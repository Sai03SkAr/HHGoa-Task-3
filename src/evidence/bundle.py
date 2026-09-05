"""Assembling, hashing and re-verifying the evidence bundle.

What actually gets anchored. The bundle is a set of named **leaves**, each
canonicalized and hashed independently, combined into a Merkle tree whose root
is the 32 bytes that go on chain.

Leaves rather than one blob, for a reason worth stating: a Merkle proof lets a
single fact be shown to a third party - "this run scored 0.71" - without
handing over the probe image, the scraped page, or anything else. Hashing the
bundle as one document would force all-or-nothing disclosure.

The embedding is recorded only as a **salted commitment**, never in the clear:

    embedding_commitment = sha256(salt || embedding_bytes)

The salt stays local, in the run directory. This proves the embedding existed
unaltered at anchor time while publishing nothing biometric - see
docs/DECISIONS.md D-007, and the note in contracts/EvidenceRegistry.sol.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .canonical import canonical, canonical_str
from .merkle import MerkleTree, ProofStep, verify_proof

SCHEMA_VERSION = 1

# Leaf order is fixed and explicit. It is part of what the root commits to, so
# it must never depend on dict iteration order or on how many candidates a run
# happened to score.
#
# `chain` is deliberately NOT a leaf, and that is a correctness requirement
# rather than an oversight. The root has to exist before the anchoring
# transaction can be sent, so a bundle cannot commit to its own transaction
# hash, block number or gas - including them would mean anchoring root A and
# then saving a bundle that hashes to root B, and every later verification
# would fail. The `chain` section is therefore a *receipt for* the anchor, not
# part of the evidence being anchored: it is recorded alongside the bundle for
# convenience, and verification checks it against the chain instead of hashing
# it.
SECTION_ORDER = ("meta", "probe", "search", "match")


def new_run_id() -> str:
    """Timestamped, collision-resistant, and sorts chronologically."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{os.urandom(3).hex()}"


def embedding_commitment(embedding: np.ndarray, salt: bytes) -> str:
    """sha256(salt || embedding). The only form an embedding is published in.

    float32 is pinned explicitly: the commitment must be reproducible, and a
    float64 copy of the same vector would hash differently.
    """
    raw = np.asarray(embedding, dtype=np.float32).tobytes()
    return hashlib.sha256(salt + raw).hexdigest()


@dataclass
class Bundle:
    """The evidence for one run."""

    run_id: str
    meta: dict[str, Any] = field(default_factory=dict)
    probe: dict[str, Any] = field(default_factory=dict)
    search: dict[str, Any] = field(default_factory=dict)
    match: dict[str, Any] = field(default_factory=dict)
    chain: dict[str, Any] = field(default_factory=dict)

    # --- leaves ---------------------------------------------------------

    def leaf_names(self) -> list[str]:
        """Names of every leaf, in the fixed order the tree is built in."""
        names = list(SECTION_ORDER)
        # Each scored candidate is its own leaf, so one score can be proved in
        # isolation. Indexed rather than named by URL: a URL is attacker-chosen
        # and could collide with a section name.
        for i in range(len(self.match.get("scored", []))):
            names.append(f"scored[{i}]")
        return names

    def _leaf_value(self, name: str) -> Any:
        """The data a named section leaf commits to.

        `meta` carries the run id and schema version as well as its own fields.
        Without that, two runs whose evidence happened to be identical would
        share a root - and since the registry refuses to overwrite an existing
        anchor, the second run would fail as "already anchored". Binding the
        run id into the hashed data makes each run's root its own.
        """
        if name == "meta":
            return {**self.meta, "run_id": self.run_id, "schema_version": SCHEMA_VERSION}
        return getattr(self, name)

    def leaves(self) -> list[bytes]:
        """Canonical payload for every leaf, in `leaf_names()` order."""
        payloads = [canonical({name: self._leaf_value(name)}) for name in SECTION_ORDER]
        for i, item in enumerate(self.match.get("scored", [])):
            payloads.append(canonical({f"scored[{i}]": item}))
        return payloads

    def merkle(self) -> MerkleTree:
        return MerkleTree(self.leaves())

    @property
    def root(self) -> bytes:
        return self.merkle().root

    @property
    def root_hex(self) -> str:
        return self.merkle().root_hex

    def proof_for(self, name: str) -> list[ProofStep]:
        """Merkle proof for one named leaf."""
        names = self.leaf_names()
        if name not in names:
            raise KeyError(f"no such leaf {name!r}; have {', '.join(names)}")
        return self.merkle().proof(names.index(name))

    # --- serialization --------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "meta": self.meta,
            "probe": self.probe,
            "search": self.search,
            "match": self.match,
            "chain": self.chain,
        }

    @staticmethod
    def from_json(payload: dict[str, Any]) -> Bundle:
        version = payload.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"bundle schema v{version} but this build understands v{SCHEMA_VERSION}"
            )
        return Bundle(
            run_id=payload["run_id"],
            meta=payload.get("meta", {}),
            probe=payload.get("probe", {}),
            search=payload.get("search", {}),
            match=payload.get("match", {}),
            chain=payload.get("chain", {}),
        )

    def write(self, path: Path) -> Path:
        """Write the bundle in canonical form.

        Canonical on disk too, not merely at hash time: it means the file a
        human opens is byte-identical to the bytes that were hashed, so
        `sha256 evidence.json` on the command line is a meaningful check.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_str(self.to_json()), encoding="utf-8")
        return path

    @staticmethod
    def read(path: Path) -> Bundle:
        return Bundle.from_json(json.loads(Path(path).read_text(encoding="utf-8")))


# --- verification ----------------------------------------------------------


@dataclass
class VerifyResult:
    """Outcome of re-deriving a bundle's root and comparing it to the chain."""

    passed: bool
    computed_root: str
    expected_root: str | None = None
    # (name, status, detail) where status is "pass", "fail" or "unverified".
    checks: list[tuple[str, str, str]] = field(default_factory=list)
    # True only when the expected root was actually read from a chain.
    chain_checked: bool = False

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, "pass" if ok else "fail", detail))
        if not ok:
            self.passed = False

    def add_unverified(self, name: str, detail: str = "") -> None:
        """Record something that could not be checked.

        Not a failure - nothing was shown to be wrong - but emphatically not a
        pass either. It never sets `passed` to False, so it cannot mask a real
        result, and the CLI renders the overall verdict differently when one is
        present.
        """
        self.checks.append((name, "unverified", detail))

    @property
    def has_unverified(self) -> bool:
        return any(status == "unverified" for _, status, _ in self.checks)

    def report(self) -> str:
        marks = {"pass": "PASS", "fail": "FAIL", "unverified": "????"}
        lines = [f"{marks[status]}  {name}" + (f"  - {d}" if d else "")
                 for name, status, d in self.checks]
        lines.append("")
        if not self.passed:
            lines.append("FAIL")
        elif self.has_unverified:
            lines.append("PASS (INCOMPLETE - see unverified checks)")
        else:
            lines.append("PASS")
        return "\n".join(lines)


def verify_bundle(bundle: Bundle, expected_root: str | None = None,
                  run_dir: Path | None = None,
                  root_from_chain: bool = True) -> VerifyResult:
    """Recompute everything derivable from the bundle and its run directory.

    Deliberately re-derives rather than trusting any value recorded inside the
    bundle: a tampered bundle would otherwise simply carry a tampered root.

    `root_from_chain` says where `expected_root` came from, and it changes what
    this function is entitled to claim. When the root was read from a chain,
    a match is real evidence of integrity. When the chain could not be reached -
    or never persisted, as with the in-process test chain - the only available
    comparison is against the root the bundle records about *itself*, which is
    circular: an attacker editing the evidence would edit that too. In that
    case the check is reported as UNVERIFIED rather than as a pass, because
    quietly printing "matches the on-chain anchor" when no chain was consulted
    would be the single most misleading thing this tool could do.
    """
    computed = bundle.root_hex
    result = VerifyResult(passed=True, computed_root=computed, expected_root=expected_root)

    result.add("bundle canonicalizes and hashes", True, computed)

    # Every leaf's own proof must verify against the root we just computed.
    tree = bundle.merkle()
    payloads = bundle.leaves()
    bad = [
        name for name, payload, index in zip(bundle.leaf_names(), payloads, range(len(payloads)))
        if not verify_proof(payload, tree.proof(index), tree.root)
    ]
    result.add("all Merkle proofs verify", not bad,
               f"{len(payloads)} leaves" if not bad else f"failed: {', '.join(bad)}")

    if expected_root is not None:
        matches = computed.lower() == expected_root.lower()
        if root_from_chain:
            result.chain_checked = True
            result.add(
                "root matches the on-chain anchor", matches,
                computed if matches else f"computed {computed} != anchored {expected_root}",
            )
        elif not matches:
            # Still worth reporting: the bundle contradicts even itself.
            result.add(
                "root matches the root recorded in the bundle", False,
                f"computed {computed} != recorded {expected_root}",
            )
        else:
            result.add_unverified(
                "root matches the on-chain anchor",
                "NOT CHECKED - no chain was consulted, so this compares the "
                "bundle against its own recorded root, which a tampered bundle "
                "would also change",
            )
    else:
        result.add_unverified(
            "root matches the on-chain anchor",
            "NOT CHECKED - the bundle records no anchor",
        )

    # Re-hash the artefacts on disk against what the bundle claims about them.
    if run_dir is not None:
        for label, key, filename in (
            ("probe image", "image_sha256", bundle.probe.get("image_file", "")),
            ("screenshot", "screenshot_sha256", bundle.match.get("screenshot_file", "")),
            ("page HTML", "page_html_sha256", bundle.match.get("page_html_file", "")),
        ):
            expected_hash = bundle.probe.get(key) or bundle.match.get(key)
            if not filename or not expected_hash:
                continue
            path = Path(run_dir) / filename
            if not path.exists():
                result.add(f"{label} present", False, f"missing {filename}")
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            result.add(f"{label} hash", actual == expected_hash,
                       filename if actual == expected_hash
                       else f"{filename}: {actual[:16]}… != {expected_hash[:16]}…")

    return result
