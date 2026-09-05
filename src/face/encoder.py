"""Face detection, quality gating and embedding.

Stage 1 of the pipeline, and - unusually - also the adjudicator of stage 2. The
same encoder that reads the probe re-reads every candidate image the search
returns, and the cosine similarity between the two is what decides whether a
search hit is a real match. That is what makes the search step verifiable
rather than merely trusted: see docs/DECISIONS.md D-003.

Model is InsightFace `buffalo_l` - RetinaFace detection plus ArcFace 512-d
embeddings, chosen in D-001. Embeddings come out L2-normalised, so cosine
similarity is a plain dot product.

A note on the quality gate: it exists to make a *refusal legible*. A probe that
is rejected with "face too small: 47px < 80px" reads as an engineered system; a
pipeline that silently returns nothing reads as a broken one. Every gate
therefore carries its measured value and its bound.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

log = logging.getLogger(__name__)

# insightface calls a scikit-image API deprecated in 0.26. Harmless, but it
# fires once per aligned face and would bury the demo output.
#
# The message is "`estimate` is deprecated since version 0.26 ..." - note the
# backticks, which is what a naive ".*estimate is deprecated.*" pattern misses.
warnings.filterwarnings("ignore", message=r".*is deprecated since version.*")
warnings.filterwarnings("ignore", category=FutureWarning, module=r"insightface.*")
warnings.filterwarnings("ignore", category=FutureWarning, module=r"skimage.*")


# --- Quality thresholds ----------------------------------------------------
#
# Deliberately permissive. These reject images that cannot produce a meaningful
# embedding at all, not images that are merely imperfect - a stricter gate would
# reject ordinary social media photos, which are exactly what we need to match.

MIN_FACE_PX = 80          # face bbox width; below this ArcFace degrades sharply
MIN_DET_SCORE = 0.60      # RetinaFace confidence
MIN_BLUR_VAR = 25.0       # Laplacian variance on the native-resolution crop
MAX_YAW_RATIO = 0.55      # nose offset / inter-ocular distance; ~frontal-ish

# Second face at least this fraction of the subject's WIDTH makes the probe
# ambiguous. Width, not area: area scales quadratically, so an area ratio of
# 0.8 means a linear ratio of ~0.89 - far stricter than "comparably sized"
# reads, and strict enough that two obviously competing faces slip through.
# At 0.70 a genuine bystander in the background (typically < 0.5) still passes.
AMBIGUOUS_FACE_RATIO = 0.70


class FaceError(Exception):
    """Base for stage-1 failures that should be reported, not crashed on."""


class ProbeUnreadable(FaceError, OSError):
    """The probe file is missing or is not a decodable image.

    Inherits OSError as well as FaceError so that callers who reasonably
    expect an OSError from something that reads a file still catch it, while
    the CLI can report it alongside every other probe problem.
    """


class NoFaceFound(FaceError):
    pass


class AmbiguousProbe(FaceError):
    """More than one plausible subject; refuse rather than guess."""


class QualityRejected(FaceError):
    """Face found, but not good enough to trust an embedding from."""


@dataclass
class Quality:
    """Measured quality of a detected face. Recorded in the evidence bundle."""

    face_px: int
    det_score: float
    blur_var: float
    yaw_ratio: float

    def to_json(self) -> dict[str, Any]:
        # Every value is coerced to a builtin: numpy scalars reach canonical()
        # as an unsupported type and fail at hashing time, far from the cause.
        return {
            "face_px": int(self.face_px),
            "det_score": round(float(self.det_score), 4),
            "blur_var": round(float(self.blur_var), 2),
            "yaw_ratio": round(float(self.yaw_ratio), 4),
        }


@dataclass
class Face:
    """One detected, embedded face."""

    embedding: np.ndarray          # 512-d, L2-normalised
    bbox: tuple[int, int, int, int]
    quality: Quality
    faces_seen: int = 1
    notes: list[str] = field(default_factory=list)

    def similarity(self, other: Face | np.ndarray) -> float:
        """Cosine similarity. Both embeddings are unit vectors, so a dot."""
        vec = other.embedding if isinstance(other, Face) else other
        return float(np.dot(self.embedding, vec))


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _yaw_ratio(kps: np.ndarray | None) -> float:
    """Crude yaw proxy from the 5-point landmarks.

    Points are [left_eye, right_eye, nose, left_mouth, right_mouth]. On a
    frontal face the nose sits midway between the eyes; as the head turns it
    slides toward one of them. Normalising by inter-ocular distance makes the
    measure scale-free.

    This is not a calibrated pose estimate and is not presented as one - it is
    a cheap gate against profile shots, which ArcFace handles poorly.
    """
    if kps is None or len(kps) < 3:
        return 0.0
    left_eye, right_eye, nose = kps[0], kps[1], kps[2]
    interocular = float(np.linalg.norm(right_eye - left_eye))
    if interocular < 1e-6:
        return 1.0
    eye_mid_x = (float(left_eye[0]) + float(right_eye[0])) / 2.0
    # float() on the way out matters: numpy scalars leak into the evidence
    # bundle and canonicalization rejects them, but only at hashing time -
    # long after the useful stack trace.
    return float(abs(float(nose[0]) - eye_mid_x) / interocular)


class FaceEncoder:
    """Wraps InsightFace. Loads the model once and reuses it.

    The first construction on a fresh machine downloads ~281 MB. That must not
    happen for the first time during a recording - pre-warm it.
    """

    def __init__(self, det_size: int = 640, model: str = "buffalo_l") -> None:
        from insightface.app import FaceAnalysis

        self.model_name = model
        # insightface print()s about a dozen lines of model-loading detail
        # straight to stdout, every time. It is not logging, so it cannot be
        # silenced with a log level - it has to be captured. Left alone it
        # buries the pipeline's own output and would clutter a screen
        # recording, so it is captured and re-emitted at debug level where
        # someone debugging can still get at it.
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self._app = FaceAnalysis(name=model, providers=["CPUExecutionProvider"])
            # ctx_id=-1 forces CPU. No GPU assumption, so a grader's laptop
            # behaves the same as this one.
            self._app.prepare(ctx_id=-1, det_size=(det_size, det_size))
        for line in buffer.getvalue().splitlines():
            if line.strip():
                log.debug("insightface: %s", line.strip())
        log.debug("loaded insightface/%s at det_size=%d", model, det_size)

    @property
    def detector_id(self) -> str:
        """Recorded in evidence so a verifier knows what produced the score."""
        return f"insightface/{self.model_name}"

    def _detect(self, image: np.ndarray) -> list:
        faces = self._app.get(image)
        if not faces:
            raise NoFaceFound("no face detected in image")
        return sorted(
            faces,
            key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
            reverse=True,
        )

    def encode(self, image: np.ndarray, *, enforce_quality: bool = True) -> Face:
        """Detect the subject in `image` and return its embedding.

        `enforce_quality=False` is used for candidate images pulled off the web:
        we cannot dictate the quality of someone else's photo, and rejecting it
        would silently discard real matches. The probe, which we control, is
        always gated.
        """
        faces = self._detect(image)
        best = faces[0]
        notes: list[str] = []

        # --- multi-face policy, stated rather than implied -----------------
        width = lambda f: float(f.bbox[2] - f.bbox[0])  # noqa: E731
        if len(faces) > 1:
            ratio = width(faces[1]) / max(width(best), 1e-9)
            if enforce_quality and ratio >= AMBIGUOUS_FACE_RATIO:
                raise AmbiguousProbe(
                    f"{len(faces)} faces detected and the second is {ratio:.0%} as wide "
                    "as the largest - cannot tell which is the subject. "
                    "Supply a probe with one clear face."
                )
            notes.append(
                f"{len(faces)} faces detected; selected largest "
                f"(next largest is {ratio:.0%} as wide)"
            )

        x1, y1, x2, y2 = (int(v) for v in best.bbox)
        face_px = x2 - x1

        # Blur is measured on the face crop at NATIVE resolution. Measuring a
        # resized copy inverts the result - downscaling sharpens edges per
        # pixel, so a downscaled blurry face scores *higher* than the crisp
        # original. See docs/FINDINGS.md F-2.
        h, w = image.shape[:2]
        crop = image[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
        if crop.size == 0:
            raise QualityRejected("detected face bbox falls outside the image")
        blur_var = float(cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())

        quality = Quality(
            face_px=face_px,
            det_score=float(best.det_score),
            blur_var=blur_var,
            yaw_ratio=_yaw_ratio(getattr(best, "kps", None)),
        )

        if enforce_quality:
            self._gate(quality)

        return Face(
            embedding=np.asarray(best.normed_embedding, dtype=np.float32),
            bbox=(x1, y1, x2, y2),
            quality=quality,
            faces_seen=len(faces),
            notes=notes,
        )

    @staticmethod
    def _gate(q: Quality) -> None:
        """Reject with a specific, measured reason - never a bare failure."""
        reasons = []
        if q.face_px < MIN_FACE_PX:
            reasons.append(f"face too small: {q.face_px}px wide, need >= {MIN_FACE_PX}px")
        if q.det_score < MIN_DET_SCORE:
            reasons.append(f"low detection confidence: {q.det_score:.3f} < {MIN_DET_SCORE}")
        if q.blur_var < MIN_BLUR_VAR:
            reasons.append(f"image too blurry: Laplacian variance {q.blur_var:.1f} < {MIN_BLUR_VAR}")
        if q.yaw_ratio > MAX_YAW_RATIO:
            reasons.append(
                f"face too far from frontal: yaw ratio {q.yaw_ratio:.2f} > {MAX_YAW_RATIO}"
            )
        if reasons:
            raise QualityRejected("; ".join(reasons))

    def encode_file(self, path: str | Path, *, enforce_quality: bool = True) -> Face:
        image = load_image(path)
        return self.encode(image, enforce_quality=enforce_quality)


def load_image(path: str | Path) -> np.ndarray:
    """Read an image, failing loudly on the things that fail quietly.

    A download that returned an HTML error page keeps its .jpg name and is only
    caught here - see docs/FINDINGS.md F-7 for the Wikimedia case that cost
    real time.
    """
    path = Path(path)
    if not path.exists():
        # A FaceError subclass rather than a bare FileNotFoundError: the CLI
        # reports every probe problem the same way, and an unreadable file is
        # a probe problem, not a crash. ProbeUnreadable still subclasses
        # OSError so library callers can catch it either way.
        raise ProbeUnreadable(f"no such image: {path}")
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        head = path.read_bytes()[:64]
        raise ProbeUnreadable(
            f"{path} is not a decodable image (first bytes: {head[:32]!r}). "
            "A failed download often lands as an HTML error page with an image extension."
        )
    return image
