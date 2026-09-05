# CONTEXT — pick this project up cold

> **You are reading the single entry point.** If you are a fresh Claude session (or a
> new person) with no memory of this project, read this file top to bottom first, then
> [PROGRESS.md](PROGRESS.md) for live status and [PLAN.md](PLAN.md) for the build order.
>
> Doc map: **CONTEXT.md** (this — the task, constraints, environment) ·
> [PLAN.md](PLAN.md) (architecture & build order) ·
> [PROGRESS.md](PROGRESS.md) (what is done, what is next, what is blocked) ·
> [docs/DECISIONS.md](docs/DECISIONS.md) (why things are the way they are) ·
> [docs/FINDINGS.md](docs/FINDINGS.md) (measured evidence — do not re-run these spikes)

**Last updated:** 2026-09-05 · **Status:** analysis complete, implementation NOT started

---

## 1. The task

HH Goa 2026 Shortlisting **Task 3: Face Identification & Blockchain Verification**.

Build a pipeline that takes a face scan as input, identifies matching content on the
web/social media, then verifies that discovered data using a blockchain — end to end.

```
Face scan input  →  Web/social media search (find matching post)  →  Blockchain upload/verification
```

### The five technical requirements, verbatim in intent

| # | Requirement | What it actually demands |
|---|---|---|
| 1 | **Face identification** | Detect and encode a face from an input image. Any library or API is acceptable. |
| 2 | **Social media / web search** | Use the face to find **at least one real, matching social media post**. Via reverse image search, an API, **or a scripted search approach**. Explicitly: *"a genuine search step, not a hardcoded/pre-picked result."* |
| 3 | **Blockchain verification** | Upload the post (or a hash/fingerprint of it — image, text, or metadata) to a blockchain to create a verifiable, tamper-evident record. **Any chain may be used** — public testnet, mainnet, or a local/simulated chain — as long as you can **demonstrate re-verifying the data against the on-chain record**. |
| 4 | **No website required** | Do not build or host a project website. Spend the time on the pipeline. |
| 5 | **GitHub repo required** | Full source in a repo, with a README covering: *what it does · how to run it · which blockchain · known limitations*. |

### Submission

- **Repo:** https://github.com/Sai03SkAr/HHGoa-Task-3 (public, currently empty)
- **Screen recording** of the pipeline working end to end. Plain capture, no editing needed. Upload anywhere (YouTube unlisted / Drive / Loom) and share a working link.
- **Form:** https://forms.gle/oZbQGuwiNeHVcHWo8
- **Deadline: Sept 7, 2026, 11:59 PM.** Task launched Aug 31, 2026.
- **No resubmissions.** Submit only when the build is final.

> **Time check:** as of this writing it is **Sept 5, 2026** — roughly **2.5 days** remain.
> This is the single most important constraint on scope. See [PLAN.md](PLAN.md) tiers.

---

## 2. Source material

Two inputs were provided and both have been read in full:

- `task #3.pdf` — the official task brief. Content is transcribed in §1 above; the PDF
  itself is gitignored (`*.pdf`) since it is not ours to redistribute.
- `IDEAS.md` — a **build-notes / idea list**, not a spec. Strong architectural ideas,
  but several concrete claims in it are **factually stale** — see §5. Treat it as a
  design brief to be verified, not instructions to follow literally.

### Reference-only folders — NEVER commit these

`HHGoa Task1 /` and `HHGoa Task2/` sit inside this directory for convenience. They are
the previous submissions and are **explicitly excluded** by the user.

Both are in `.gitignore` and verified ignored via `git check-ignore`. **Do not `git add -f`
them, do not move them into the repo, do not reference their contents in the deliverable.**
Task 2 is worth reading only as a *style* reference for handoff docs — its
`CONTEXT.md` / `progress.md` pattern is what this doc set imitates.

---

## 3. The core design idea

The naive submission is a linear pipe where every step blindly trusts the last:

```
face → reverse image search → take first URL → hash it → send to chain
```

Nothing in that verifies anything. The URL is trusted because Google returned it.

Instead this project is a **closed verification loop** — the face model is not just an
encoder at the start, it is the **adjudicator** of the search stage:

```
                    ┌──────────────────────────────┐
  probe image ─────►│ 1. detect / quality / embed  │──── probe_emb ──┐
                    └──────────────────────────────┘                 │
                                   │                                 │
                                   ▼                                 │
                    ┌──────────────────────────────┐                 │
                    │ 2. search providers (ladder) │                 │
                    └──────────────────────────────┘                 │
                                   │ candidate posts + images        │
                                   ▼                                 │
                    ┌──────────────────────────────┐                 │
                    │ 3. scrape + screenshot       │                 │
                    │    RE-EMBED candidate faces  │◄────────────────┘
                    │    cosine ≥ threshold ?      │
                    └──────────────────────────────┘
                                   │ verified match + evidence
                                   ▼
                    ┌──────────────────────────────┐
                    │ 4. canonicalize → Merkle root│
                    │    → anchor tx on-chain      │
                    └──────────────────────────────┘
                                   │
                                   ▼
                          verify --tx 0x…  →  PASS / FAIL
```

**Why this matters for grading.** Requirement 2 demands "a genuine search step, not a
hardcoded/pre-picked result." A closed loop answers that with cryptographic receipts
rather than with our word for it: the search returns *candidates*, and our own detector
+ embedder decides which (if any) is a real match, recording the score either way.

We anchor the **whole evidence bundle** — probe hash, candidate image hash, page HTML
hash, screenshot hash, similarity score, raw search queries and responses, timestamps —
not just a URL.

---

## 4. Environment (verified on this machine, 2026-09-05)

| Tool | State | Note |
|---|---|---|
| macOS | 26.6, **arm64** (Apple Silicon) | |
| Python | 3.14.4 is default — **too new** | Use **3.12.12** (`/opt/homebrew/bin/python3.12`); `uv` can also fetch it |
| `uv` | 0.11.8 ✅ | Use for all venv/dependency work |
| Node | 22.20.0, npm 11.8.0 ✅ | Hardhat path is viable |
| git | 2.50.1 ✅ | |
| **`gh` CLI** | ❌ **not installed** | Repo already created via browser, so not strictly needed |
| **Foundry** (`anvil`/`forge`/`cast`) | ❌ **not installed** | Local-chain plan uses **Hardhat** instead — see [docs/DECISIONS.md](docs/DECISIONS.md) D-005 |
| **Docker** | ❌ not installed | `docker-compose.yml` from IDEAS.md is dropped; it was "nice to have" only |
| **IPFS (kubo)** | ❌ not installed | Would need a pinning service (Pinata) — deferred, see D-006 |
| Disk free | ~41 GB | Enough; `buffalo_l` is ~281 MB |

### Git layout — read this before touching git

`/Users/saisalelkar` (the **home directory**) is itself a git repo pointed at
`iOS-conversion.git`. That is unrelated to this project and must not be committed to.

A **separate, nested repo** has been initialised at
`/Users/saisalelkar/Desktop/HHGoa Task3` on branch `main`, remote `origin` =
`https://github.com/Sai03SkAr/HHGoa-Task-3.git`. Always confirm you are in the right
one before any git command:

```bash
git rev-parse --show-toplevel   # must print /Users/saisalelkar/Desktop/HHGoa Task3
```

**Nothing has been pushed yet.**

---

## 5. Corrections to IDEAS.md — verified, do not undo these

`IDEAS.md` is a good design brief but contains stale facts. Each was checked directly:

| IDEAS.md says | Reality (verified 2026-09-05) |
|---|---|
| Ladder rung 2 = **Bing Visual Search API** | ❌ **Dead.** All Bing Search APIs were retired **Aug 11, 2025**; endpoint returns 404. Cannot be a fallback. |
| SerpAPI Google Lens as primary | ⚠️ Alive (100 free searches/month) but takes **`url` or `image_id` only — there is no file-upload endpoint.** Reverse-searching a webcam probe therefore requires **publishing the probe face to a public URL first**, which contradicts the project's own "no raw biometrics leave the machine" stance. Real design tension — see D-003. |
| Yandex reverse image as rung 3 | ⚠️ No official API. HTML scraping only, aggressive anti-bot. Unreliable for a live demo. |
| `rpc.sepolia.org` | ❌ 404. Use `ethereum-sepolia-rpc.publicnode.com` (verified `0xaa36a7`). |
| `rpc-amoy.polygon.technology` | ❌ Times out. Use `polygon-amoy-bor-rpc.publicnode.com` (verified `0x13882`). |
| Anvil/Foundry as the local chain | ⚠️ Not installed here. Hardhat (npm) is the lower-friction path. |
| Deadline "Sept 7, 2026" | ✅ Confirmed against the PDF. |

**The consequence:** the search ladder from IDEAS.md cannot be built as written. The
replacement is in [PLAN.md](PLAN.md) §2 and rests on a verified, zero-key, genuinely
social-media source. This is the single largest deviation from the brief and it is
deliberate.

---

## 6. What has been measured (short version)

Full detail with commands in [docs/FINDINGS.md](docs/FINDINGS.md). Headlines:

- **InsightFace `buffalo_l` installs and runs clean** on Python 3.12 / arm64 CPU.
  One-time model download ~281 MB; **warm load 0.4 s**; detect+embed **~0.11 s**.
- **The cosine threshold story holds with enormous margin.** Same person through a
  simulated web round-trip (3× downscale + JPEG q45, crop, brightness): **0.975–0.991**.
  Two different people: **−0.044**. A 0.45 threshold is very conservative — good.
- **Mastodon's public API is a genuine, zero-auth social media search.** Returns live
  posts (verified: posts timestamped the same day), real authors, real permalink URLs,
  and directly downloadable image attachments. No key, no quota, no anti-bot.
- **Bluesky's public endpoint returns 403** from this machine — usable only as a
  keyed fallback, not a primary.
- Testnet RPCs reachable: **Sepolia**, **Polygon Amoy**, **Base Sepolia**.
- `web3.py` installs at **8.0.0** — a major version whose API differs from the 6.x used
  in most tutorials and blog posts. Do not copy 6.x snippets.

---

## 7. Open questions for the user — these block work

Tracked with full context in [PROGRESS.md](PROGRESS.md) §Blockers. Summary:

1. **Which chain for the recorded demo** — local Hardhat only (zero friction, no faucet)
   vs. a public testnet (needs a funded burner wallet; stronger demo with a live
   explorer link). Recommendation: **do both**, local as default + testnet for the tape.
2. **Testnet funds** — if a testnet is used, someone must fund a burner address from a
   faucet. This is a human action and can be slow; start early.
3. **The demo subject** — the pipeline can only find a match if the probe face actually
   appears in a public post. See [PLAN.md](PLAN.md) §2.3; recommendation is for the user
   to post their own photo publicly, which also settles consent cleanly.
4. **Whether to buy/obtain a SerpAPI key** — optional; the pipeline is designed to work
   fully without one.

---

## 8. Ground rules for whoever continues this

- **Keep these docs current.** They exist so this project survives a context limit or an
  account switch. Update [PROGRESS.md](PROGRESS.md) whenever something lands or breaks;
  append to [docs/DECISIONS.md](docs/DECISIONS.md) whenever a choice is made.
- **Distinguish measured from assumed.** [docs/FINDINGS.md](docs/FINDINGS.md) is only for
  things actually run and observed, with the command included. Never promote a guess into
  it.
- **Never commit `HHGoa Task1 /` or `HHGoa Task2/`.** Explicit user instruction.
- **No secrets in git.** `.env` is ignored; `.env.example` is the committed template.
- **Scope discipline.** The deadline is hard and there are no resubmissions. Get the
  Must-have tier working *and recorded* before starting anything else.
