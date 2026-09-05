# PROGRESS — live status

> **The one file to read to know where things stand.** Update it whenever something
> lands, breaks, or unblocks. Start at [CONTEXT.md](CONTEXT.md) if you are cold.
>
> **Last updated:** 2026-09-05 · **Phase: pipeline complete, audited, and pushed.**
> All five technical requirements are met and verified on the local-chain path.

---

## Read this first if you are picking up cold

**The project works.** Face → search → adjudicate → anchor → verify, end to end, verified
against live data and a real chain. A fresh clone from GitHub was set up and run from
scratch as a grader would, and it worked.

**Repo:** https://github.com/Sai03SkAr/HHGoa-Task-3 — public, 4 commits, everything pushed.
Local checkout: `/Users/saisalelkar/Desktop/HHGoa Task3`.

**144 tests pass.** `make test-fast` (135, no model, no network) · `make test` (all 144).

**Nothing is blocked on code.** What remains is three human actions and the recording.

---

## What is left, in order

1. **A-1 — the demo subject.** The only thing standing between here and a *personal*
   demo: Sai posts a photo publicly (Mastodon, ~5 min) and sends the hashtag + handle.
   Full instructions in [docs/USER_ACTIONS.md](docs/USER_ACTIONS.md). Until then the
   pipeline demonstrates correctly against any public account — see F-11.
2. **A-2 — testnet funding** *(optional)*. Only needed for a live explorer link. The local
   chain fully satisfies requirement 3. Deploy with `python -m src.cli deploy --network amoy`
   once a burner address is funded (`python -m src.cli wallet-new` generates one).
   **If this happens, put the contract address + explorer link in the README** — there is a
   placeholder marked `not yet deployed` under "Which blockchain".
3. **Rehearse and record.** Shot list in [PLAN.md](PLAN.md) §7. Run `make prewarm` first so
   nothing downloads mid-take.
4. **Fresh-clone dry run before submitting.** Already done once (F-12), but repeat it after
   any further change — the submission checklist demands it and there are no resubmissions.
5. **Submit** — repo link + recording link + https://forms.gle/oZbQGuwiNeHVcHWo8

---

## Status by requirement

| # | Requirement | Status | Where |
|---|---|---|---|
| 1 | Face identification | ✅ **done** | `src/face/encoder.py` — detect, multi-face policy, quality gate that reports its measurements, 512-d ArcFace embed |
| 2 | Social media / web search | ✅ **done** | `src/search/` — provider ladder across Mastodon instances, hashed search trail, and the closed loop where our own encoder adjudicates |
| 3 | Blockchain verification | ✅ **done** | `contracts/EvidenceRegistry.sol` + `src/chain/registry.py` — anchor, verify, recover from a bare tx hash, three tamper vectors caught |
| 4 | No website | ✅ n/a | Explicitly not required |
| 5 | GitHub repo + README | ✅ **done** | Pushed. README covers all four required sections |
| — | Evidence core | ✅ **done** | `src/evidence/` — canonical JSON + Merkle with domain separation |
| — | Screen recording | ⬜ **not started** | Shot list ready, [PLAN.md](PLAN.md) §7 |

---

## How to run it right now

```bash
cd "/Users/saisalelkar/Desktop/HHGoa Task3"
make node                      # terminal 1: local chain on 127.0.0.1:8545
make deploy                    # terminal 2: prints CONTRACT_ADDRESS -> put it in .env
make demo PROBE=tests/fixtures/person_a.jpg QUERY='#portrait'
make verify
```

`.env` exists locally and is gitignored. It currently points at `CHAIN=local` with
Hardhat's public dev key — worthless, local-only, safe.

---

## What has been verified, with evidence

Everything below was actually run; details and raw output in
[docs/FINDINGS.md](docs/FINDINGS.md).

| | Result |
|---|---|
| **Positive match** (F-11) | 0.9995 on the source photo, **0.76 on the same person's other photos**, and **0.0668 correctly rejecting a different person in the same account** |
| **Negative case** (F-10) | Correctly reports NO MATCH with the full score table and a reason for every unusable image |
| **Threshold calibration** (F-9) | Same person cross-post median **0.698**; different people **−0.044**. 0.45 sits in an empty valley — moving it 0.30→0.50 changes only **1.1%** of verdicts |
| **Tamper detection** (F-12) | Three independent vectors, including a **self-consistent forgery** that only the chain catches |
| **Fresh clone** (F-12) | `git clone` → `make setup` → `make test` → all pass, on a directory that had never seen the project |
| **Ladder fall-through** (F-13) | Dead first instance → visible fall-through → run completes on the next rung |
| **Runtime** (F-11) | ~16 s end to end for 3 posts / 12 images, including model load and the anchor tx |

---

## Open issues

### ⚠️ Rare native crash at test teardown — F-14

Seen **once in ~17 runs**: `libc++abi ... recursive_mutex lock failed` / `Abort trap: 6`
*after* all 144 tests reported passing. A native teardown race in onnxruntime/opencv, not
a correctness problem. **Workaround: re-run.** Do not debug it on camera.

### 🟡 README testnet placeholder

Under "Which blockchain" there is a line reading *"not yet deployed — pending faucet
funding"*. If A-2 happens, replace it with the real address and explorer link. If it does
not, the line is still accurate and honest — leave it.

---

## Blockers needing a human

### A-1 · Demo subject — *blocks only a personal demo* 🟡

The pipeline needs the probe face to appear in a public post to match **Sai specifically**.
It is otherwise fully working (F-11). Recommendation and step-by-step in
[docs/USER_ACTIONS.md](docs/USER_ACTIONS.md) A-1.

### A-2 · Testnet funding — *optional* 🟢

Only for a live explorer link. Local chain is compliant. Polygon Amoy has the easiest
faucet. Do not spend more than ~20 minutes fighting one.

---

## Known risks for the recording

| Risk | Mitigation |
|---|---|
| 281 MB model download mid-take | `make prewarm` before recording |
| Live API flaking | Ladder falls through visibly; responses cached in `.cache/` |
| Long runtime if `--limit` is raised | Defaults (`--limit 10 --max-images 3`) are tuned for a demo. **Do not raise them mid-demo** — a `--limit 12` run did not finish in 7 minutes |
| The teardown flake (F-14) | Re-run; it is not a correctness issue |
| Node not running | `make node` in a separate terminal first; the error message says exactly this |

---

## Deliberately not built

Each was a decision, not an oversight — see [docs/DECISIONS.md](docs/DECISIONS.md).

- **Reverse image search / SerpAPI** (D-015) — requires publishing the probe face publicly,
  and an untestable keyed provider two days from a hard deadline buys nothing. The README
  previously claimed this was "supported but off by default"; that was false and is fixed.
- **IPFS pinning** (D-006) — the `cid` field exists and is anchored; pinning is not wired.
  A CID proves *what*, never *availability*.
- **Playwright screenshots** — the page HTML is hashed already, which is stronger evidence
  than a picture of a rendered page, and it avoids a ~150 MB browser dependency.
- **Docker** (D-009), **liveness/anti-spoof**, **face blurring**, **EAS attestation**.

---

## Changelog

| Date | Entry |
|---|---|
| 2026-09-05 | Corrected a false README claim (reverse image search was never implemented) and made the ladder genuinely multi-rung across Mastodon instances (D-015, F-13). Fixed PLAN/README doc-vs-code mismatches. Recorded the rare teardown flake (F-14). |
| 2026-09-05 | Verification pass (F-12). Fresh-clone dry run passed. Six defects found and fixed, the most serious being `verify` claiming on-chain confirmation when no chain had been consulted. Tamper detection confirmed on three vectors. |
| 2026-09-05 | Pipeline complete. Search stage, evidence bundle and CLI; verified end to end against live Mastodon data and a local chain. Threshold calibrated on real photos (F-9). README written. |
| 2026-09-05 | Evidence core, Stage 1 (face) and Stage 3 (chain) built and tested. Toolchain collapsed to pure Python (D-014). |
| 2026-09-05 | Analysis phase. Fact-checked IDEAS.md — Bing retired, both suggested RPCs dead, SerpAPI has no upload endpoint. Found Mastodon as a zero-key search path. Repo initialised with Task 1/2 excluded. |
