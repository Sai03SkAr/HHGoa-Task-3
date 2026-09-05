"""Merkle tree: proofs must verify, and tampering must break them."""

from __future__ import annotations

import hashlib

import pytest

from src.evidence.merkle import (
    LEAF_PREFIX,
    NODE_PREFIX,
    MerkleTree,
    ProofStep,
    hash_leaf,
    hash_node,
    verify_proof,
)


def payloads(n: int) -> list[bytes]:
    return [f"leaf-{i}".encode() for i in range(n)]


def test_single_leaf_root_is_the_leaf_hash():
    tree = MerkleTree([b"only"])
    assert tree.root == hash_leaf(b"only")


def test_two_leaves_matches_hand_computation():
    tree = MerkleTree([b"a", b"b"])
    expected = hash_node(hash_leaf(b"a"), hash_leaf(b"b"))
    assert tree.root == expected


def test_empty_tree_rejected():
    # A zero root would let an empty bundle verify against a real anchor.
    with pytest.raises(ValueError):
        MerkleTree([])


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 7, 8, 9, 16, 17, 33])
def test_every_proof_verifies(n):
    items = payloads(n)
    tree = MerkleTree(items)
    for i, payload in enumerate(items):
        assert verify_proof(payload, tree.proof(i), tree.root), f"leaf {i} of {n}"


@pytest.mark.parametrize("n", [2, 3, 8, 9])
def test_proof_fails_for_wrong_payload(n):
    items = payloads(n)
    tree = MerkleTree(items)
    proof = tree.proof(0)
    assert not verify_proof(b"not-in-the-tree", proof, tree.root)


def test_proof_fails_against_wrong_root():
    tree = MerkleTree(payloads(4))
    other = MerkleTree(payloads(5))
    assert not verify_proof(b"leaf-0", tree.proof(0), other.root)


def test_leaf_order_changes_the_root():
    """Order is part of what is being committed to."""
    assert MerkleTree([b"a", b"b"]).root != MerkleTree([b"b", b"a"]).root


def test_flipping_one_byte_changes_the_root():
    """The property the tamper demo rests on."""
    before = MerkleTree([b"probe", b"score:0.61", b"url"]).root
    after = MerkleTree([b"probe", b"score:0.62", b"url"]).root
    assert before != after


def test_domain_separation_between_leaf_and_node():
    """An internal node must not be presentable as a leaf.

    Both are 32 bytes; without distinct prefixes an attacker could offer an
    inner node as a leaf payload and produce a valid-looking proof.
    """
    assert LEAF_PREFIX != NODE_PREFIX
    data = b"x" * 32
    assert hash_leaf(data) != hashlib.sha256(data).digest()
    assert hash_leaf(data + data) != hash_node(data, data)


def test_odd_level_promotes_rather_than_duplicates():
    """Guards against the Bitcoin CVE-2012-2459 duplication collision.

    If an odd final node were duplicated, [a, b, c] and [a, b, c, c] would
    share a root, so two different evidence sets would satisfy one anchor.
    """
    three = MerkleTree([b"a", b"b", b"c"])
    four_dup = MerkleTree([b"a", b"b", b"c", b"c"])
    assert three.root != four_dup.root


def test_root_hex_is_bytes32_shaped():
    root_hex = MerkleTree(payloads(3)).root_hex
    assert root_hex.startswith("0x")
    assert len(root_hex) == 66  # 0x + 64 hex chars
    assert bytes.fromhex(root_hex[2:]) == MerkleTree(payloads(3)).root


def test_proof_step_json_round_trip():
    tree = MerkleTree(payloads(5))
    for step in tree.proof(2):
        assert ProofStep.from_json(step.to_json()) == step


def test_proof_survives_json_round_trip():
    """Proofs are stored in the bundle as JSON and re-read by `verify`."""
    items = payloads(6)
    tree = MerkleTree(items)
    serialized = [s.to_json() for s in tree.proof(3)]
    restored = [ProofStep.from_json(s) for s in serialized]
    assert verify_proof(items[3], restored, tree.root)


def test_index_out_of_range():
    tree = MerkleTree(payloads(3))
    with pytest.raises(IndexError):
        tree.proof(3)
    with pytest.raises(IndexError):
        tree.proof(-1)
