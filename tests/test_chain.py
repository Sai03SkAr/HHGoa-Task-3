"""Stage 3: anchoring and re-verification against the on-chain record.

Runs entirely in-process on eth-tester - no node, no faucet, no network. That
is the point: the chain stage stays testable on any machine.
"""

from __future__ import annotations

import pytest

from src.chain.registry import NETWORKS, ChainClient, ChainError, compile_contract
from src.evidence.merkle import MerkleTree

ROOT_A = bytes.fromhex("ab" * 32)
ROOT_B = bytes.fromhex("cd" * 32)


@pytest.fixture(scope="module")
def client() -> ChainClient:
    return ChainClient("memory")


@pytest.fixture
def deployed(client) -> str:
    return client.deploy()


def test_contract_compiles():
    abi, bytecode = compile_contract()
    assert bytecode, "no bytecode produced"
    names = {entry.get("name") for entry in abi}
    assert {"anchor", "verify", "Anchored"} <= names


def test_deploy_returns_an_address(client):
    address = client.deploy()
    assert address.startswith("0x") and len(address) == 42


def test_anchor_then_lookup_round_trip(client, deployed):
    receipt = client.anchor(deployed, ROOT_A, "ipfs://demo")
    assert receipt.tx_hash.startswith("0x")
    assert receipt.gas_used > 0
    assert receipt.block_number > 0

    record = client.lookup(deployed, ROOT_A)
    assert record is not None
    assert record["root"] == "0x" + ROOT_A.hex()
    assert record["cid"] == "ipfs://demo"
    assert record["timestamp"] > 0


def test_unanchored_root_is_absent(client, deployed):
    client.anchor(deployed, ROOT_A)
    assert client.lookup(deployed, ROOT_B) is None


def test_reanchoring_is_refused(client, deployed):
    """An anchor's whole value is its timestamp; overwriting would destroy it."""
    client.anchor(deployed, ROOT_A)
    with pytest.raises(ChainError, match="already anchored"):
        client.anchor(deployed, ROOT_A)


def test_zero_root_rejected(client, deployed):
    with pytest.raises(Exception):
        client.anchor(deployed, bytes(32))


def test_wrong_root_length_rejected(client, deployed):
    with pytest.raises(ChainError, match="32 bytes"):
        client.anchor(deployed, b"\x01" * 31)


def test_recover_anchor_from_tx_hash(client, deployed):
    """The `verify --tx` path: start from a transaction, trust no local file."""
    receipt = client.anchor(deployed, ROOT_A, "ipfs://xyz")
    recovered = client.anchor_from_tx(receipt.tx_hash)
    assert recovered is not None
    assert recovered["root"] == "0x" + ROOT_A.hex()
    assert recovered["cid"] == "ipfs://xyz"
    assert recovered["block_number"] == receipt.block_number


def test_tamper_detection_end_to_end(client, deployed):
    """The demo's closing move, as a test.

    Anchor a bundle, alter one leaf, and confirm the recomputed root no longer
    matches what the chain holds.
    """
    leaves = [b"probe:aaa", b"cosine:0.612000", b"url:https://example.test/post/1"]
    original = MerkleTree(leaves)
    client.anchor(deployed, original.root)
    assert client.lookup(deployed, original.root) is not None

    tampered = MerkleTree([leaves[0], b"cosine:0.912000", leaves[2]])
    assert tampered.root != original.root
    assert client.lookup(deployed, tampered.root) is None, (
        "a tampered bundle must not resolve against the chain"
    )


def test_anchor_survives_a_full_merkle_round_trip(client, deployed):
    tree = MerkleTree([b"a", b"b", b"c", b"d", b"e"])
    receipt = client.anchor(deployed, tree.root)
    record = client.lookup(deployed, tree.root)
    assert record["root"] == tree.root_hex
    assert receipt.chain_id == client.chain_id


def test_empty_cid_is_allowed(client, deployed):
    """IPFS is optional - see docs/DECISIONS.md D-006."""
    client.anchor(deployed, ROOT_A, "")
    assert client.lookup(deployed, ROOT_A)["cid"] == ""


# --- configuration ---------------------------------------------------------


def test_unknown_network_rejected():
    with pytest.raises(ChainError, match="unknown network"):
        ChainClient("mainnet-oops")


def test_testnet_without_key_fails_clearly():
    """A missing key must not surface as an obscure signing error later."""
    with pytest.raises(ChainError, match="PRIVATE_KEY"):
        ChainClient("amoy")


@pytest.mark.parametrize("name", ["amoy", "sepolia", "base-sepolia"])
def test_testnets_have_explorer_links(name):
    net = NETWORKS[name]
    url = net.explorer_url("0xdeadbeef")
    assert url and url.startswith("https://") and "0xdeadbeef" in url
    assert net.chain_id and net.rpc


def test_dead_rpcs_from_ideas_md_are_not_used():
    """Both endpoints suggested in IDEAS.md are dead - see FINDINGS F-5."""
    configured = {n.rpc for n in NETWORKS.values() if n.rpc}
    assert "https://rpc.sepolia.org" not in configured
    assert "https://rpc-amoy.polygon.technology" not in configured
