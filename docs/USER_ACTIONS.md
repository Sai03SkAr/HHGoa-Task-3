# USER_ACTIONS — the things only Sai can do

> Everything here is **needed for the final recording, not for development.** Building
> proceeds fully without any of it. Do these in spare moments; nothing is blocked meanwhile.
>
> **Last updated:** 2026-09-05

---

## A-1 · Post a photo of yourself publicly  — *do this first, it has the longest tail*

**Why it's needed.** The pipeline finds a match only if your face genuinely appears in a
public post. This is the one thing that cannot be faked or worked around — and doing it
yourself is also what makes the consent story clean.

**Why I can't do it.** Posting content on your behalf and creating accounts are both off
limits for me, and I don't have your photo.

### Steps (~5 minutes)

1. Go to **https://mastodon.social** and sign up. Free, no phone number required. Any
   instance works, but `mastodon.social` is the one the pipeline queries by default.
2. Make sure the account is **public**, not locked. Settings → Profile → leave
   *"Require follow requests"* **unchecked**.
3. Post **1–3 clear photos of your face**. Good light, face reasonably large in frame,
   looking at the camera. Ordinary selfies are fine — this should look like a normal post.
4. **Add a distinctive hashtag** to each post, something nobody else is using. For example
   `#hhgoa2026sai`. Tell me the exact tag.
5. Confirm it's publicly visible: open the post URL in a **private/incognito window**. If
   it loads while logged out, we're good.

### What to send me

- the hashtag you used
- your handle (e.g. `@yourname@mastodon.social`)
- the post URL(s)

### Why a hashtag isn't "hardcoding the result"

Choosing a *search query* is how search works — every search engine takes one. What must
not be hardcoded is the **result**. The pipeline fetches whatever posts that tag currently
returns, downloads their images, and the face model decides which (if any) matches, with
the cosine score recorded either way. Point the same query at a tag full of other people's
faces and it correctly finds nothing. That's the difference, and it's visible on camera.

---

## A-2 · Fund a testnet wallet — *only if we want a live explorer link*

**Why it's needed.** Only for the recorded demo. A local Hardhat chain satisfies the task
requirement on its own ("any blockchain may be used — public testnet, mainnet, or a
local/simulated chain"). A live explorer link is a credibility upgrade, not compliance.

**Why I can't do it.** Faucets require captchas and social-auth sign-ins.

### Steps

1. I'll generate a **burner wallet** locally and print the address. It will hold only
   worthless testnet funds and its key stays in gitignored `.env`. **Never put real funds
   in it.**
2. Take that address to a **Polygon Amoy** faucet:
   - https://faucet.polygon.technology (select *Amoy*) — usually the easiest
   - https://www.alchemy.com/faucets/polygon-amoy — needs a free Alchemy account
3. Request test POL. You need only a tiny amount — a single anchor transaction costs a
   fraction of a cent equivalent.
4. Tell me when it lands and I'll deploy + anchor against Amoy.

**If faucets give you trouble, skip it.** The local chain path is fully compliant and I'll
build that regardless. Do not spend more than ~20 minutes fighting a faucet.

---

## A-3 · Record the screen — *at the very end*

Full shot list is in [../PLAN.md](../PLAN.md) §7. I'll give you a rehearsed script and
pre-warm every cache first, so nothing downloads or rate-limits mid-take.

Two things to know now:
- The first-ever run downloads a **281 MB** face model. We pre-warm this before recording.
- Have the wall clock / today's date visible on screen at the start.

---

## A-4 · Submit

- Repo: https://github.com/Sai03SkAr/HHGoa-Task-3 (must be **public**)
- Form: https://forms.gle/oZbQGuwiNeHVcHWo8
- Deadline **Sept 7, 2026, 11:59 PM**. **No resubmissions** — submit only when final.
- Test the recording link in a **private window** before submitting.
