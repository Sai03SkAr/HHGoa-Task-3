# USER_ACTIONS — your step-by-step guide to finishing

> Everything the code can do is done. What is left needs a human. This file is the
> complete list, in order, in plain language.
>
> **Last updated:** 2026-09-05 · **Deadline: Sept 7, 2026, 11:59 PM · no resubmissions**

---

## The whole plan at a glance

| Step | What | How long | Who |
|---|---|---|---|
| **1** | Post a photo of yourself on Mastodon | 5 min | you |
| **2** | Send me the hashtag + handle; I wire it up and test | 10 min | me |
| **3** | *(optional)* Fund a testnet wallet for a live explorer link | 15 min | you |
| **4** | I prepare and rehearse the exact demo | 15 min | me |
| **5** | Record your screen | 10 min | you |
| **6** | Upload the video, submit the form | 10 min | you |

**You can do step 1 right now.** Nothing else is waiting on anything else.

---

## STEP 1 · Post a photo of yourself on Mastodon

**Why:** the pipeline searches real social media and matches faces. To demo it finding
**you**, a photo of your face has to actually be in a public post. This is the one thing
no code can do.

**Why it isn't cheating:** we choose a *search query*, exactly like typing something into
Google. What we never choose is the **result**. The pipeline downloads whatever posts that
query returns right now, runs every image through the face model, and the score decides.
Point it at a tag full of strangers and it correctly finds nobody.

### 1.1 — Make the account

1. Go to **https://mastodon.social**
2. Click **Create account**. It is free, and no phone number is needed.
3. Pick any username. Confirm your email.

> ⚠️ **Use `mastodon.social` specifically, not another Mastodon server.** Our search asks
> `mastodon.social` what it knows about. A post made on a different server has to
> *federate* across before it shows up there, which can take time or not happen at all.
> Posting directly on `mastodon.social` means it is findable immediately.

### 1.2 — Make sure your account is public

1. **Settings → Profile**
2. Make sure **"Require follow requests"** is **UNCHECKED**.

If that box is ticked, your posts are private and nothing can find them.

### 1.3 — Post your photos

Post **2 or 3 separate posts**, each with a clear photo of your face.

Good photos:
- your face is large in the frame, not a tiny figure in a landscape
- decent light, looking roughly at the camera
- ordinary selfies are perfect — this should look like a normal post

Avoid: sunglasses, heavy shadow, side profile, or a group photo where several faces are
the same size.

> **Why 2 or 3 posts and not one?** The demo is far more convincing when the probe photo
> is a *different* photo from the ones it finds. Matching a photo to itself proves very
> little; matching you across two different photos proves the face model is doing real work.

### 1.4 — Add a unique hashtag to every post

Put a hashtag on each post that nobody else on earth is using. For example:

```
#saihhgoa2026
```

Check it is unused: open `https://mastodon.social/tags/saihhgoa2026` — it should show only
your posts.

### 1.5 — Confirm the posts are really public

Open one of your post links in a **private / incognito browser window**. If it loads while
you are logged out, it is public. If it asks you to log in, go back to 1.2.

### 1.6 — Keep one photo aside as the probe

Take **one more photo of yourself that you do NOT post** — a fresh selfie from your laptop
webcam is ideal. That becomes the "face scan" the pipeline starts from.

Save it somewhere easy, e.g. `~/Desktop/probe.jpg`.

> This is what makes the demo airtight: you scan a face that exists nowhere online, and
> the pipeline still finds your public posts.

### 1.7 — Send me these three things

```
hashtag :  #saihhgoa2026
handle  :  @yourname@mastodon.social
probe   :  ~/Desktop/probe.jpg
```

---

## STEP 2 · I wire it up *(me, ~10 min)*

I will run the real pipeline against your hashtag and handle, confirm it finds you, check
the score is comfortably above the threshold, and fix anything that comes up. Then I will
tell you the exact commands for the recording.

---

## STEP 3 · *(Optional)* Fund a testnet wallet

**Skip this if you want to finish faster.** The task explicitly allows a local chain:

> *"Any blockchain may be used — public testnet, mainnet, or a local/simulated chain."*

A public testnet only adds a clickable explorer link in the video. It is a nice touch, not
a requirement.

### If you want to do it

1. I generate a throwaway wallet:
   ```bash
   .venv/bin/python -m src.cli wallet-new
   ```
   This prints an **address** and a **private key**. The key goes in `.env`, which is
   gitignored and never uploaded.

   > ⚠️ This wallet is for worthless test coins only. **Never send real money to it.**

2. Take the **address** to a Polygon Amoy faucet:
   - https://faucet.polygon.technology (choose **Amoy**)
   - or https://www.alchemy.com/faucets/polygon-amoy (needs a free account)

3. Ask for test POL. You need a tiny amount — one transaction costs a fraction of a cent.

4. Tell me when it arrives. I deploy to Amoy and put the live explorer link in the README.

**If a faucet gives you trouble, stop after 20 minutes and skip it.** It is genuinely
optional.

---

## STEP 4 · I rehearse the demo *(me, ~15 min)*

I will pre-download everything so nothing loads during your recording, run the whole thing
once end to end, and hand you a script with the exact commands in order.

---

## STEP 5 · Record your screen

Plain screen capture. **No editing needed.** Aim for 5–7 minutes.

- **Mac:** press `Cmd + Shift + 5` → **Record Entire Screen**. Turn the microphone on if
  you want to narrate — talking through it helps, but it is not required.

### Layout

Terminal on the **left**, browser on the **right**, both visible at once.

### What to show, in order

1. **Today's date on screen.** Open a clock or a calendar for a second. This timestamps
   everything that follows.
2. **Take the probe photo live from your webcam**, right there on camera. This single act
   answers the "did you pre-pick the result?" question better than any explanation.
3. **Run the pipeline.** Narrate what appears: the quality gate, the face size, the search.
4. **Scroll the raw search response** in the terminal — the actual JSON that came back from
   Mastodon. This is the proof it is a real live search.
5. **Open the found post in the browser**, next to the image the code downloaded. Same
   photo, same person.
6. **Point at the cosine score** and the threshold. Say what it means: "0.76, and the bar
   is 0.45, so this is a match."
7. **Show the Merkle root and the transaction hash.**
8. **Open the transaction in the block explorer** *(only if you did Step 3)*.
9. **Run `verify`** → green **PASS**.
10. **The tamper test.** Change one digit in `evidence.json`, run `verify` again → red
    **FAIL** showing the mismatch. Change it back → **PASS** again.

> **Step 10 is the most important 20 seconds in the whole video.** The task specifically
> asks you to demonstrate re-verifying against the on-chain record. Do not rush it.

### If something goes wrong mid-recording

- A test crashes with `Abort trap: 6` → just run it again, it is a known rare glitch.
- A search returns nothing → run it again; the ladder tries other servers.
- **Do not** raise `--limit` to get more results. It gets very slow. Keep the defaults.

---

## STEP 6 · Submit

1. Upload the video to **YouTube (unlisted)** or **Google Drive**.
2. **Test the link in a private/incognito window.** If it does not open there, nobody can
   watch it. This is the single most common submission mistake.
3. Check the repo is public: https://github.com/Sai03SkAr/HHGoa-Task-3
4. Submit the form: **https://forms.gle/oZbQGuwiNeHVcHWo8**
   - GitHub repo link
   - video link

> **There are no resubmissions.** Only submit when you are happy with it.

---

## Quick answers

**Do I have to do Step 3 (the testnet)?**
No. The local chain fully satisfies the task. Step 3 only adds a clickable link.

**What if I do not want my face in a public post?**
Then we demo against a public account instead, which already works. The video would show
the pipeline correctly identifying someone else's public posts. It is a slightly weaker
story, but completely valid.

**Can I delete the Mastodon posts afterwards?**
Yes. Do it after recording. The evidence on your machine is deletable too. What stays on
the blockchain is only a hash — not your photo, not your face data, and not anything that
can be turned back into either.

**How long until this is finished?**
If you do Step 1 now and skip Step 3, realistically about **an hour of your time**.
