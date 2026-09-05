# PROGRESS — live status

> **The one file to read to know where things stand.** Update it whenever something
> lands, breaks, or unblocks. Start at [CONTEXT.md](CONTEXT.md) if you are cold.
>
> **Last updated:** 2026-09-05 · **Phase: pipeline complete and verified end to end.**
> All five technical requirements are met on the local-chain path.

---

## Where to pick up

**The pipeline works.** Face → search → adjudicate → anchor → verify, with the tamper test
going red and `verify --tx` reconstructing from a bare transaction hash. Both the match
and no-match paths are verified against live data (F-10, F-11).

**Next actions, in order:**

1. **B-1 — the demo subject.** The only blocker on a *personal* demo. See
   [docs/USER_ACTIONS.md](docs/USER_ACTIONS.md) A-1. Until then the pipeline demonstrates
   correctly against any public account.
2. **B-2 — testnet funding**, if a live explorer link is wanted. Optional: the local chain
   is fully compliant.
3. **Rehearse and record** — shot list in [PLAN.md](PLAN.md) §7. `make prewarm` first.
4. **Fresh-clone dry run** — the submission checklist demands it and there are no
   resubmissions.

**144 tests pass** (135 fast + 9 model-loading). `make test-fast` skips the model.

A full verification pass — fresh clone from GitHub, every CLI path, every error path, and
adversarial tamper cases — is recorded in [docs/FINDINGS.md](docs/FINDINGS.md) **F-12**.
It found and fixed six real defects, the most serious being that `verify` claimed a root
matched the on-chain anchor in cases where no chain had been consulted.

---

## Status by requirement

| # | Requirement | Status | Notes |
|---|---|---|---|
| 1 | Face identification | ✅ **done** | `src/face/encoder.py` — detect, multi-face policy, quality gate with reasons, 512-d embed. 9 tests |
| 2 | Social media / web search | ✅ **done** | `src/search/` — provider ladder, Mastodon (zero-key), hashed search trail, and the closed loop where our encoder adjudicates. Verified live on both match and no-match (F-10, F-11) |
| 3 | Blockchain verification | ✅ **done** | `contracts/EvidenceRegistry.sol` + `src/chain/registry.py` — compile, deploy, anchor, verify, recover-from-tx. 15 tests, all in-process |
| 4 | No website | ✅ n/a | Explicitly not required |
| 5 | GitHub repo + README | ✅ **done** | README covers all four required sections: what it does · how to run it · which blockchain · known limitations |
| — | Evidence core | ✅ **done** | `src/evidence/` — canonical JSON + Merkle with domain separation. 40 tests |
| — | Screen recording | ⬜ not started | Shot list ready in [PLAN.md](PLAN.md) §7 |

---

## Done so far

- **Read both source documents in full** — `task #3.pdf` (transcribed into
  [CONTEXT.md](CONTEXT.md) §1) and `IDEAS.md`.
- **Fact-checked IDEAS.md against reality.** Several load-bearing claims are stale; the
  corrections are in [CONTEXT.md](CONTEXT.md) §5 and drove the Stage 2 redesign.
- **Validated the face stack end to end** — installed, ran, and measured InsightFace
  `buffalo_l` on real portraits, including the cosine-threshold behaviour the whole
  design rests on (F-1, F-2).
- **Found and verified a zero-key social media search** (Mastodon, F-3) after
  establishing that Bing is retired, Yandex has no API, SerpAPI cannot take an upload,
  and Bluesky 403s (F-4).
- **Verified chain endpoints** — both RPC URLs suggested by IDEAS.md are dead; three
  working alternatives confirmed (F-5).
- **Verified the Python stack installs** on 3.12, including `web3` (F-6).
- **Set up the repo** — nested git repo at `Desktop/HHGoa Task3`, branch `main`, remote
  `Sai03SkAr/HHGoa-Task-3`, with `HHGoa Task1 /` and `HHGoa Task2/` **verified excluded**
  via `git check-ignore`, plus `.env` and `*.pdf`.
- **Wrote this doc set** — CONTEXT / PLAN / PROGRESS / DECISIONS / FINDINGS / USER_ACTIONS.
- **Built the evidence core** — canonical JSON (fixed-precision floats, sorted keys,
  round-trip stable across processes) and a Merkle tree with leaf/node domain separation
  and promote-not-duplicate odd levels. 40 tests.
- **Built Stage 1** — detection, an explicit multi-face policy, a quality gate that
  reports its measurements, and 512-d embeddings.
- **Built Stage 3** — `EvidenceRegistry.sol`, plus compile/deploy/anchor/verify and
  recovery of an anchor from a bare tx hash. Runs in-process on `eth-tester`.
- **Collapsed the toolchain to pure Python** (D-014) — `py-solc-x` compiles Solidity, so
  no Node is needed to build or test.

---

## Blockers — these need the user

### B-1 · Demo subject — *blocks only a personal demo* 🟡

The pipeline can only find a match **of you specifically** if your face appears in a public
post. It is otherwise fully working — verified against a public account in F-11, where it
correctly matched the account owner at 0.76 and rejected a different person in the same
account's photos at 0.07.

**Recommendation:** the user posts their own photo publicly (Mastodon works and needs no
key), then probes with a live webcam capture. One move gives a real social media post, a
live search, an undeniably non-hardcoded match, and clean consent.

Alternatives: a consenting teammate with an existing public photo, or a public figure
(guaranteed to resolve, weaker consent story). See [PLAN.md](PLAN.md) §2.3.

### B-2 · Testnet funding — *long lead time, start early* 🔴

If the recorded demo uses a public testnet, a burner wallet must be funded from a faucet.
Faucets are slow and often gated (mainnet balance or social auth).

**Recommendation:** Polygon Amoy — the least painful faucet of the three verified
networks. A local Hardhat chain remains the default so **development is never blocked on
this**; only the on-camera explorer link is.

### B-3 · Which chain for the recording 🟡

Local Hardhat (zero friction) vs public testnet (live explorer link, stronger on camera).
Requirement 3 accepts either. **Recommendation: both** — local as default, testnet for
the tape. See [docs/DECISIONS.md](docs/DECISIONS.md) D-013.

### B-4 · SerpAPI key — optional 🟢

Only needed for the reverse-image-search rung, which is **off by default** for privacy
reasons (D-003). The pipeline is designed to work fully without it. Free tier is 100
searches/month. Skip unless a second visible rung on the ladder is wanted for the demo.

---

## Known risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Threshold not calibrated for the real regime.** Measured separation covers same-image-re-encoded vs different-person; the demo runs in the *same person, different photo* regime (~0.5–0.7 typical) | **high** | Re-validate with real webcam probes before locking 0.45; record the achieved score every run; state honestly in Known Limitations (D-011) |
| **Canonicalization not reproducing** — the classic way a re-verification demo dies on stage | **high** | Build evidence/Merkle **before** the search stage (D-008); test byte-stability across processes; fix float formatting before hashing |
| Demo subject not findable → pipeline looks broken | **high** | B-1; and the quality gate should fail *with a printed reason* so a no-match still reads as engineered |
| Live API flaking mid-recording | medium | Disk cache keyed by query hash; visible fall-through ladder |
| First-run 281 MB model download during the recording | medium | Pre-warm the cache; warn in the README |
| `web3` 8.0.0 API differs from every 6.x tutorial | medium | Check v8 docs; do not paste old snippets (F-6) |
| Faucet gating blocks the testnet link | medium | Local chain default; start funding early (B-2) |
| ~2.5 days, no resubmissions | **high** | Strict tiering — Tier 1 working *and recorded* before anything else (PLAN §0) |

---

## Not yet verified — open technical unknowns

- `playwright install chromium` (browser binary download) has not been run.
- No chain round-trip yet: no contract compiled, deployed, or anchored — not even locally.
- Hardhat itself is not installed (`npm install` not run).
- Webcam capture path on macOS (permissions) untested.
- Mastodon search has been verified to *return posts*; it has **not** been verified to
  find a *specific known person* — that depends on B-1.

---

## Changelog

| Date | Entry |
|---|---|
| 2026-09-05 | Verification pass (F-12). Fresh-clone dry run passed. Six defects found and fixed: verify falsely claiming on-chain confirmation when no chain was reached; insightface stdout noise; raw traceback on a missing probe; empty run dirs left by failed runs; unhelpful error on a cross-network contract address; `make demo` reporting a no-match as a build failure. Tamper detection confirmed on three independent vectors including a self-consistent forgery. 144 tests. |
| 2026-09-05 | Pipeline complete. Search stage, evidence bundle and CLI built; verified end to end against live Mastodon data and a local chain — match, no-match, verify-from-tx, and the tamper cycle (PASS → FAIL → PASS). Threshold calibrated on real photos (F-9). README written. 138 tests. |
| 2026-09-05 | Implementation began. Evidence core (canonical + Merkle), Stage 1 (face), Stage 3 (chain + contract) all built and tested — 68 tests green. Toolchain collapsed to pure Python (D-014, supersedes D-005). Two real bugs caught by tests: numpy scalars leaking into evidence (would have failed at hash time) and a multi-face policy comparing areas where it meant widths. First commit. |
| 2026-09-05 | Analysis phase. Read task + IDEAS.md; fact-checked IDEAS.md (Bing retired, both RPCs dead, SerpAPI upload limitation); validated InsightFace + cosine thresholds; found Mastodon as a zero-key search path; initialised repo with Task 1/2 excluded; wrote the doc set. No implementation. |
