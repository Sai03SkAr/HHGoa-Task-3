# faceanchor

**A face scan finds a real social media post, and the evidence is anchored on a blockchain so anyone can prove it was not altered afterwards.**

HH Goa 2026 — Shortlisting Task 3.

```
face scan  →  social media search  →  our encoder adjudicates  →  Merkle root anchored on chain  →  re-verify
```

---

## What this project does

Most builds of this task are a linear pipe where every step trusts the last:

```
face → reverse image search → take the first URL → hash it → send to chain
```

Nothing there verifies anything. The URL is believed because a search engine returned it,
and the chain records a hash of an answer nobody checked.

**faceanchor is a closed verification loop.** The face model is not just an encoder at the
front — it is the *adjudicator* of the search:

```
                    ┌──────────────────────────────┐
  probe image ─────►│ 1. detect / quality / embed  │──── probe_emb ──┐
                    └──────────────────────────────┘                 │
                                   │                                 │
                                   ▼                                 │
                    ┌──────────────────────────────┐                 │
                    │ 2. search providers (ladder) │                 │
                    │    returns CANDIDATES only   │                 │
                    └──────────────────────────────┘                 │
                                   │ candidate posts + images        │
                                   ▼                                 │
                    ┌──────────────────────────────┐                 │
                    │ 3. download each image and   │                 │
                    │    RE-EMBED it ourselves     │◄────────────────┘
                    │    cosine ≥ threshold ?      │
                    └──────────────────────────────┘
                                   │ verdict + every score
                                   ▼
                    ┌──────────────────────────────┐
                    │ 4. canonicalize → Merkle root│
                    │    → anchor tx on chain      │
                    └──────────────────────────────┘
                                   │
                                   ▼
                     verify --tx 0x…  →  PASS / FAIL
```

A search provider proposes posts. **Nothing about its ranking is trusted.** Every
candidate image is downloaded and run through the same encoder that read the probe, and a
cosine score decides. The score is recorded whether it passes or fails.

Three properties follow from that, and they are the point of the project:

- **The search step is checkable, not merely asserted.** Every HTTP request and its raw
  response body are written to disk and hashed into the evidence. A reader can replay
  exactly what was asked and what came back.
- **The system can fail.** A run that matches nothing still produces a complete evidence
  bundle showing what it looked at and what each candidate scored. A pipeline that could
  only ever report success would prove nothing.
- **What is anchored is the whole bundle**, not a URL — probe hash, every candidate image
  hash, the page HTML hash, all scores, the full search trail, timestamps — combined into
  one Merkle root.

### It really does tell people apart

From a live run against one account's public posts (`docs/FINDINGS.md` F-11):

| cosine | what it is |
|---|---|
| `0.9995` | the probe's own source photo |
| `0.7632` `0.7607` `0.7603` | **same person, different photos** — different day, lighting, pose |
| `0.0668` | **a different person appearing in that same account's photos** |
| `—` | two images with no detectable face, recorded with the reason |

The `0.0668` row is the one that matters. A pipeline that accepted whatever the search
returned would have taken that person as a match. Ours rejects them, on the strength of a
number it publishes.

---

## How to run it

### Prerequisites

- **Python 3.12** (3.14 is too new for the ML stack) and [`uv`](https://docs.astral.sh/uv/)
- **Node 20+** — *only* for an optional persistent local chain. The pipeline itself is
  pure Python; Solidity is compiled by `py-solc-x`.
- ~1 GB disk. The first run downloads **281 MB** of face-model weights.

### Setup

```bash
make setup
cp .env.example .env
```

Then pre-warm the model and compiler, so nothing downloads at an awkward moment:

```bash
make prewarm
```

**Everything works with a completely empty `.env`.** No API keys are required: the
default search provider needs no credentials and the default chain is local.

### Run it — the zero-friction path, no faucet, no keys

In one terminal, start a local chain:

```bash
make node
```

In another, deploy the registry and put the printed address in `.env`:

```bash
make deploy
```

Then run the pipeline and verify it:

```bash
.venv/bin/python -m src.cli run --image probe.jpg --query '#portrait'
.venv/bin/python -m src.cli verify --run runs/<run_id>
```

`--query` takes either a hashtag (`#portrait`) or an account (`@user@instance.social`).

### Verify from nothing but a transaction hash

```bash
.venv/bin/python -m src.cli verify --tx 0xabc...
```

This pulls the anchored root out of the transaction's event log, finds the local bundle
that reproduces that root — by recomputing, not by trusting what any bundle claims — and
re-derives everything.

### The tamper test

```bash
.venv/bin/python -m src.cli verify --run runs/<run_id>      # PASS, exit 0
# change a single digit of one cosine score in evidence.json
.venv/bin/python -m src.cli verify --run runs/<run_id>      # FAIL, exit 1
```

One altered field — zero change in file length — produces a completely different root,
and `verify` prints the computed and anchored roots side by side.

Tampering is caught three independent ways:

| What you change | What catches it |
|---|---|
| any field in `evidence.json` | the recomputed Merkle root |
| `probe.jpg`, leaving the JSON untouched | the artefact hash recorded in the bundle |
| **the evidence *and* the bundle's own recorded root**, so the file is self-consistent | **the chain** — that root was never anchored |

The third case is the one the blockchain actually earns its place for. A self-consistent
forgery defeats every local check; only the on-chain record catches it.

### Exit codes

| code | meaning |
|---|---|
| `0` | success — `run` matched, or `verify` passed |
| `1` | **a legitimate negative**: no match found, or verification FAILED. The pipeline worked; the answer was no |
| `2` | bad input or configuration — unreadable probe, unreachable chain |
| `3` | no candidates returned by any search provider |

### When verification cannot reach a chain

`verify` will **never** claim a root "matches the on-chain anchor" unless it actually read
that root from a chain. If no chain can be consulted — the ephemeral `memory` chain, or a
node that is down — the check is reported as `????` **UNVERIFIED** and the verdict is
**INCOMPLETE**, not PASS:

```
  ????  root matches the on-chain anchor   NOT CHECKED - no chain was consulted, so this
        compares the bundle against its own recorded root, which a tampered bundle would
        also change
```

Without that distinction the tool would produce a confident green PASS for a check it
never performed, which is worse than no check at all.

### Tests

```bash
make test        # full suite, loads the real model
make test-fast   # no model load, no network
```

**139 fast tests, plus 9 that load the real model.** The chain tests run entirely
in-process on `eth-tester` — no node, no faucet, no network.

> Very occasionally (once in ~17 runs) the full suite aborts at interpreter teardown with
> `libc++abi ... recursive_mutex lock failed`, *after* every test has reported passing.
> It is a native teardown race in onnxruntime/opencv on macOS, not a test failure.
> Re-run it. Details in `docs/FINDINGS.md` F-14.

### What a run leaves behind

```
runs/<run_id>/
├── evidence.json      the bundle, written in canonical form
├── receipt.json       root, tx, chain
├── probe.jpg          the probe image
├── salt.bin           salt for the embedding commitment - never leaves this directory
├── page.html          the matched post, as fetched  (only on a match)
├── candidates/        every image that was downloaded and scored
└── search_trail/      raw provider responses, byte for byte
```

`evidence.json` is written **in canonical form**, so the bytes a human opens are the bytes
that were hashed — `sha256 evidence.json` is a meaningful check.

---

## Which blockchain

**Any EVM chain.** The network is a config value and the re-verification path is identical
everywhere, because the task accepts *"public testnet, mainnet, or a local/simulated
chain — as long as you can demonstrate re-verifying the data against the on-chain
record."*

| `CHAIN=` | What it is | Needs funds? |
|---|---|---|
| `memory` | `eth-tester`, in-process. Used by the test suite. | no |
| `local` | **Default.** Persistent node on `127.0.0.1:8545` via `npx hardhat node`. | no |
| `amoy` | Polygon Amoy testnet (chain id **80002**) | yes — faucet |
| `sepolia` | Ethereum Sepolia (chain id **11155111**) | yes — faucet |
| `base-sepolia` | Base Sepolia (chain id **84532**) | yes — faucet |

**Why a local chain is the default.** It needs no faucet, so a grader can clone this repo
and see the full loop — including the tamper test — in about two minutes without waiting
on anyone. **Polygon Amoy** is the recommended public target for a demo with a live
explorer link; its faucet is the least painful of the three.

> **Deployed testnet contract:** _not yet deployed — pending faucet funding._
> Once deployed, the address and its explorer link go here.

### The contract

[`contracts/EvidenceRegistry.sol`](contracts/EvidenceRegistry.sol) — deliberately minimal.
The sophistication of this project is in *what gets hashed*, not in Solidity.

```solidity
function anchor(bytes32 root, string calldata cid) external;
function verify(bytes32 root) external view returns (bool, Anchor memory);
```

Anchors are immutable by construction: no update path, no owner, and re-anchoring an
existing root reverts rather than silently overwriting its timestamp — which is the only
thing an anchor actually proves.

Measured cost: deploy **757,035 gas**, anchor **93,815 gas**.

### No biometrics ever go on chain

The contract never receives a face image or a raw embedding. The embedding appears only as
a **salted commitment**, `sha256(salt || embedding)`, and the salt stays in the local run
directory.

This is not decoration. A public chain is permanent and irrevocable — publishing biometric
data to one would be unfixable. It is also what makes erasure coherent: **the local
evidence is deletable, and what remains on chain is a hash that was never personal data.**

---

## Known limitations

Stated plainly, because most of these are properties of the problem rather than bugs.

**The threshold is a tunable, not a truth.** The default is cosine **≥ 0.45**. On real
Mastodon photos, *same person, different photo* had a median of **0.698** and two different
people scored **−0.044** (`docs/FINDINGS.md` F-9). The useful part is that the threshold
sits in an **empty valley**: moving it from 0.30 to 0.50 changes the verdict for only
**1.1%** of pairs, so the exact value is not load-bearing. But it is still a dial, and a
different population would move it.

**The recall figure is rough, not measured.** ~87.5% of cross-post pairs from one account
cleared 0.45. That was one account, one apparent ethnicity, favourable lighting, and the
pairs were not hand-labelled — some below the bar are genuinely other people. Treat it as
calibration, not a benchmark.

**Face recognition is demographically biased.** ArcFace and every model like it perform
unevenly across skin tone, age and gender, and error rates are typically worst for
already-marginalised groups. Nothing here corrects for that, and the calibration above
came from a single subject, so it says nothing about how the threshold behaves for anyone
else.

**We search Mastodon, not "the web", and reverse image search is not implemented.**
Bing's Visual Search API was retired in August 2025, Yandex has no official API, and
SerpAPI's Google Lens accepts only a *public image URL* — it has no upload endpoint, so
reverse-searching a webcam probe would mean **publishing the probe face to the public
internet first**. That directly contradicts this project's own privacy stance, so it was
not built rather than built and disabled. The ladder runs across several Mastodon
instances, each with its own federated view.

The honest consequence: this searches **real, live, federated social media**, but a
genuinely narrower slice of the internet than a reverse image search would reach. If the
person you are looking for posts only on Instagram, this will not find them.

**Results change minute to minute.** A hashtag timeline is live. Re-running the same query
tomorrow returns different posts, which is exactly why the search trail is hashed into the
evidence — the bundle records what *was* returned, not what would be returned now.

**An anchor proves integrity and time, not truth.** It proves this evidence existed in this
exact form by that block. It does not prove the match is correct, that the post is
authentic, or that the person consented. Evidence integrity and evidential value are
different things.

**Availability is not proven either.** The `cid` field exists for an IPFS bundle but
pinning is not implemented. A CID on chain would prove *what*, never *that it is still
retrievable*.

**Recent anchors can reorg.** A transaction that is one block deep is not final. For a
testnet demo, wait a few confirmations before treating an anchor as settled.

**No consent verification in the pipeline.** The code cannot tell whether the person in a
scraped photo agreed to any of this. That is a policy problem, and we do not pretend the
tooling solves it — see below.

**The quality gate is deliberately loose on candidates.** The probe is gated; candidate
images are not, because we do not control the quality of someone else's posted photo and
rejecting them would silently discard real matches. Low-quality candidates therefore
produce noisier scores.

**No page screenshots.** The design sketch called for a Playwright screenshot of the
matched post as visual evidence. It is not implemented: it adds a ~150 MB browser download
and a fragile dependency, and the **raw page HTML is hashed into the bundle anyway**, which
is stronger evidence than an image of a rendered page. The bundle schema and `verify`
already handle a `screenshot_sha256` if one is ever added.

---

## Ethics

The underlying capability — identifying a stranger from a photo — is genuinely dangerous,
and this repo is a demonstration, not a product.

- **No raw biometrics leave the machine.** On chain: a salted commitment only.
- **The reverse-image-search path is opt-in**, precisely because it requires publishing the
  probe face publicly.
- **Right to erasure:** delete `runs/<run_id>/` and the biometric data is gone. The
  on-chain anchor is a hash that was never personal data — which is what makes deletion
  meaningful rather than theatrical.
- **What we would not ship without:** a consent allowlist enforced at the probe, blurring
  of bystanders in stored evidence, an audit log of who ran what, and a bias evaluation
  across skin tones on a labelled dataset. None of those are in this build, and it should
  not be used on anyone who has not agreed to it.

---

## Project documentation

| Doc | What it is for |
|---|---|
| [CONTEXT.md](CONTEXT.md) | Pick the project up cold — the task, constraints, environment |
| [PLAN.md](PLAN.md) | Architecture, scope tiers, build order |
| [PROGRESS.md](PROGRESS.md) | Live status, blockers, risks |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Every real choice, with its reason |
| [docs/FINDINGS.md](docs/FINDINGS.md) | Measured evidence only, with the commands |
| [docs/USER_ACTIONS.md](docs/USER_ACTIONS.md) | The steps that need a human |

---

## Repo layout

```
src/
├── face/encoder.py      detect · multi-face policy · quality gate · 512-d embed
├── search/
│   ├── base.py          SearchProvider interface · provider ladder · search trail
│   ├── mastodon.py      the only provider - no key, no quota, one per instance
│   └── matcher.py       the closed loop: re-embed candidates and adjudicate
├── scrape/fetch.py      bounded downloads · content sniffing · OpenGraph
├── evidence/
│   ├── canonical.py     deterministic JSON - the reason verification reproduces
│   ├── merkle.py        Merkle tree with domain separation
│   └── bundle.py        assembly · salted commitment · verification
├── chain/registry.py    compile · deploy · anchor · verify · recover-from-tx
└── cli.py               run · verify · deploy · wallet-new
contracts/EvidenceRegistry.sol
tests/                   139 fast + 9 model-loading
```
