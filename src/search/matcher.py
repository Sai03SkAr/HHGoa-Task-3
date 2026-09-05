"""The closed loop: re-embed every candidate and let the face model decide.

This module is the reason the pipeline is a verification loop rather than a
linear pipe. A search provider proposes posts; nothing about a provider's
ranking is trusted. Each candidate image is downloaded, run through the *same*
encoder that read the probe, and scored by cosine similarity. Only a score at
or above the threshold is a match, and the score is recorded either way.

Two properties this is built to have:

  * **Every score is kept, not just the winner.** A bundle that recorded only
    the best match would be unfalsifiable. Recording the full table means a
    reader can see the margin between the accepted candidate and the rest - and
    a run that matched nothing still produces evidence of what it looked at.

  * **A candidate that fails is recorded, not silently dropped.** Broken image
    links, non-image bodies and faceless photos all appear in the table with
    the reason. Silence is indistinguishable from a bug.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..face.encoder import FaceEncoder, FaceError, load_image
from ..scrape.fetch import FetchError, fetch_image
from .base import Candidate

log = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.45

# Guard against a tag that returns dozens of image-heavy posts: each download
# plus embed costs time, and a demo should not stall.
MAX_IMAGES_PER_CANDIDATE = 4

# Decimal places a score is rounded to, matching evidence/canonical.py.
#
# The rounding happens BEFORE the threshold comparison, not just before
# serialization, and that ordering is load-bearing. Embeddings are float32, so
# a cosine of exactly 0.45 is really 0.4499999880790710; comparing the raw
# value against a float64 threshold rejects it, while the bundle would record
# "cosine": 0.450000 next to a verdict of no-match. The evidence would then
# contradict itself, and a verifier recomputing from the recorded numbers would
# reach the opposite conclusion. Deciding on the same number we publish removes
# the discrepancy by construction.
SCORE_DP = 6


@dataclass
class ScoredImage:
    """One candidate image, scored against the probe."""

    post_url: str
    image_url: str
    author: str
    platform: str
    posted_at: str
    # Already rounded to SCORE_DP when set - see the note on SCORE_DP.
    cosine: float | None = None
    image_sha256: str = ""
    faces_found: int = 0
    local_path: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.cosine is not None

    def to_json(self) -> dict[str, Any]:
        return {
            "post_url": self.post_url,
            "image_url": self.image_url,
            "author": self.author,
            "platform": self.platform,
            "posted_at": self.posted_at,
            # Already rounded at source; round again only to normalise -0.0.
            "cosine": None if self.cosine is None else round(float(self.cosine), SCORE_DP),
            "image_sha256": self.image_sha256,
            "faces_found": self.faces_found,
            "local_path": self.local_path,
            "error": self.error,
        }


@dataclass
class MatchResult:
    """Outcome of adjudicating a candidate set."""

    matched: bool
    threshold: float
    best: ScoredImage | None
    scored: list[ScoredImage] = field(default_factory=list)

    @property
    def considered(self) -> int:
        return len(self.scored)

    @property
    def comparable(self) -> int:
        """How many candidates actually yielded a face to compare."""
        return sum(1 for s in self.scored if s.ok)

    def summary(self) -> str:
        if self.matched and self.best:
            return (
                f"MATCH  cosine={self.best.cosine:.4f} >= {self.threshold} "
                f"({self.comparable}/{self.considered} candidate images comparable)"
            )
        if self.best and self.best.ok:
            return (
                f"NO MATCH  best cosine={self.best.cosine:.4f} < {self.threshold} "
                f"({self.comparable}/{self.considered} candidate images comparable)"
            )
        return f"NO MATCH  no candidate image yielded a comparable face (of {self.considered})"

    def to_json(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "threshold": round(float(self.threshold), SCORE_DP),
            "best": self.best.to_json() if self.best else None,
            "considered": self.considered,
            "comparable": self.comparable,
            # The full table, ordered best-first, is what makes the decision
            # auditable rather than merely asserted.
            "scored": [s.to_json() for s in self.scored],
        }


def adjudicate(
    probe_embedding,
    candidates: list[Candidate],
    encoder: FaceEncoder,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    workdir: Path | None = None,
    max_images_per_candidate: int = MAX_IMAGES_PER_CANDIDATE,
) -> MatchResult:
    """Score every candidate image against the probe embedding.

    `workdir` receives the downloaded images; their paths and hashes go into the
    evidence bundle, so the exact bytes that produced each score can be
    re-examined later.
    """
    scored: list[ScoredImage] = []
    if workdir:
        workdir.mkdir(parents=True, exist_ok=True)

    for c_index, candidate in enumerate(candidates):
        for i_index, image_url in enumerate(candidate.images[:max_images_per_candidate]):
            entry = ScoredImage(
                post_url=candidate.post_url,
                image_url=image_url,
                author=candidate.author,
                platform=candidate.platform,
                posted_at=candidate.posted_at,
            )
            try:
                got = fetch_image(image_url)
                entry.image_sha256 = got.sha256
                if workdir:
                    path = workdir / f"cand_{c_index:02d}_{i_index}.img"
                    got.save(path)
                    entry.local_path = path.name
                    image = load_image(path)
                else:
                    import cv2
                    import numpy as np

                    image = cv2.imdecode(
                        np.frombuffer(got.content, dtype=np.uint8), cv2.IMREAD_COLOR
                    )
                    if image is None:
                        raise FetchError("bytes sniffed as an image but would not decode")

                # Quality gating is deliberately OFF here. We do not control the
                # quality of someone else's posted photo, and rejecting it would
                # silently discard real matches. The probe, which we do control,
                # is always gated.
                face = encoder.encode(image, enforce_quality=False)
                entry.faces_found = face.faces_seen
                # Round here, not at serialization: the verdict below must be
                # decided on the same number the bundle publishes.
                entry.cosine = round(float(face.similarity(probe_embedding)), SCORE_DP)
                log.info("  %s  cosine=%.4f  %s", "MATCH " if entry.cosine >= threshold
                         else "      ", entry.cosine, image_url[:70])
            except (FetchError, FaceError) as exc:
                # Expected failures - a dead link, an HTML error page, a photo
                # with no face in it. Recorded, never fatal.
                entry.error = str(exc)
                log.info("  skip   %s  (%s)", image_url[:70], type(exc).__name__)
            except Exception as exc:  # noqa: BLE001 - one bad image must not end the run
                entry.error = f"{type(exc).__name__}: {exc}"
                log.warning("  error  %s  (%s)", image_url[:70], exc)
            scored.append(entry)

    # Best-first, with unscorable entries last so the table reads top-down.
    scored.sort(key=lambda s: (s.cosine is not None, s.cosine or -1.0), reverse=True)
    best = scored[0] if scored and scored[0].ok else None
    # Both sides rounded to the same precision, so the comparison a verifier
    # redoes from the published bundle gives the identical answer.
    matched = bool(
        best and best.cosine is not None and best.cosine >= round(float(threshold), SCORE_DP)
    )
    return MatchResult(matched=matched, threshold=threshold, best=best, scored=scored)
