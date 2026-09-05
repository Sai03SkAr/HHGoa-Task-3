"""Merkle tree over evidence leaves.

Anchoring one root rather than one hash per artefact buys a real capability:
a single item can later be proved to a third party - just the similarity score,
say - without disclosing the probe image, the scraped page, or anything else in
the bundle. The chain stores 32 bytes either way.

Two structural details that matter more than they look:

  * **Domain separation.** Leaf hashes are prefixed 0x00 and internal nodes
    0x01. Without this, an attacker can present an internal node as if it were
    a leaf, since both are 32 bytes - the classic second-preimage attack on
    naive Merkle trees.

  * **Odd levels promote, they do not duplicate.** The widespread trick of
    duplicating the final node when a level has an odd count creates two
    distinct leaf multisets with the same root (CVE-2012-2459 in Bitcoin).
    Promoting the unpaired node up a level has no such collision.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def hash_leaf(data: bytes) -> bytes:
    """Hash a leaf payload with domain separation."""
    return sha256(LEAF_PREFIX + data)


def hash_node(left: bytes, right: bytes) -> bytes:
    """Hash two child nodes with domain separation."""
    return sha256(NODE_PREFIX + left + right)


@dataclass(frozen=True)
class ProofStep:
    """One sibling on the path from a leaf to the root."""

    sibling: bytes
    # True when the sibling sits on the left, i.e. hash(sibling || running).
    sibling_is_left: bool

    def to_json(self) -> dict:
        return {"sibling": self.sibling.hex(), "sibling_is_left": self.sibling_is_left}

    @staticmethod
    def from_json(obj: dict) -> ProofStep:
        return ProofStep(bytes.fromhex(obj["sibling"]), bool(obj["sibling_is_left"]))


class MerkleTree:
    """A Merkle tree built over pre-serialized leaf payloads.

    Leaf order is significant and is preserved exactly as given, so the caller
    controls it and the bundle records it.
    """

    def __init__(self, payloads: list[bytes]) -> None:
        if not payloads:
            # An empty tree has no meaningful root, and returning a zero root
            # would make an empty bundle verify against a real anchor.
            raise ValueError("cannot build a Merkle tree with no leaves")
        self.payloads = list(payloads)
        self.leaves = [hash_leaf(p) for p in self.payloads]
        self._levels = self._build(self.leaves)

    @staticmethod
    def _build(leaves: list[bytes]) -> list[list[bytes]]:
        levels = [list(leaves)]
        current = leaves
        while len(current) > 1:
            nxt = []
            for i in range(0, len(current) - 1, 2):
                nxt.append(hash_node(current[i], current[i + 1]))
            if len(current) % 2:
                # Promote the unpaired node unchanged - see module docstring.
                nxt.append(current[-1])
            levels.append(nxt)
            current = nxt
        return levels

    @property
    def root(self) -> bytes:
        return self._levels[-1][0]

    @property
    def root_hex(self) -> str:
        """0x-prefixed root, in the form the contract expects as bytes32."""
        return "0x" + self.root.hex()

    def proof(self, index: int) -> list[ProofStep]:
        """Sibling path proving the leaf at `index` is in this tree."""
        if not 0 <= index < len(self.leaves):
            raise IndexError(f"leaf index {index} out of range (have {len(self.leaves)})")
        steps: list[ProofStep] = []
        for level in self._levels[:-1]:
            if index == len(level) - 1 and len(level) % 2:
                # This node was promoted rather than paired; nothing to record.
                index //= 2
                continue
            if index % 2:
                steps.append(ProofStep(level[index - 1], sibling_is_left=True))
            else:
                steps.append(ProofStep(level[index + 1], sibling_is_left=False))
            index //= 2
        return steps


def verify_proof(payload: bytes, steps: list[ProofStep], root: bytes) -> bool:
    """Recompute the root from a leaf payload and its sibling path."""
    running = hash_leaf(payload)
    for step in steps:
        running = (
            hash_node(step.sibling, running)
            if step.sibling_is_left
            else hash_node(running, step.sibling)
        )
    return running == root
