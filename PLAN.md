# PLAN — architecture and build order

> Read [CONTEXT.md](CONTEXT.md) first. This file is the *design*; [PROGRESS.md](PROGRESS.md)
> is the *state*. **Last updated:** 2026-09-05 · nothing implemented yet.

---

## 0. Scope tiers — build strictly in this order

The deadline is **Sept 7, 2026 11:59 PM** with **no resubmissions**. Roughly 2.5 days.
Therefore: **get Tier 1 fully working AND recorded before starting Tier 2.**

| Tier | Items | Status |
|---|---|---|
| **1 — Must have** | Closed verification loop · canonical hashing that reproduces byte-for-byte · tamper demo · a real on-chain tx we can re-verify against · README with all four required sections | not started |
| **2 — High value** | Merkle proofs · search-provider fallback ladder · full search-trail logging · public testnet + explorer link · local chain path for tests | not started |
| **3 — Nice to have** | IPFS/Pinata CID on-chain · liveness/anti-spoof · face blurring of bystanders · cost & latency table · EAS attestation | not started |
| **Dropped** | Docker (not installed, no grading value here) · hosted website (requirement 4 explicitly says not to) | — |

A Tier-1-only submission fully satisfies all five stated requirements. Everything above
that is differentiation, not compliance.

---

## 1. Stage 1 — Face

**Library: InsightFace `buffalo_l`** (RetinaFace detector + ArcFace 512-d embeddings).
Verified working — see [docs/FINDINGS.md](docs/FINDINGS.md) F-1. Chosen over
`face_recognition`/dlib because it ships better embeddings plus landmarks and a
detection confidence for free, and because dlib needs a compiler toolchain we would
rather not depend on.

Pipeline:

1. **Detect.** RetinaFace via `FaceAnalysis.get()`.
2. **Multi-face policy — make the rule explicit and log it.** Pick the largest face by
   bbox area; if a second face is within 80% of the winner's area, refuse and ask the
   user to supply an unambiguous probe rather than guessing.
3. **Quality gate, with a printed reason for every rejection.** A probe that is rejected
   *with a stated reason* reads as engineered; one that silently returns nothing reads as
   broken. Gates: minimum face width in px, Laplacian-variance blur floor, detection
   confidence floor, and yaw/pitch from the 5-point landmarks.
4. **Embed.** 512-d, L2-normalised, so cosine similarity is a plain dot product.
5. **Store the embedding, never the raw probe, in anything that leaves the machine.**

**Threshold: cosine ≥ 0.45.** Justified by measurement rather than folklore — see
FINDINGS F-2, where the same person through a web round-trip scored 0.975–0.991 and two
different people scored −0.044. The README must state the threshold and the evidence
records the achieved score, so the decision is auditable rather than arbitrary.

> Calibration gap to close during implementation: the measured separation covers
> *same-image-re-encoded* vs *different-person*. The genuinely hard regime — **same
> person, different photo, different lighting/age** — typically lands ~0.5–0.7 for
> ArcFace. Validate with real webcam probes before fixing the threshold, and say so
> honestly in Known Limitations.

---

## 2. Stage 2 — Search  ← highest risk, engineer for failure

### 2.1 Why the IDEAS.md ladder cannot be built

Restating [CONTEXT.md](CONTEXT.md) §5 because it drives the whole design: **Bing Visual
Search is retired**, **Yandex has no API**, and **SerpAPI Google Lens accepts only a
public image URL — it has no upload endpoint.** That last one is not a mere
inconvenience; it means the canonical "reverse image search" path *requires publishing
the probe face to the public internet*, which is in direct conflict with this project's
own privacy stance.

That tension is worth surfacing in the README rather than hiding: it is a real,
documented trade-off, and naming it is the kind of thing that separates a considered
build from a demo.

### 2.2 The replacement: two provider families behind one interface

```python
class SearchProvider(Protocol):
    name: str
    def available(self) -> bool: ...
    def search(self, probe: Probe) -> list[Candidate]: ...
```

**Family A — reverse image search** (probe must be published; opt-in, off by default)
- `serpapi_lens` — requires `SERPAPI_KEY` *and* an upload target for the probe.
  Enabled only behind an explicit `--allow-probe-upload` flag so the privacy cost is a
  deliberate act, never a default.

**Family B — scripted search** (probe never leaves the machine) ← **the default**
- `mastodon` — **verified working, zero auth, no quota.** The public hashtag/timeline
  API returns live posts with real authors, real permalink URLs, real timestamps and
  directly downloadable image attachments. See FINDINGS F-3.
- `bluesky` — public endpoint 403s from here; usable only with an app password. Keep as
  a keyed fallback so the ladder has a visible second rung.

The ladder falls through A → B, and **a fall-through is a feature to show on camera**,
not something to hide.

**Why Family B is genuinely a "search step" and not a dodge.** Requirement 2 explicitly
permits "a scripted search approach". More importantly, in Family B *our own face model
does the matching* — the provider only supplies candidates. The search cannot be
hardcoded because the candidate set is fetched live and changes minute to minute, and
the match is decided by a cosine score we compute and record. That is a stronger
demonstration of requirement 1 being load-bearing than delegating the judgement to
Google's "visual match" list.

### 2.3 The demo subject problem — needs a user decision

The pipeline can only find a match if the probe face genuinely appears in a public post.
Options, best first:

1. **The user posts their own photo publicly** (Mastodon, or any indexed public
   profile), then the probe is a live webcam capture of the same person. This gives a
   real social media post, a live search, an undeniably non-hardcoded match, and clean
   consent all at once. **Recommended.**
2. A consenting teammate with an existing public photo.
3. A public figure with public posts — guaranteed to resolve, but weaker on the
   consent narrative.

### 2.4 Anti-fragility for the recording

- **Log the full search trail to disk** — exact request, raw JSON response, HTTP status,
  timestamp — and hash it into the evidence bundle. Scrolling the raw response on camera
  kills any "is this hardcoded?" doubt.
- **Cache responses on disk keyed by query hash**, so a re-run mid-recording cannot burn
  quota or hit a rate limit at the worst possible moment.
- **Scrape properly:** OpenGraph metadata (`og:image`, `og:title`, author, post
  timestamp) plus a Playwright screenshot of the post.

  > **Shipped without the screenshot.** OG metadata and the full page HTML are fetched
  > and hashed into the bundle; Playwright is not a dependency. A ~150 MB browser
  > download and an extra failure mode were not worth it two days from a
  > no-resubmission deadline, and the **hashed page HTML is stronger evidence than a
  > picture of a rendered page**. The bundle schema and `verify` already accept a
  > `screenshot_sha256`, so adding it later needs no format change.

---

## 3. Stage 3 — Blockchain

### 3.1 Contract

Minimal registry, keyed by Merkle root. Deliberately small — the sophistication belongs
in what gets hashed, not in Solidity:

```solidity
contract EvidenceRegistry {
    struct Anchor { bytes32 root; string cid; address submitter; uint64 timestamp; }
    mapping(bytes32 => Anchor) public anchors;

    event Anchored(bytes32 indexed root, string cid, address indexed submitter, uint64 timestamp);

    function anchor(bytes32 root, string calldata cid) external {
        require(anchors[root].timestamp == 0, "already anchored");
        anchors[root] = Anchor(root, cid, msg.sender, uint64(block.timestamp));
        emit Anchored(root, cid, msg.sender, uint64(block.timestamp));
    }

    function verify(bytes32 root) external view returns (bool, Anchor memory) {
        return (anchors[root].timestamp != 0, anchors[root]);
    }
}
```

`cid` stays in the struct even while IPFS is Tier 3 — an empty string costs nothing and
avoids a redeploy if pinning lands later.

### 3.2 Toolchain: Hardhat, not Foundry

Foundry is not installed and Node is. Hardhat also gives a grader a one-command
`npm install` path. Dual target:

- **Local Hardhat network** — the default. Tests and CI never need faucet funds.
- **Public testnet** — for the recorded demo, with a live explorer link. Verified
  reachable: Sepolia (`0xaa36a7`), Polygon Amoy (`0x13882`), Base Sepolia (`0x14a34`).
  **Polygon Amoy is the recommendation** — its faucet is usually the least painful.

Print **chain ID, tx hash, gas used, block number** on anchor. Requirement 3 says any
chain is acceptable *"as long as you can demonstrate re-verifying the data against the
on-chain record"* — so the re-verification path, not the choice of chain, is what is
actually being graded.

### 3.3 Privacy on-chain — non-negotiable

**Never put the face image or the raw embedding on-chain.** Anchor a salted commitment
(`sha256(salt || embedding)`) only. State this explicitly in the README: an on-chain
hash is not personal data, which is exactly what makes the right-to-erasure story
coherent — local evidence is deletable, the anchor is not, and the anchor reveals
nothing on its own.

Burner key only, loaded from `.env`, `.env` gitignored, `.env.example` committed.

---

## 4. Evidence bundle & canonicalization

**This is where re-verification demos usually die on stage: a hash that will not
reproduce.** Canonicalize before hashing — RFC 8785 (JCS), or equivalently sorted keys,
no whitespace, and a fixed float format. Floats are the classic trap: the cosine score
must serialise identically on every run, so fix it to a set number of decimal places
*before* it enters the bundle.

```jsonc
{
  "run_id": "2026-09-05T14:22:03Z-a3f9",
  "probe": {
    "image_sha256": "…",
    "embedding_commitment": "sha256(salt || embedding)",
    "detector": "insightface/buffalo_l",
    "quality": { "blur": 142.7, "yaw_deg": 4.1, "face_px": 312 }
  },
  "search": {
    "providers_tried": ["serpapi_lens", "mastodon"],
    "provider_used": "mastodon",
    "queries": [ { "ts": "…", "request": "…", "response_sha256": "…" } ]
  },
  "match": {
    "post_url": "https://…", "platform": "mastodon", "author": "…",
    "post_timestamp": "…", "candidate_image_sha256": "…",
    "page_html_sha256": "…", "screenshot_sha256": "…",
    "cosine_similarity": 0.612, "threshold": 0.45
  },
  "chain": { "network": "polygon-amoy", "chain_id": 80002, "contract": "0x…" }
}
```

Every leaf hash goes into a Merkle tree; the **root** is what gets anchored. The Merkle
structure buys a real capability: proving one item (just the similarity score, say)
without disclosing the rest.

---

## 5. Repo layout & CLI

```
.
├── README.md              # the graded deliverable - written LAST
├── CONTEXT.md PLAN.md PROGRESS.md
├── docs/                  # DECISIONS.md, FINDINGS.md
├── Makefile               # make demo / make test / make verify
├── .env.example
├── contracts/             # EvidenceRegistry.sol + Hardhat deploy script
├── src/
│   ├── face/              # detect, quality gate, embed
│   ├── search/            # SearchProvider base + mastodon / serpapi / bluesky
│   ├── scrape/            # OG metadata, image download (no screenshot - see §2.4)
│   ├── evidence/          # canonical JSON, hashing, Merkle tree
│   ├── chain/             # web3 client, anchor, verify
│   └── cli.py
├── tests/                 # canonicalization, Merkle, mocked search, local-chain integration
└── runs/                  # one dir per run (gitignored)
```

Two verbs, that is all:

```bash
python -m src.cli run    --image probe.jpg      # → runs/<run_id>/ + tx hash
python -m src.cli verify --run runs/<run_id>    # re-derive from disk
python -m src.cli verify --tx 0xabc…            # pull root from chain, re-verify
```

**As shipped**, `runs/<run_id>/` holds `evidence.json`, `receipt.json`, `probe.jpg`,
`salt.bin`, `candidates/`, `search_trail/`, and `page.html` on a match. (`manifest.json`,
`merkle.json` and `run.log` from the original sketch were dropped as redundant - the
Merkle root is derivable from `evidence.json` and duplicating it invites the two copies
to disagree.)

`verify` recomputes everything and prints a green **PASS** or a red **FAIL** naming the
exact mismatching hash.

---

## 6. Build order

Each step ends in something demonstrable. Do not start a step before the previous one runs.

1. **Scaffold** — repo skeleton, `uv` venv on **Python 3.12**, `.env.example`, pytest wired.
2. **Stage 1** — detect → quality gate → embed. Test: two images of the same person score high, two different people score low.
3. **Evidence core** — canonical JSON + hashing + Merkle. **Test first**: canonicalization must be idempotent and byte-stable across processes. This is the piece that silently breaks the finale.
4. **Stage 3 on a local chain** — contract, deploy, anchor, verify, and the **tamper test** going red. *Deliberately before the search stage:* it is the requirement most likely to be under-built, and it is fully in our control.
5. **Stage 2** — Mastodon provider, candidate download, re-embed, adjudicate. Then scrape OG metadata + page HTML.
6. **Wire end to end** — `run` and `verify` over the real loop.
7. **Testnet deploy** — real tx, explorer link. Needs faucet funds; **start the funding early**, it is the slowest external dependency.
8. **README** — all four required sections, written against what actually shipped.
9. **Dry run** — clone into a fresh directory, follow the README verbatim.
10. **Record.**

---

## 7. The recording

Terminal left, browser right. Target 5–7 minutes, no editing.

1. Show the **wall clock / today's date** on screen — timestamps everything after it.
2. **Take the probe photo from the webcam, live.** This single act forecloses the
   "pre-picked result" question better than any explanation could.
3. `cli run`. Narrate the quality gate and the embedding.
4. **Scroll the raw search API response.** If a provider falls through the ladder, show
   it — do not hide it.
5. Show the scraped post **in the browser**, beside the candidate image the code downloaded.
6. Show the cosine similarity against the threshold.
7. Show the Merkle root and the tx hash.
8. **Open the tx on the explorer.** Live, in the browser.
9. `cli verify --tx 0x…` → green **PASS**.
10. **The tamper test** — flip one byte in the local evidence file, re-run `verify`, show
    the red **FAIL** and the mismatching hash, restore, show **PASS** again.

Step 10 is the most convincing 20 seconds in the submission; requirement 3 asks
specifically for demonstrated re-verification against the on-chain record, and nothing
shows tamper-evidence more viscerally.

Upload unlisted and **test the link in a private window** before submitting.

---

## 8. Ethics & privacy

The underlying capability is *identifying strangers from a photo*. Visibly having
thought about that is cheap and differentiating:

- **Consent allowlist** — demo restricted to subjects who agreed; the CLI refuses probes
  outside it in demo mode.
- **Blur other faces** in scraped images before storing them as evidence (Tier 3).
- **No raw biometrics on-chain** — salted commitments only.
- **Right-to-erasure note** — local evidence is deletable; the on-chain anchor is a hash,
  not personal data. Explain why that distinction matters.
- A short `ETHICS.md` (or README section) stating intended use, and what we would not
  ship without.
