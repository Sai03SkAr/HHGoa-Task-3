"""Compile, deploy and talk to EvidenceRegistry.

Stage 3. Deliberately chain-agnostic: the task accepts "public testnet, mainnet,
or a local/simulated chain - as long as you can demonstrate re-verifying the
data against the on-chain record". So the network is a config value and the
re-verification path is identical everywhere.

Three transports, one interface:

  * ``memory``  - eth-tester, in-process. Used by the test suite: no node, no
    faucet, no network, and it resets between runs. State does NOT survive the
    process, so it cannot back a two-command demo.
  * ``local``   - a persistent JSON-RPC node on 127.0.0.1:8545 (anvil). Survives
    between ``run`` and ``verify``, needs no faucet.
  * a testnet   - Polygon Amoy / Sepolia / Base Sepolia over public RPC, signing
    locally with a burner key.

The compiler is `py-solc-x`, which fetches solc itself. That keeps the whole
project a single `uv` install with no Node toolchain - see docs/DECISIONS.md
D-005 (revised).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

log = logging.getLogger(__name__)

SOLC_VERSION = "0.8.24"
CONTRACT_PATH = Path(__file__).resolve().parents[2] / "contracts" / "EvidenceRegistry.sol"
CONTRACT_NAME = "EvidenceRegistry"


@dataclass(frozen=True)
class Network:
    name: str
    chain_id: int | None
    rpc: str | None
    explorer_tx: str | None  # format string with {tx}
    # Proof-of-authority chains put oversized data in the extraData header
    # field, which web3's default validation rejects outright.
    poa: bool = False

    def explorer_url(self, tx_hash: str) -> str | None:
        return self.explorer_tx.format(tx=tx_hash) if self.explorer_tx else None


NETWORKS: dict[str, Network] = {
    # In-process, for tests only.
    "memory": Network("memory", None, None, None),
    # Persistent local node (anvil / hardhat node). No faucet needed.
    "local": Network("local", 31337, "http://127.0.0.1:8545", None),
    # Public testnets. RPCs verified reachable - see docs/FINDINGS.md F-5.
    # Note both RPC URLs suggested in IDEAS.md are dead; these are the
    # replacements.
    "amoy": Network(
        "polygon-amoy", 80002,
        "https://polygon-amoy-bor-rpc.publicnode.com",
        "https://amoy.polygonscan.com/tx/{tx}", poa=True,
    ),
    "sepolia": Network(
        "sepolia", 11155111,
        "https://ethereum-sepolia-rpc.publicnode.com",
        "https://sepolia.etherscan.io/tx/{tx}",
    ),
    "base-sepolia": Network(
        "base-sepolia", 84532,
        "https://sepolia.base.org",
        "https://sepolia.basescan.org/tx/{tx}",
    ),
}


class ChainError(Exception):
    pass


@dataclass
class Receipt:
    """Everything worth printing about an anchoring transaction."""

    tx_hash: str
    block_number: int
    gas_used: int
    chain_id: int
    network: str
    contract: str
    explorer_url: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "tx_hash": self.tx_hash,
            "block_number": self.block_number,
            "gas_used": self.gas_used,
            "chain_id": self.chain_id,
            "network": self.network,
            "contract": self.contract,
            "explorer_url": self.explorer_url,
        }


@lru_cache(maxsize=1)
def compile_contract() -> tuple[list[dict], str]:
    """Compile EvidenceRegistry.sol, returning (abi, bytecode).

    Cached: solc takes a moment and the source never changes mid-run.
    """
    import solcx

    if SOLC_VERSION not in {str(v) for v in solcx.get_installed_solc_versions()}:
        log.info("installing solc %s (one time)", SOLC_VERSION)
        solcx.install_solc(SOLC_VERSION)

    compiled = solcx.compile_source(
        CONTRACT_PATH.read_text(),
        output_values=["abi", "bin"],
        solc_version=SOLC_VERSION,
        # Without this the compiler emits a warning about the unnamed source.
        base_path=str(CONTRACT_PATH.parent),
    )
    key = next(k for k in compiled if k.endswith(f":{CONTRACT_NAME}"))
    return compiled[key]["abi"], compiled[key]["bin"]


class ChainClient:
    """Talks to one network. Signs locally when a private key is supplied."""

    def __init__(self, network: str = "memory", private_key: str | None = None,
                 rpc_url: str | None = None) -> None:
        if network not in NETWORKS:
            raise ChainError(
                f"unknown network {network!r}; expected one of {', '.join(NETWORKS)}"
            )
        self.net = NETWORKS[network]
        self.account = None

        if network == "memory":
            from web3 import EthereumTesterProvider

            self.w3 = Web3(EthereumTesterProvider())
            self.sender = self.w3.eth.accounts[0]
        else:
            url = rpc_url or self.net.rpc
            self.w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 30}))
            if self.net.poa:
                self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            if not self.w3.is_connected():
                raise ChainError(
                    f"cannot reach {self.net.name} at {url}. "
                    + ("Start one with:  npx hardhat node" if network == "local"
                       else "Check your connection or set RPC_URL.")
                )
            if private_key:
                from eth_account import Account

                self.account = Account.from_key(private_key)
                self.sender = self.account.address
            elif network == "local":
                # anvil unlocks its dev accounts, so a key is optional locally.
                self.sender = self.w3.eth.accounts[0]
            else:
                raise ChainError(
                    f"{self.net.name} needs a PRIVATE_KEY to sign transactions. "
                    "Generate a burner with: python -m src.cli wallet-new"
                )

    @property
    def chain_id(self) -> int:
        return self.w3.eth.chain_id

    def balance_eth(self) -> float:
        return float(self.w3.from_wei(self.w3.eth.get_balance(self.sender), "ether"))

    def _send(self, fn) -> Any:
        """Send a transaction, signing locally when we hold the key."""
        if self.account is None:
            tx_hash = fn.transact({"from": self.sender})
        else:
            tx = fn.build_transaction({
                "from": self.sender,
                "nonce": self.w3.eth.get_transaction_count(self.sender),
                "chainId": self.chain_id,
            })
            signed = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

    def deploy(self) -> str:
        """Deploy a fresh EvidenceRegistry and return its address."""
        abi, bytecode = compile_contract()
        factory = self.w3.eth.contract(abi=abi, bytecode=bytecode)
        receipt = self._send(factory.constructor())
        address = receipt.contractAddress
        log.info("deployed %s at %s (gas %s)", CONTRACT_NAME, address, receipt.gasUsed)
        return address

    def at(self, address: str):
        """Bind to a deployed registry, checking there is really one there.

        Without the code check, pointing at an address that holds no contract -
        the usual cause being a CONTRACT_ADDRESS left over from a different
        network, or a local node that has been restarted since - surfaces as
        web3's `BadFunctionCallOutput: could not decode contract function call`,
        which says nothing about the actual mistake.
        """
        abi, _ = compile_contract()
        checksummed = Web3.to_checksum_address(address)
        if self.w3.eth.get_code(checksummed) in (b"", "0x", b"0x"):
            raise ChainError(
                f"no contract deployed at {checksummed} on {self.net.name} "
                f"(chain id {self.chain_id}).\n"
                "  A CONTRACT_ADDRESS from a different network, or a local node "
                "restarted since it was deployed, both look like this.\n"
                "  Deploy a fresh one with:  python -m src.cli deploy"
            )
        return self.w3.eth.contract(address=checksummed, abi=abi)

    def anchor(self, address: str, root: bytes, cid: str = "") -> Receipt:
        """Anchor a Merkle root. Raises if it is already on chain."""
        if len(root) != 32:
            raise ChainError(f"root must be 32 bytes, got {len(root)}")
        contract = self.at(address)
        found, _ = contract.functions.verify(root).call()
        if found:
            # Surfaced here rather than as a raw revert, because re-running a
            # demo against an unchanged bundle hits this every time.
            raise ChainError(
                f"root 0x{root.hex()} is already anchored on {self.net.name}. "
                "The evidence is unchanged since the last run - this is the "
                "contract refusing to overwrite an existing timestamp."
            )
        receipt = self._send(contract.functions.anchor(root, cid))
        tx_hash = receipt.transactionHash.hex()
        if not tx_hash.startswith("0x"):
            tx_hash = "0x" + tx_hash
        return Receipt(
            tx_hash=tx_hash,
            block_number=receipt.blockNumber,
            gas_used=receipt.gasUsed,
            chain_id=self.chain_id,
            network=self.net.name,
            contract=address,
            explorer_url=self.net.explorer_url(tx_hash),
        )

    def lookup(self, address: str, root: bytes) -> dict[str, Any] | None:
        """Read an anchor back. None when the root was never anchored."""
        found, record = self.at(address).functions.verify(root).call()
        if not found:
            return None
        return {
            "root": "0x" + bytes(record[0]).hex(),
            "cid": record[1],
            "submitter": record[2],
            "timestamp": int(record[3]),
        }

    def anchor_from_tx(self, tx_hash: str) -> dict[str, Any] | None:
        """Recover the anchored root and CID from a transaction hash.

        This is the path `verify --tx` takes: given only a transaction, pull the
        Anchored event out of its receipt and re-derive what was committed to,
        without trusting any local file.
        """
        abi, _ = compile_contract()
        receipt = self.w3.eth.get_transaction_receipt(tx_hash)
        contract = self.w3.eth.contract(address=receipt.to, abi=abi)
        events = contract.events.Anchored().process_receipt(receipt)
        if not events:
            return None
        args = events[0].args
        return {
            "root": "0x" + bytes(args.root).hex(),
            "cid": args.cid,
            "submitter": args.submitter,
            "timestamp": int(args.timestamp),
            "contract": receipt.to,
            "block_number": receipt.blockNumber,
        }
