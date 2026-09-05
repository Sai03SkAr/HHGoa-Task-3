"""faceanchor - face scan -> social media search -> blockchain anchor.

Two verbs:

    python -m src.cli run    --image probe.jpg --query '#sometag'
    python -m src.cli verify --run runs/<run_id>
    python -m src.cli verify --tx 0xabc...

Everything printed here also lands in the run directory, so the terminal is a
view of the evidence rather than the only record of it.

Exit codes, chosen so scripts can tell outcomes from failures:

    0  success - `run` matched, or `verify` passed
    1  a legitimate negative - no match found, or verification FAILED.
       The pipeline worked; the answer was no.
    2  bad input or unusable configuration - unreadable probe, missing
       arguments, unreachable chain
    3  no candidates returned by any search provider
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .chain.registry import NETWORKS, ChainClient, ChainError
from .evidence.bundle import Bundle, embedding_commitment, new_run_id, verify_bundle
from .evidence.canonical import canonical_str
from .face.encoder import FaceEncoder, FaceError, sha256_file
from .scrape.fetch import FetchError, fetch_page
from .search.base import SearchTrail, run_ladder, utc_now
from .search.mastodon import MastodonProvider
from .search.matcher import DEFAULT_THRESHOLD, adjudicate

app = typer.Typer(add_completion=False, help=__doc__)
console = Console()

RUNS_DIR = Path("runs")
CACHE_DIR = Path(".cache/search")


def _load_env() -> None:
    """Minimal .env loader - avoids a dependency for six lines of parsing."""
    path = Path(".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(message)s",
        stream=sys.stdout,
    )
    # httpx logs every request at INFO, which drowns the pipeline's own output.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _chain_from_env(network: str | None) -> tuple[str, str | None, str | None]:
    return (
        network or os.environ.get("CHAIN", "memory"),
        os.environ.get("PRIVATE_KEY") or None,
        os.environ.get("CONTRACT_ADDRESS") or None,
    )


# --- run -------------------------------------------------------------------


@app.command()
def run(
    image: Path = typer.Option(..., "--image", "-i", help="Probe image (a face scan)."),
    query: str = typer.Option(..., "--query", "-q",
                              help="Search query: '#hashtag' or '@user@instance'."),
    network: Optional[str] = typer.Option(None, "--network", "-n",
                                          help=f"One of: {', '.join(NETWORKS)}"),
    contract: Optional[str] = typer.Option(None, "--contract", help="Deployed registry address."),
    threshold: float = typer.Option(None, "--threshold", "-t", help="Cosine match bar."),
    limit: int = typer.Option(10, "--limit", help="Max posts to pull from the provider."),
    max_images: int = typer.Option(
        3, "--max-images",
        help="Max images scored per post. Each costs a download plus an embed, "
             "so this is the main lever on runtime.",
    ),
    no_anchor: bool = typer.Option(False, "--no-anchor", help="Run the pipeline, skip the chain."),
    verbose: bool = typer.Option(True, "--verbose/--quiet"),
) -> None:
    """Run the full pipeline and anchor the evidence on chain."""
    _load_env()
    _setup_logging(verbose)
    threshold = threshold if threshold is not None else float(
        os.environ.get("MATCH_THRESHOLD", DEFAULT_THRESHOLD)
    )

    run_id = new_run_id()
    run_dir = RUNS_DIR / run_id
    console.print(Panel.fit(f"[bold]run {run_id}[/bold]\n{utc_now()}", border_style="cyan"))

    # --- stage 1: face ---------------------------------------------------
    console.rule("[bold cyan]1 · face")
    encoder = FaceEncoder()
    try:
        probe = encoder.encode_file(image)
    except FaceError as exc:
        # A refusal with its measurement is a result, not a crash. The run
        # directory is deliberately not created until the probe passes -
        # otherwise every rejected probe leaves an empty directory behind.
        console.print(f"[red]probe rejected:[/red] {exc}")
        raise typer.Exit(2)

    run_dir.mkdir(parents=True, exist_ok=True)
    probe_copy = run_dir / "probe.jpg"
    probe_copy.write_bytes(Path(image).read_bytes())
    # The salt keeps the embedding commitment from being brute-forceable and
    # never leaves this directory.
    salt = os.urandom(32)
    (run_dir / "salt.bin").write_bytes(salt)

    quality = probe.quality
    console.print(f"  detector      {encoder.detector_id}")
    console.print(f"  face          {quality.face_px}px wide, det_score {quality.det_score:.3f}")
    console.print(f"  quality       blur {quality.blur_var:.1f}, yaw ratio {quality.yaw_ratio:.3f}")
    for note in probe.notes:
        console.print(f"  [yellow]note[/yellow]          {note}")
    console.print("  [green]quality gate passed[/green]")

    # --- stage 2: search -------------------------------------------------
    console.rule("[bold cyan]2 · search")
    trail = SearchTrail(run_dir=run_dir, cache_dir=CACHE_DIR)
    providers = [MastodonProvider(os.environ.get("MASTODON_INSTANCE", "https://mastodon.social"))]
    console.print(f"  query         {query}")
    console.print(f"  ladder        {' -> '.join(p.name for p in providers)}")
    ladder = run_ladder(providers, query, trail, limit=limit)
    for name, note in ladder.notes.items():
        console.print(f"  [yellow]fell through[/yellow]  {name}: {note}")
    if not ladder.candidates:
        console.print("[red]no candidates returned by any provider[/red]")
        raise typer.Exit(3)
    console.print(f"  [green]{len(ladder.candidates)} candidate posts[/green] via {ladder.provider_used}")

    # --- stage 2b: adjudicate --------------------------------------------
    console.rule("[bold cyan]3 · verify candidates (our encoder decides)")
    result = adjudicate(probe.embedding, ladder.candidates, encoder,
                        threshold=threshold, workdir=run_dir / "candidates",
                        max_images_per_candidate=max_images)

    table = Table(box=None, pad_edge=False)
    table.add_column("cosine", justify="right")
    table.add_column("author")
    table.add_column("post / reason", overflow="fold")
    for entry in result.scored[:12]:
        score = f"{entry.cosine:.4f}" if entry.ok else "  -   "
        style = "green" if (entry.ok and entry.cosine >= threshold) else ""
        table.add_row(score, entry.author[:24],
                      entry.post_url if entry.ok else f"[dim]{entry.error[:70]}[/dim]",
                      style=style)
    console.print(table)
    console.print(f"  threshold     {threshold}")
    console.print(f"  [bold]{result.summary()}[/bold]")

    # --- stage 3b: scrape the matched post -------------------------------
    page_meta = None
    if result.matched and result.best:
        console.rule("[bold cyan]4 · scrape matched post")
        try:
            page, page_meta = fetch_page(result.best.post_url)
            (run_dir / "page.html").write_bytes(page.content)
            console.print(f"  page          {len(page.content)} bytes, sha256 {page.sha256[:16]}…")
            console.print(f"  og:title      {page_meta.og_title[:70]}")
        except FetchError as exc:
            console.print(f"  [yellow]could not fetch the post page:[/yellow] {exc}")

    # --- build the bundle -------------------------------------------------
    console.rule("[bold cyan]5 · evidence")
    bundle = Bundle(
        run_id=run_id,
        meta={
            "created_at": utc_now(),
            "tool": "faceanchor/0.1",
            "detector": encoder.detector_id,
        },
        probe={
            "image_file": "probe.jpg",
            "image_sha256": sha256_file(probe_copy),
            # The embedding itself is never published - see D-007.
            "embedding_commitment": embedding_commitment(probe.embedding, salt),
            "quality": quality.to_json(),
            "faces_seen": probe.faces_seen,
        },
        search={
            "query": query,
            **ladder.to_json(),
            "trail": trail.to_json(),
        },
        match={
            **result.to_json(),
            "page_html_file": "page.html" if page_meta else "",
            "page_html_sha256": (
                __import__("hashlib").sha256((run_dir / "page.html").read_bytes()).hexdigest()
                if page_meta else ""
            ),
            "page_meta": page_meta.to_json() if page_meta else None,
        },
        chain={},
    )

    tree = bundle.merkle()
    console.print(f"  leaves        {len(bundle.leaf_names())}")
    console.print(f"  merkle root   [bold]{tree.root_hex}[/bold]")

    # --- anchor -----------------------------------------------------------
    receipt = None
    if not no_anchor:
        console.rule("[bold cyan]6 · anchor on chain")
        net, key, address = _chain_from_env(network)
        address = contract or address
        if net == "memory":
            # The in-process chain is created fresh for this process and dies
            # with it, so any configured CONTRACT_ADDRESS belongs to a
            # different chain. Deploy every time rather than fail confusingly.
            address = None
        try:
            client = ChainClient(net, private_key=key)
            if not address:
                console.print(f"  no contract for {net} - deploying…")
                address = client.deploy()
                console.print(f"  deployed      {address}")
            receipt = client.anchor(address, tree.root, cid="")
            bundle.chain = {
                "network": receipt.network,
                "chain_id": receipt.chain_id,
                "contract": receipt.contract,
                "tx_hash": receipt.tx_hash,
                "block_number": receipt.block_number,
                "gas_used": receipt.gas_used,
                "root": tree.root_hex,
            }
            console.print(f"  network       {receipt.network} (chain id {receipt.chain_id})")
            console.print(f"  tx            [bold]{receipt.tx_hash}[/bold]")
            console.print(f"  block         {receipt.block_number}   gas {receipt.gas_used}")
            if receipt.explorer_url:
                console.print(f"  explorer      {receipt.explorer_url}")
        except ChainError as exc:
            console.print(f"  [red]anchoring failed:[/red] {exc}")
            bundle.chain = {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - web3 raises its own hierarchy
            # A chain problem must not destroy a run whose face and search work
            # already succeeded: the evidence is still written, just unanchored.
            console.print(f"  [red]anchoring failed:[/red] {type(exc).__name__}: {exc}")
            bundle.chain = {"error": f"{type(exc).__name__}: {exc}"}

    # The bundle is written last: chain details are part of what it commits to,
    # so the root printed above is recomputed here with them included.
    bundle.write(run_dir / "evidence.json")
    (run_dir / "receipt.json").write_text(
        canonical_str({
            "run_id": run_id,
            "root": bundle.root_hex,
            "chain": bundle.chain,
            "matched": result.matched,
        }),
        encoding="utf-8",
    )

    console.rule("[bold cyan]done")
    console.print(f"  evidence      {run_dir}/evidence.json")
    console.print(f"  final root    [bold]{bundle.root_hex}[/bold]")
    console.print(f"\n  verify with:  [bold]python -m src.cli verify --run {run_dir}[/bold]")
    if not result.matched:
        # A no-match run is a legitimate, fully-evidenced outcome.
        raise typer.Exit(1)


# --- verify ----------------------------------------------------------------


@app.command()
def verify(
    run_dir: Optional[Path] = typer.Option(None, "--run", help="Run directory to verify."),
    tx: Optional[str] = typer.Option(None, "--tx", help="Anchoring transaction hash."),
    network: Optional[str] = typer.Option(None, "--network", "-n"),
    verbose: bool = typer.Option(False, "--verbose/--quiet"),
) -> None:
    """Re-derive a bundle from disk and check it against the on-chain record."""
    _load_env()
    _setup_logging(verbose)

    if not run_dir and not tx:
        console.print("[red]give --run <dir> or --tx <hash>[/red]")
        raise typer.Exit(2)

    anchored_root: str | None = None
    chain_info: dict | None = None

    # --- start from the chain when given a tx ----------------------------
    if tx:
        net, key, _ = _chain_from_env(network)
        console.rule(f"[bold cyan]on-chain record ({net})")
        try:
            client = ChainClient(net, private_key=key)
            chain_info = client.anchor_from_tx(tx)
        except ChainError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(2)
        if not chain_info:
            console.print(f"[red]no Anchored event in transaction {tx}[/red]")
            raise typer.Exit(1)
        anchored_root = chain_info["root"]
        console.print(f"  root          {anchored_root}")
        console.print(f"  contract      {chain_info['contract']}")
        console.print(f"  block         {chain_info['block_number']}")
        console.print(f"  submitter     {chain_info['submitter']}")

        if not run_dir:
            # Find the local bundle that reproduces this root.
            run_dir = _find_run_by_root(anchored_root)
            if not run_dir:
                console.print(
                    f"[red]no local run reproduces {anchored_root}[/red]\n"
                    "The anchor exists on chain but the evidence is not on this machine."
                )
                raise typer.Exit(1)
            console.print(f"  local bundle  {run_dir}")

    # --- re-derive from disk ---------------------------------------------
    console.rule("[bold cyan]re-derived from evidence.json")
    evidence_path = Path(run_dir) / "evidence.json"
    if not evidence_path.exists():
        console.print(f"[red]no evidence.json in {run_dir}[/red]")
        raise typer.Exit(2)

    try:
        bundle = Bundle.read(evidence_path)
    except Exception as exc:  # noqa: BLE001 - a mangled bundle is a FAIL, not a traceback
        console.print(f"[red]FAIL[/red]  evidence.json could not be parsed: {exc}")
        raise typer.Exit(1)

    # When no tx was given, fall back to what the bundle says it anchored - but
    # only treat it as an on-chain fact if a chain actually confirms it.
    # `root_from_chain` tracks that distinction, because claiming "matches the
    # on-chain anchor" without consulting a chain is the most misleading thing
    # this command could print.
    root_from_chain = tx is not None
    if anchored_root is None:
        recorded = bundle.chain.get("root")
        contract_addr = bundle.chain.get("contract")
        net = network or bundle.chain.get("network") or os.environ.get("CHAIN", "memory")
        anchored_root = recorded
        if recorded and contract_addr and _normalize_net(net) != "memory":
            try:
                client = ChainClient(_normalize_net(net), private_key=os.environ.get("PRIVATE_KEY"))
                found = client.lookup(contract_addr, bytes.fromhex(recorded[2:]))
                if found:
                    anchored_root = found["root"]
                    root_from_chain = True
                    console.print(f"  chain lookup  found on {net}")
                else:
                    # The chain answered, and the answer is that this root was
                    # never anchored. That is a genuine failure, not an
                    # unverifiable one.
                    anchored_root = None
                    root_from_chain = True
                    console.print(f"  chain lookup  [red]NOT FOUND[/red] on {net}")
            except (ChainError, Exception) as exc:  # noqa: BLE001
                console.print(f"  [yellow]chain unreachable:[/yellow] {exc}")
        elif _normalize_net(net) == "memory":
            console.print(
                "  [yellow]chain lookup  skipped[/yellow] - the 'memory' chain is "
                "in-process and does not outlive the run that created it"
            )

    if root_from_chain and anchored_root is None:
        console.print()
        console.print(Panel.fit(
            "[bold red]FAIL[/bold red] — this root is not anchored on the chain",
            border_style="red"))
        raise typer.Exit(1)

    result = verify_bundle(bundle, expected_root=anchored_root,
                           run_dir=Path(run_dir), root_from_chain=root_from_chain)

    marks = {
        "pass": "[green]PASS[/green]",
        "fail": "[red]FAIL[/red]",
        "unverified": "[yellow]????[/yellow]",
    }
    for name, status, detail in result.checks:
        console.print(f"  {marks[status]}  {name}" + (f"  [dim]{detail}[/dim]" if detail else ""))

    console.print()
    if not result.passed:
        console.print(Panel.fit("[bold red]FAIL[/bold red] — evidence does not match",
                                border_style="red"))
        raise typer.Exit(1)
    if result.has_unverified:
        console.print(Panel.fit(
            "[bold yellow]INCOMPLETE[/bold yellow] — the evidence is internally "
            "consistent,\nbut it was NOT checked against a blockchain",
            border_style="yellow"))
        # Exit 0: nothing is wrong. The caller is told plainly what was not done.
        return
    console.print(Panel.fit("[bold green]PASS[/bold green] — evidence matches the anchored root",
                            border_style="green"))


def _normalize_net(name: str) -> str:
    """Bundles record a display name ('polygon-amoy'); config uses a key ('amoy')."""
    if name in NETWORKS:
        return name
    for key, net in NETWORKS.items():
        if net.name == name:
            return key
    return name


def _find_run_by_root(root_hex: str) -> Path | None:
    """Locate the local run whose bundle recomputes to `root_hex`.

    Recomputes rather than trusting each bundle's recorded root - otherwise a
    tampered bundle could claim any anchor it liked.
    """
    if not RUNS_DIR.exists():
        return None
    for candidate in sorted(RUNS_DIR.iterdir(), reverse=True):
        path = candidate / "evidence.json"
        if not path.exists():
            continue
        try:
            if Bundle.read(path).root_hex.lower() == root_hex.lower():
                return candidate
        except Exception:  # noqa: BLE001 - unreadable bundles simply do not match
            continue
    return None


# --- helpers ---------------------------------------------------------------


@app.command("wallet-new")
def wallet_new() -> None:
    """Generate a burner keypair for testnet use."""
    from eth_account import Account

    account = Account.create()
    # eth-account's .hex() dropped the 0x prefix in recent versions. Both forms
    # load fine, but .env.example shows the prefixed form and a key that looks
    # different from the documented one invites a "did I paste it right?" pause
    # mid-demo.
    private_key = "0x" + account.key.hex().removeprefix("0x")
    console.print(Panel.fit(
        f"[bold]address[/bold]      {account.address}\n"
        f"[bold]private key[/bold]  {private_key}",
        title="burner wallet", border_style="yellow",
    ))
    console.print(
        "\n[yellow]Testnet use only.[/yellow] Put the key in [bold].env[/bold] as "
        "PRIVATE_KEY (gitignored).\nNever send real funds to this address.\n"
        "Fund it from a faucet - see docs/USER_ACTIONS.md A-2."
    )


@app.command()
def deploy(
    network: Optional[str] = typer.Option(None, "--network", "-n"),
    verbose: bool = typer.Option(True, "--verbose/--quiet"),
) -> None:
    """Deploy EvidenceRegistry and print the address for .env."""
    _load_env()
    _setup_logging(verbose)
    net, key, _ = _chain_from_env(network)
    client = ChainClient(net, private_key=key)
    console.print(f"deploying to {net} (chain id {client.chain_id}) as {client.sender}")
    if net != "memory":
        console.print(f"balance: {client.balance_eth():.6f}")
    address = client.deploy()
    console.print(Panel.fit(f"CONTRACT_ADDRESS={address}", border_style="green"))


if __name__ == "__main__":
    app()
