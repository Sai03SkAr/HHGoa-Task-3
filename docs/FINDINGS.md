# FINDINGS — measured evidence

> **Rule for this file: nothing goes in here that was not actually run and observed.**
> Every entry carries the command and the real output, so nobody re-does the work and
> nobody mistakes a guess for a result. Assumptions belong in
> [../PLAN.md](../PLAN.md); decisions belong in [DECISIONS.md](DECISIONS.md).

All measured **2026-09-05** on macOS 26.6, arm64, unless noted.

---

## F-1 — InsightFace `buffalo_l` installs and runs on Python 3.12 / arm64 ✅

Installed with `uv pip install insightface onnxruntime opencv-python-headless numpy`
into a 3.12 venv. Resolved clean, **no compiler toolchain needed**.

Notable resolved versions: `onnxruntime 1.29.0`, `onnx 1.22.0`, `numpy 2.5.2`,
`opencv-python 5.0.0.93`, `scikit-image 0.26.0`.

| Measurement | Value |
|---|---|
| One-time model download (`buffalo_l.zip`) | **281 MB**, ~165 s on this connection |
| **Warm** model load (`FaceAnalysis.prepare`) | **0.4 s** |
| Detect + embed, 3356×2687 image | **~0.11 s** |
| Embedding | 512-d, L2-normalised (`normed_embedding`) |

Model cache lands in `~/.insightface/models/buffalo_l`. The first run of a fresh clone
pays the 281 MB download — **warn about this in the README**, and do not let it happen
for the first time during the recording.

### Gotcha

`insightface/utils/face_align.py` emits a `FutureWarning` against scikit-image 0.26
(`estimate` is deprecated). Harmless today, but it will clutter demo output — suppress
the warning or pin scikit-image.

---

## F-2 — The cosine threshold holds with an enormous margin ✅

The single most load-bearing assumption in the design. Two real portraits
(different people), plus derived variants of one simulating a web round-trip.

```
=== identity A (Obama official portrait, 3356x2687) ===
  A original             faces=1 det=0.903 face_px=630 blur=  120.5
  A jpeg45_3xdown        faces=1 det=0.901 face_px=210 blur=  285.7
  A cropped              faces=1 det=0.819 face_px=629 blur=  152.6
  A brightened           faces=1 det=0.904 face_px=628 blur=  118.7

=== identity B (Biden official portrait, 3000x2400) ===
  B original             faces=1 det=0.829 face_px=703 blur=  245.4

=== cosine similarity ===
  SAME person, web round-trip (expect HIGH):
    A vs A/jpeg45_3xdown    = +0.9749
    A vs A/cropped          = +0.9753
    A vs A/brightened       = +0.9909
  DIFFERENT people (expect LOW):
    A vs B                  = -0.0438
```

**Reading:** aggressive recompression (3× downscale, JPEG q45), cropping and a brightness
shift barely move the embedding — 0.975+ throughout — while two different people sit at
essentially zero. A **0.45 threshold is very conservative**, which is the right
direction to err.

### The gap this does NOT close — do not overclaim

This covers *same image re-encoded* vs *different person*. It does **not** measure the
genuinely hard regime: **same person, different photo, different lighting/pose/age**,
which for ArcFace typically lands ~0.5–0.7. Validate that with real webcam probes before
fixing the threshold, and state the limitation honestly in the README.

Also worth noting: the blur (Laplacian variance) numbers do **not** order the way naive
intuition suggests — the downscaled+recompressed variant scored *higher* (285.7) than the
original (120.5), because downscaling sharpens edges per-pixel. So a blur gate must be
applied to the **native-resolution probe**, not to a resized copy, or it will pass
exactly the images it should reject.

---

## F-3 — Mastodon's public API is a genuine zero-auth social media search ✅

```bash
curl -s -H "User-Agent: HHGoaSpike/0.1" \
  "https://mastodon.social/api/v1/timelines/tag/portrait?limit=3&only_media=true"
```

Returned live posts — timestamped **the same day the probe was run** — each with:

```
post : https://pixelfed.social/p/neotux/1001746808799439975
  by  : neotux@pixelfed.social | 2026-09-05T07:04:10.000Z
  media: image https://files.mastodon.social/cache/media_attachments/files/117/...
```

**No API key. No quota. No anti-bot.** Real permalinks, real authors, real timestamps,
directly downloadable image attachments — and the federation means results span many
instances (pixelfed, chaos.social) rather than one silo.

This is what makes the whole Stage 2 replacement viable, and it is un-fakeable on camera:
the candidate set changes minute to minute, so it visibly cannot be hardcoded.

---

## F-4 — Search provider landscape ⚠️

| Provider | State | Evidence |
|---|---|---|
| **Bing Visual Search** | ❌ **retired Aug 11, 2025** | Endpoint 404s. Microsoft retired *all* Bing Search APIs; migration path is "Grounding with Bing Search" inside Azure AI Agents, which is not a reverse-image API. |
| **SerpAPI Google Lens** | ⚠️ alive, keyed | `https://serpapi.com/search` → 401 (alive, wants a key). Free tier **100 searches/month**; paid from **$75/mo**. |
| SerpAPI image input | ⚠️ **no upload endpoint** | Takes `url` or `image_id` only. SerpApi's own guide routes local files through **S3 to obtain a public URL**. Reverse-searching a webcam probe therefore **requires publishing the probe face publicly** — the core privacy conflict driving [DECISIONS.md](DECISIONS.md) D-003. |
| **Yandex** | ⚠️ scraping only | `yandex.com/images` → 200 HTML. No official API; aggressive anti-bot. Unreliable for a live demo. |
| **Bluesky** public API | ❌ 403 from here | `public.api.bsky.app/xrpc/app.bsky.feed.searchPosts` → 403 with and without a custom UA. Keyed fallback only. |
| **TinEye** | ❌ ~$200/mo | Out of budget. |
| **Mastodon** | ✅ **works, free** | See F-3. |

---

## F-5 — Chain endpoints ✅

`eth_chainId` over JSON-RPC POST:

| Endpoint | Result |
|---|---|
| `https://ethereum-sepolia-rpc.publicnode.com` | ✅ `0xaa36a7` (11155111) |
| `https://polygon-amoy-bor-rpc.publicnode.com` | ✅ `0x13882` (80002) |
| `https://sepolia.base.org` | ✅ `0x14a34` (84532) |
| `https://rpc.sepolia.org` | ❌ **404** — the endpoint named in IDEAS.md is dead |
| `https://rpc-amoy.polygon.technology` | ❌ **timeout** — also named in IDEAS.md, also unusable |

Both RPC URLs suggested by IDEAS.md fail. Use the publicnode ones.

---

## F-6 — Python stack ✅

`uv pip install web3 eth-account playwright beautifulsoup4 httpx typer rich` resolved
clean on 3.12.

| Package | Version | Note |
|---|---|---|
| `web3` | **8.0.0** | ⚠️ **Major version.** The API differs from the 6.x used in nearly every tutorial and blog post. Do not paste 6.x snippets — check the v8 docs. |
| `httpx` | 0.28.1 | |
| `beautifulsoup4` | 4.15.0 | |

**Not yet verified:** `playwright install chromium` (the browser binary download) has not
been run, and no chain round-trip has been executed against a local node. Both are open —
see [../PROGRESS.md](../PROGRESS.md).

---

## F-7 — Environment / tooling gaps ✅

| Tool | State |
|---|---|
| Python 3.14.4 default; **3.12.12 available** | Use 3.12 — 3.14 is too new for this ML stack |
| `uv` 0.11.8, Node 22.20.0, npm 11.8.0, git 2.50.1 | ✅ present |
| `gh` CLI | ❌ absent (repo was created in the browser, so not needed) |
| Foundry (`anvil`/`forge`/`cast`) | ❌ absent → Hardhat instead |
| Docker, IPFS (kubo) | ❌ absent |
| Disk free | ~41 GB |

### Wikimedia fetch gotcha (cost real time)

`upload.wikimedia.org` now **rejects arbitrary thumbnail widths** — a `480px-` or
`640px-` thumb URL returns **HTTP 400** with `Use thumbnail sizes listed on
https://w.wiki/GHai`, and the body is HTML, so a naive `curl -o file.jpg` silently writes
an HTML file with a `.jpg` name. Fetch the **original** path
(`/wikipedia/commons/<a>/<ab>/<Name>.jpg`) instead.

General lesson for the scraper: **always sniff the downloaded bytes** (magic number /
`file`) rather than trusting the extension or the HTTP status alone.

---

## F-8 — The whole chain stage runs in pure Python ✅

`py-solc-x` fetched **solc 0.8.24** and compiled `EvidenceRegistry.sol`; `web3` +
`eth-tester` then deployed and exercised it entirely **in-process** — no node, no faucet,
no network:

```
compiled OK, abi entries: 6 | bytecode 3290 bytes
connected: True
deployed at: 0xF2E2…395b   gas: 757035
anchored                   gas:  93815   block: 2
verify(root)          -> True
verify(unknown root)  -> False
Anchored event root matches: True
```

**Consequence:** no Node toolchain is needed to build or test this project — see
[DECISIONS.md](DECISIONS.md) D-014. Gas numbers above feed the cost table.

**The one limitation:** `eth-tester` state dies with the process, so it cannot back a
demo where `run` and `verify` are separate commands. Hardhat **3.15.0** is installed to
supply a persistent local node (`npx hardhat node` on `127.0.0.1:8545`) for that case.

**Foundry does not install here.** `foundryup` places its own launcher but then fetches
no binaries; `anvil` never appears. Abandoned — `eth-tester` covers tests and Hardhat
covers persistence.

---

## F-9 — Threshold calibrated on real social media photos ✅ *(closes the F-2 gap)*

F-2 measured *same image re-encoded* vs *different person* and explicitly flagged the
untested regime: **same person, different photo**, which is what the demo actually runs
in. That gap is now closed with live data.

Method: pulled every public post from one Mastodon account, embedded every face found,
and split the pairwise similarities into *same post* (near-duplicates) and **cross post**
(genuinely different photos — different day, lighting, pose, framing).

```
95 faces across 37 distinct posts

SAME post : n=  82  min=-0.070  p10=+0.561  median=+0.779  p90=+0.905  max=+0.974
CROSS post: n=4383  min=-0.120  p10=+0.152  median=+0.698  p90=+0.775  max=+0.879

cross-post pairs >= 0.30 : 3846/4383 = 87.7%
cross-post pairs >= 0.40 : 3842/4383 = 87.7%
cross-post pairs >= 0.45 : 3834/4383 = 87.5%
cross-post pairs >= 0.50 : 3797/4383 = 86.6%
cross-post pairs >= 0.60 : 3606/4383 = 82.3%
```

**Same person, different photo has a median of 0.698** — comfortably above the 0.45 bar,
and far above the −0.044 measured for two different people (F-2).

**The threshold sits in an empty valley, which is the real result.** Moving it from 0.30
to 0.50 changes the outcome for only **1.1%** of pairs (3846 → 3797). The distribution is
bimodal — one mode high (the account owner, ~0.6–0.88) and one low (other people who
appear in their photos, ~0.15) — with very little mass in between. A threshold anywhere
in 0.30–0.50 behaves almost identically, which means 0.45 is **not a knife edge**: small
misjudgements in choosing it do not flip results.

That is the honest justification for the number, and it is stronger than quoting a
canonical ArcFace figure. [DECISIONS.md](DECISIONS.md) D-011 is upgraded from provisional
to firm on this evidence.

**Caveats worth stating in the README rather than hiding.** One account, one apparent
ethnicity, favourable lighting; this is calibration, not a benchmark. The ~12% of
cross-post pairs below the bar are mostly *other people* in that account's photos, which
is the correct outcome, but they were not hand-labelled — so treat 87.5% as a rough
recall figure, not a measured one.

---

## F-10 — The closed loop runs end to end against live data ✅

Searched Mastodon for `#portrait`, downloaded every image from the returned posts,
re-embedded each with the same encoder that read the probe, and scored them:

```
search: mastodon returned 6 candidates
  skip   …/117/217/24…  (NoFaceFound)
         cosine=0.1113  …
         cosine=0.1057  …
  skip   …/117/217/12…  (NoFaceFound)
         cosine=-0.0397 …

NO MATCH  best cosine=0.1113 < 0.45 (4/8 candidate images comparable)
```

The probe was a portrait of someone who is **not** in those posts, and the pipeline says
so — with the full score table, and with a recorded reason for each of the four images
that yielded no face. A system that can only ever report success proves nothing; this one
is falsifiable, and that is the property requirement 2 is really asking about.

---

## F-11 — The positive path works, and discriminates ✅

Everything up to here proved the pipeline could correctly report **no match**. This
proves it finds a real one, and — more importantly — that it tells people apart.

Probe: a face taken from one public post. Query: that account's other public posts.

```
0.9995  irene@troet.cafe  (the probe's own source photo)
0.7632  irene@troet.cafe  https://troet.cafe/@irene/117163894713098683
0.7607  irene@troet.cafe  https://troet.cafe/@irene/117065046214505725
0.7603  irene@troet.cafe  https://troet.cafe/@irene/117163894713098683
0.0668  irene@troet.cafe  (a DIFFERENT person appearing in the same account's photos)
     -                    no face detected in image  (x2)

MATCH  cosine=0.9995 >= 0.45  (10/12 candidate images comparable)
```

**The 0.0668 row is the result that matters.** Another person appears in the same
account's own photos and is correctly rejected. A pipeline that simply returned whatever
the search gave back would have accepted them. The face model is doing real work, which
is precisely what requirement 2 is testing.

The 0.76 cluster is *same person, different photo* — the hard regime — sitting far above
the 0.45 bar and consistent with the median of 0.698 measured independently in F-9.

`verify --run` then passed on this bundle: root reproduced, all 16 Merkle proofs verified,
probe image and page HTML hashes re-checked against the files on disk.

### Runtime

**16.4 s** end to end for 3 posts / 12 candidate images, including model load, search,
12 downloads, 12 embeds, page scrape, Merkle build and the anchoring transaction.

A run at `--limit 12` did **not** finish in 7 minutes: cost is dominated by downloading
full-resolution originals, which vary enormously in size. `--limit` and `--max-images`
are therefore the demo's runtime levers, and the defaults (10 and 3) are set for a
recording rather than for exhaustiveness. **Do not raise them mid-demo.**

---

## F-12 — Full verification pass (fresh clone + adversarial cases) ✅

A deliberate audit rather than a happy-path demo. Everything below was run, and each
problem found was fixed.

### Fresh clone from GitHub

`git clone` into an empty directory → `make setup` → `make test-fast` → **129 passed**,
then `make test` → **138 passed** in 14.4 s including the model download. The public repo
contains no `HHGoa Task1 /`, no `HHGoa Task2/`, no `.env`, no `runs/`, no `.cache/`.

### Six real defects found and fixed

| # | Defect | Why it mattered |
|---|---|---|
| 1 | **`verify` claimed "root matches the on-chain anchor" when no chain was consulted.** On the `memory` chain — which dies with the process — it compared the bundle against the root the bundle records *about itself*. | The most dangerous bug in the audit. Circular: anyone editing the evidence would edit that field too. Now reported as a distinct **`????` UNVERIFIED`** state with an **INCOMPLETE** verdict, never a green PASS. |
| 2 | **InsightFace printed ~11 lines of model-loading noise to stdout on every run.** It uses `print()`, so no log level silences it. | Buried the pipeline's own output and would have cluttered the entire screen recording. Now captured and re-emitted at debug level. |
| 3 | **A missing probe file raised a raw `FileNotFoundError` traceback.** | Every other probe problem reported cleanly; this one dumped a stack trace. Now `ProbeUnreadable`, which subclasses both `FaceError` and `OSError`. |
| 4 | **Every failed run left an empty `runs/<id>/` directory behind.** | Junk accumulation for anyone experimenting. The directory is now created only once the probe passes. |
| 5 | **A `CONTRACT_ADDRESS` from the wrong network produced `BadFunctionCallOutput`.** | Says nothing about the actual mistake. Now a code check at the address with an actionable message. `memory` also ignores any configured address, since its chain is fresh each process. |
| 6 | **`make demo` reported `Error 1` on a legitimate no-match run.** | The pipeline had worked perfectly; it just found no match. Exit codes are now documented (0/1/2/3) and the Makefile distinguishes a negative result from a failure. |

### Tamper detection — three independent mechanisms

| Attack | Caught by | Result |
|---|---|---|
| Edit one field in `evidence.json` | recomputed Merkle root | FAIL, exit 1 |
| Edit `probe.jpg`, leave the JSON alone | recorded artefact hash | FAIL, exit 1 |
| **Edit the evidence *and* the recorded root so the bundle is internally consistent** | **the chain** — that root was never anchored | **FAIL, exit 1** |

The third is the one that matters. A self-consistent forgery defeats every local check;
only the on-chain record catches it. That is precisely what requirement 3 is asking for,
and it is now demonstrated rather than asserted.

Restoring the originals returns all three to PASS, exit 0.

---

## F-13 — The provider ladder falls through visibly ✅

The README had claimed reverse image search was "supported but off by default". It was
**not implemented at all** — see [DECISIONS.md](DECISIONS.md) D-015 for the correction and
why it was not built. The ladder now spans several Mastodon instances, which have
genuinely different federated views, so a second rung is a different *source* rather than
a retry.

Verified by pointing the first rung at a host that does not resolve:

```
  ladder        mastodon:this-instance-does-not-exist-xyz.invalid -> mastodon:mstdn.social
search: mastodon:this-instance-does-not-exist-xyz.invalid failed
        ([Errno 8] nodename nor servname provided, or not known), falling through
search: mastodon:mstdn.social returned 2 candidates
  fell through  mastodon:this-instance-does-not-exist-xyz.invalid: error: [Errno 8] ...
  2 candidate posts via mastodon:mstdn.social
```

The run continues and the fall-through is printed rather than hidden — which is the point:
a live demo dies when one endpoint is down, and a ladder that visibly recovers on screen is
a feature. The instance name is part of the provider name, so it lands in the hashed search
trail: "which server answered" is itself evidence.

---

## F-14 — Rare native crash at test-suite teardown ⚠️ *(open, not reproducible)*

Observed **once**, on the first `make test` after a fresh `make setup`:

```
libc++abi: terminating due to uncaught exception of type std::__1::system_error:
recursive_mutex lock failed: Invalid argument
make: *** [test] Abort trap: 6
```

All 144 tests had already printed as passing; the abort happened at interpreter
teardown. Re-running immediately succeeded, and **8 consecutive runs afterwards were
clean** — so roughly 1 occurrence in ~17 runs.

**Diagnosis (unconfirmed):** a native teardown race in `onnxruntime`/`opencv` on macOS,
not in this project's Python. Nothing in the test results was wrong; the process failed to
exit cleanly after reporting success.

**Workaround:** re-run. It is not a correctness problem — no test failed.

**If it appears during the recording**, just run it again; do not debug it on camera. If
someone wants to chase it properly, the likely lever is forcing single-threaded
onnxruntime (`OMP_NUM_THREADS=1`, `session.intra_op_num_threads=1`) or running the
model-loading tests in a separate pytest process (`-p no:cacheprovider`, or `--forked`).

> **Caution for whoever measures this next:** a first attempt to quantify the rate used
> `pytest -q 2>&1 | tail -2` and grepped for "144 passed". `tail -2` returns the progress
> bar, not the summary line, so it reported 6/6 failures when nothing had failed. Check
> the process exit code instead.
