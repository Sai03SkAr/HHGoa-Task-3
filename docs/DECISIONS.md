# DECISIONS — the log

> Append-only. One entry per real choice, with the reason and what would reverse it.
> If you change a decision, **add a new entry superseding it** rather than editing history.
> Evidence lives in [FINDINGS.md](FINDINGS.md); the resulting design lives in
> [../PLAN.md](../PLAN.md).

Status key: **firm** (decided, evidence-backed) · **provisional** (default chosen, revisit
cheaply) · **open** (needs a user answer — see [../PROGRESS.md](../PROGRESS.md))

---

### D-001 — Face stack: InsightFace `buffalo_l` · **firm**

RetinaFace detection + ArcFace 512-d embeddings, over `face_recognition`/dlib.

**Why.** Better embeddings, and landmarks plus a detection confidence come free — both
feed the quality gate directly. dlib needs a compiler toolchain; InsightFace resolved to
prebuilt wheels on arm64/3.12 with no build step (F-1). Warm load 0.4 s, embed ~0.11 s
(F-1), so it is comfortably fast enough for a live demo.

**Reverses if:** the model download becomes a problem for graders, or arm64 wheels break.

---

### D-002 — Python 3.12, not 3.14 · **firm**

The machine default is 3.14.4; `/opt/homebrew/bin/python3.12` exists and `uv` can fetch
3.12 anyway.

**Why.** The ML stack (onnxruntime, insightface, opencv) is not reliably packaged for
3.14 yet. 3.12 is what Task 2 used and what resolved clean here (F-1, F-6).

---

### D-003 — Reverse image search is NOT the default path · **firm**

Default search is the **scripted-search family (Mastodon)**. SerpAPI Google Lens is
supported but **off unless explicitly enabled**.

**Why.** Three independent reasons, all verified in F-4:

1. **The ladder in IDEAS.md is not buildable.** Bing Visual Search was retired Aug 11
   2025; Yandex has no API and fights bots. Two of the three rungs do not exist.
2. **SerpAPI has no upload endpoint.** It accepts a public image URL or an `image_id`.
   To reverse-search a live webcam probe you must **first publish the probe face to the
   public internet** — which directly contradicts this project's own "no raw biometrics
   leave the machine" stance. That is a genuine conflict, not a technicality.
3. **100 free searches/month is a fragile spine for a live recording.**

**The upside, not just damage control.** In the scripted path our *own* detector and
embedder decide what matches — the provider only proposes candidates. That makes Stage 1
load-bearing rather than decorative, and it satisfies requirement 2's own wording
("or a scripted search approach") while being *harder* to fake than delegating judgement
to someone else's "visual match" list.

**Consequence.** `--allow-probe-upload` gates the SerpAPI path so the privacy cost is
always a deliberate act. The README must explain this trade-off rather than bury it.

---

### D-004 — Primary search provider: Mastodon public API · **firm**

**Why.** Verified working with **no key, no quota, no anti-bot** (F-3). Returns genuine
social media posts with real permalinks, authors, timestamps and downloadable images,
federated across instances. Bluesky's public endpoint 403s from this machine (F-4), so it
becomes a keyed second rung rather than the primary.

Critically for the demo: the candidate set is live and changes minute to minute, so a
"this was hardcoded" objection dies on contact with the screen recording.

**Reverses if:** rate limits appear under real use, or the demo subject's posts are not
reachable from `mastodon.social`.

---

### D-005 — Local chain: Hardhat, not Foundry/Anvil · **superseded by D-014**

**Why (at the time).** Foundry is not installed; Node 22 and npm 11 are (F-7). Hardhat
gives a grader a plain `npm install` path.

**Superseded** once the pure-Python toolchain was found to work — see D-014. Hardhat is
retained only as an optional persistent local node.

---

### D-006 — IPFS/Pinata deferred to Tier 3 · **provisional**

Anchor the Merkle root on-chain; keep a `cid` field in the contract struct but allow it
to be empty.

**Why.** No local kubo, and Pinata needs another signup (F-7). Requirement 3 asks for a
tamper-evident record we can re-verify — the **root** delivers that on its own. IPFS adds
retrievability, not integrity, and a CID on-chain proves *what*, never *availability*.

Keeping `cid` in the struct now costs one empty string and avoids a redeploy if pinning
lands later.

---

### D-007 — Anchor a Merkle root, never raw biometrics · **firm**

On-chain: `bytes32 root` (+ optional `cid`). The embedding appears only as a **salted
commitment** `sha256(salt || embedding)`, and the salt stays local.

**Why.** Putting a face image or a raw embedding on a public chain would be permanent,
irrevocable publication of biometric data. The salted commitment still proves the
embedding existed at anchor time without revealing it — and it is what makes the
right-to-erasure story coherent: local evidence is deletable, and the anchor is a hash
rather than personal data.

---

### D-008 — Build the blockchain stage BEFORE the search stage · **firm**

Order: scaffold → face → evidence/Merkle → **chain + tamper test** → search → wire → testnet.

**Why.** Stage 3 is fully within our control and is the requirement most likely to be
under-built; Stage 2 depends on the open internet and a cooperative demo subject. Getting
the tamper test going red early means the most convincing part of the recording exists
even if the search stage stays rough. It also front-loads canonicalization, which is the
piece that silently breaks a re-verification demo.

---

### D-009 — Docker dropped; no website · **firm**

Docker is not installed and adds nothing to grading here. Requirement 4 explicitly says
no website is required.

---

### D-010 — Nested git repo, Task 1 & 2 never committed · **firm**

`/Users/saisalelkar` (the home directory) is itself a git repo pointed at an unrelated
`iOS-conversion.git`. A separate repo was initialised at
`/Users/saisalelkar/Desktop/HHGoa Task3` → `origin` = `Sai03SkAr/HHGoa-Task-3`.

`HHGoa Task1 /` and `HHGoa Task2/` are gitignored on explicit user instruction, and the
exclusion is verified with `git check-ignore`. `*.pdf` is ignored too, so the task brief
is not redistributed.

**Always** confirm `git rev-parse --show-toplevel` before any git command — committing to
the home repo by accident is the failure mode this guards against.

---

### D-011 — Threshold 0.45, stated and recorded · **provisional**

**Why.** Measured separation is enormous — 0.975+ for the same person through a web
round-trip vs −0.044 for different people (F-2) — so 0.45 errs conservative.

**Why still provisional.** That measurement does not cover *same person, different
photo*, which is the regime the demo actually runs in and which typically lands ~0.5–0.7
for ArcFace. **Re-validate with real webcam probes before locking it**, and record the
achieved score in every bundle so the decision stays auditable either way.

---

### D-012 — Demo subject · **open — needs the user**

Recommendation: the user posts their own photo publicly, then probes with a live webcam
capture. Gives a real post, a live search, an undeniably non-hardcoded match, and clean
consent in one move. See [../PLAN.md](../PLAN.md) §2.3.

---

### D-013 — Demo chain · **open — needs the user**

Recommendation: **local Hardhat as the default** (tests and CI need no faucet funds)
**plus Polygon Amoy for the recording** (easiest faucet of the three verified networks,
live explorer link). Requirement 3 accepts any chain including a local one, so the
testnet is for credibility rather than compliance — but a live explorer link is
meaningfully stronger on camera.

**Blocked on:** a funded burner address. Faucets are slow; start early.


---

### D-014 — Pure-Python chain toolchain: `py-solc-x` + `eth-tester` · **firm** *(supersedes D-005)*

Contracts compile with `py-solc-x` (which fetches solc itself) and the test suite runs
against `eth-tester` **in-process**. No Node, no Hardhat, no `node_modules` required to
build or test.

**Why.** Verified working end to end: compile → deploy → anchor → verify → read the event
back, all inside one `uv`-managed venv (F-8). This collapses the project to a **single
toolchain and a single install command**, which materially improves the "clone it and
follow the README" dry run that the submission checklist demands. It also makes the chain
stage testable on any machine with **no node, no faucet and no network**.

**What Hardhat is still for.** `eth-tester` state does not survive the process, so it
cannot back a two-command demo where `run` and `verify` are separate invocations. Hardhat
3.15.0 is installed to provide an optional **persistent** local node on `127.0.0.1:8545`
for exactly that case. It is a fallback for the demo, not a build dependency.

**Foundry was attempted and abandoned:** `foundryup` installs its launcher but fetches no
binaries on this machine. Not worth further time given `eth-tester` covers testing and
Hardhat covers persistence.

**Measured gas** (`memory` backend): deploy **757,035**, anchor **93,815**. Feeds the
cost/latency table.
