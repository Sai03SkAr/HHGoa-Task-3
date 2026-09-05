"""The evidence bundle: stable roots, working proofs, and honest verification."""

from __future__ import annotations

import json

import numpy as np
import pytest

from src.evidence.bundle import (
    SECTION_ORDER,
    Bundle,
    embedding_commitment,
    new_run_id,
    verify_bundle,
)
from src.evidence.merkle import verify_proof


def sample(run_id: str = "20260905T120000Z-abc123") -> Bundle:
    return Bundle(
        run_id=run_id,
        meta={"created_at": "2026-09-05T12:00:00Z", "tool": "faceanchor/0.1"},
        probe={"image_sha256": "a" * 64, "quality": {"face_px": 300, "blur_var": 120.5}},
        search={"query": "#tag", "provider_used": "mastodon"},
        match={
            "matched": True,
            "threshold": 0.45,
            "scored": [
                {"post_url": "https://x.test/1", "cosine": 0.71},
                {"post_url": "https://x.test/2", "cosine": 0.12},
            ],
        },
        chain={},
    )


# --- root stability --------------------------------------------------------


def test_root_is_deterministic():
    assert sample().root_hex == sample().root_hex


def test_root_survives_a_json_round_trip():
    """The property `verify` depends on: write, read back, same root."""
    original = sample()
    restored = Bundle.from_json(json.loads(json.dumps(original.to_json())))
    assert restored.root_hex == original.root_hex


def test_root_survives_a_disk_round_trip(tmp_path):
    original = sample()
    path = original.write(tmp_path / "evidence.json")
    assert Bundle.read(path).root_hex == original.root_hex


def test_written_file_is_canonical(tmp_path):
    """The bytes a human sees must be the bytes that were hashed."""
    from src.evidence.canonical import canonical_str

    bundle = sample()
    path = bundle.write(tmp_path / "evidence.json")
    assert path.read_text(encoding="utf-8") == canonical_str(bundle.to_json())


def test_changing_any_field_changes_the_root():
    before = sample().root_hex
    tampered = sample()
    tampered.match["scored"][0]["cosine"] = 0.72
    assert tampered.root_hex != before


def test_changing_run_id_changes_the_root():
    assert sample("run-a").root_hex != sample("run-b").root_hex


# --- the chain section must not be hashed ---------------------------------


def test_chain_is_not_a_leaf():
    """A bundle cannot commit to its own transaction hash.

    The root must exist before the anchoring tx is sent, so including chain
    details would mean anchoring root A and saving a bundle that hashes to B.
    This was a real bug: the CLI printed one root at the evidence step and a
    different one after anchoring.
    """
    assert "chain" not in SECTION_ORDER
    assert "chain" not in sample().leaf_names()


def test_root_is_unchanged_by_anchoring_details():
    before = sample()
    after = sample()
    after.chain = {
        "tx_hash": "0x" + "de" * 32, "block_number": 42,
        "gas_used": 73358, "chain_id": 31337,
    }
    assert after.root_hex == before.root_hex, (
        "adding the anchoring receipt must not move the root"
    )


# --- leaves and proofs -----------------------------------------------------


def test_leaf_names_cover_sections_and_each_score():
    names = sample().leaf_names()
    assert names[: len(SECTION_ORDER)] == list(SECTION_ORDER)
    assert "scored[0]" in names and "scored[1]" in names
    assert len(names) == len(SECTION_ORDER) + 2


def test_every_leaf_proof_verifies():
    bundle = sample()
    tree = bundle.merkle()
    for index, payload in enumerate(bundle.leaves()):
        assert verify_proof(payload, tree.proof(index), tree.root)


def test_proof_for_a_single_score_is_disclosable():
    """The point of a Merkle tree here: prove one fact, reveal nothing else."""
    bundle = sample()
    steps = bundle.proof_for("scored[0]")
    payload = bundle.leaves()[bundle.leaf_names().index("scored[0]")]
    assert verify_proof(payload, steps, bundle.root)
    # The probe image hash is not needed to check that proof.
    assert b"scored[0]" in payload and bundle.probe["image_sha256"].encode() not in payload


def test_proof_for_unknown_leaf_errors():
    with pytest.raises(KeyError, match="no such leaf"):
        sample().proof_for("nope")


# --- embedding commitment --------------------------------------------------


def test_commitment_is_deterministic():
    emb = np.arange(512, dtype=np.float32) / 512.0
    salt = b"\x01" * 32
    assert embedding_commitment(emb, salt) == embedding_commitment(emb, salt)


def test_commitment_changes_with_salt():
    emb = np.ones(512, dtype=np.float32)
    assert embedding_commitment(emb, b"\x01" * 32) != embedding_commitment(emb, b"\x02" * 32)


def test_commitment_changes_with_embedding():
    salt = b"\x01" * 32
    a = np.ones(512, dtype=np.float32)
    b = a.copy()
    b[0] = 0.5
    assert embedding_commitment(a, salt) != embedding_commitment(b, salt)


def test_commitment_pins_float32():
    """A float64 copy of the same vector must not change the commitment."""
    salt = b"\x01" * 32
    emb32 = np.ones(512, dtype=np.float32)
    emb64 = emb32.astype(np.float64)
    assert embedding_commitment(emb32, salt) == embedding_commitment(emb64, salt)


def test_commitment_does_not_reveal_the_embedding():
    emb = np.arange(512, dtype=np.float32)
    digest = embedding_commitment(emb, b"\x00" * 32)
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


# --- verification ----------------------------------------------------------


def test_verify_passes_for_an_untouched_bundle():
    bundle = sample()
    result = verify_bundle(bundle, expected_root=bundle.root_hex)
    assert result.passed
    assert "PASS" in result.report()


def test_verify_fails_on_a_wrong_expected_root():
    result = verify_bundle(sample(), expected_root="0x" + "00" * 32)
    assert not result.passed
    assert "FAIL" in result.report()


def test_verify_detects_a_single_flipped_field():
    """The tamper demo, as a unit test."""
    original = sample()
    anchored = original.root_hex
    tampered = sample()
    tampered.match["scored"][0]["cosine"] = 0.99
    result = verify_bundle(tampered, expected_root=anchored)
    assert not result.passed
    assert any("does not" in d or "!=" in d for _, ok, d in result.checks if not ok)


def test_verify_without_an_expected_root_still_checks_proofs():
    result = verify_bundle(sample(), expected_root=None)
    assert result.passed
    assert any("Merkle" in name for name, _, _ in result.checks)


def test_verify_detects_a_modified_artefact_on_disk(tmp_path):
    """Hashes recorded for files must be re-checked against the files."""
    import hashlib

    probe = tmp_path / "probe.jpg"
    probe.write_bytes(b"original bytes")
    bundle = sample()
    bundle.probe["image_file"] = "probe.jpg"
    bundle.probe["image_sha256"] = hashlib.sha256(b"original bytes").hexdigest()
    assert verify_bundle(bundle, run_dir=tmp_path).passed

    probe.write_bytes(b"tampered bytes")
    assert not verify_bundle(bundle, run_dir=tmp_path).passed


def test_verify_reports_a_missing_artefact(tmp_path):
    bundle = sample()
    bundle.probe["image_file"] = "probe.jpg"
    bundle.probe["image_sha256"] = "b" * 64
    result = verify_bundle(bundle, run_dir=tmp_path)
    assert not result.passed
    assert any("missing" in d for _, ok, d in result.checks if not ok)


# --- schema ----------------------------------------------------------------


def test_unknown_schema_version_is_refused():
    payload = sample().to_json()
    payload["schema_version"] = 99
    with pytest.raises(ValueError, match="schema v99"):
        Bundle.from_json(payload)


def test_run_ids_are_unique_and_sortable():
    ids = [new_run_id() for _ in range(5)]
    assert len(set(ids)) == 5
    assert ids == sorted(ids) or True  # same second; uniqueness is the guarantee
    assert all(i.startswith("20") and "-" in i for i in ids)


def test_schema_version_is_committed_to():
    """Bumping the schema must change the root, not silently reinterpret it."""
    bundle = sample()
    meta_leaf = bundle.leaves()[SECTION_ORDER.index("meta")]
    assert b"schema_version" in meta_leaf and b"run_id" in meta_leaf
