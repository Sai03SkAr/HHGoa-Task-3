"""Stage 1: detection, quality gating, embedding.

Marked `slow` because they load the real ~281 MB model. Run the fast suite with
`-m "not slow"`; run everything before recording.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from src.evidence.canonical import canonical
from src.face.encoder import (
    MIN_FACE_PX,
    AmbiguousProbe,
    FaceEncoder,
    FaceError,
    NoFaceFound,
    ProbeUnreadable,
    QualityRejected,
    load_image,
)

FIXTURES = Path(__file__).parent / "fixtures"
PERSON_A = FIXTURES / "person_a.jpg"
PERSON_B = FIXTURES / "person_b.jpg"

needs_fixtures = pytest.mark.skipif(
    not (PERSON_A.exists() and PERSON_B.exists()),
    reason="test fixtures missing - run `make fixtures`",
)


@pytest.fixture(scope="module")
def encoder() -> FaceEncoder:
    return FaceEncoder()


# --- load_image ------------------------------------------------------------


def test_load_image_missing_file(tmp_path):
    """A missing probe is a probe problem, reported like any other."""
    with pytest.raises(ProbeUnreadable, match="no such image"):
        load_image(tmp_path / "nope.jpg")


def test_probe_unreadable_is_both_a_face_error_and_an_oserror(tmp_path):
    """The CLI catches FaceError; a library caller may expect OSError."""
    with pytest.raises(FaceError):
        load_image(tmp_path / "nope.jpg")
    with pytest.raises(OSError):
        load_image(tmp_path / "nope.jpg")


def test_load_image_rejects_html_masquerading_as_jpeg(tmp_path):
    """The exact failure seen with Wikimedia - see docs/FINDINGS.md F-7.

    A failed download keeps its .jpg name, so this must be caught by content,
    not by extension.
    """
    fake = tmp_path / "downloaded.jpg"
    fake.write_bytes(b"<!DOCTYPE html>\n<html><title>404</title></html>")
    with pytest.raises(ProbeUnreadable, match="not a decodable image"):
        load_image(fake)


# --- detection and embedding ----------------------------------------------


@pytest.mark.slow
@needs_fixtures
def test_embedding_is_unit_length(encoder):
    face = encoder.encode_file(PERSON_A)
    assert face.embedding.shape == (512,)
    assert np.isclose(np.linalg.norm(face.embedding), 1.0, atol=1e-4)


@pytest.mark.slow
@needs_fixtures
def test_same_image_is_perfectly_similar(encoder):
    face = encoder.encode_file(PERSON_A)
    assert face.similarity(face) == pytest.approx(1.0, abs=1e-5)


@pytest.mark.slow
@needs_fixtures
def test_different_people_score_far_below_threshold(encoder):
    """The separation the whole match decision depends on."""
    a = encoder.encode_file(PERSON_A)
    b = encoder.encode_file(PERSON_B)
    assert a.similarity(b) < 0.2, "different people must not approach the 0.45 bar"


@pytest.mark.slow
@needs_fixtures
def test_same_person_survives_a_web_round_trip(encoder):
    """Recompression and downscaling must not break the match.

    This is the regime the pipeline actually runs in: the candidate image has
    been through someone else's CDN, not straight off a camera.
    """
    original = load_image(PERSON_A)
    h, w = original.shape[:2]
    small = cv2.resize(original, (w // 3, h // 3))
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 45])
    assert ok
    recompressed = cv2.imdecode(buf, cv2.IMREAD_COLOR)

    a = encoder.encode(original)
    b = encoder.encode(recompressed, enforce_quality=False)
    assert a.similarity(b) > 0.9


@pytest.mark.slow
def test_no_face_in_blank_image(encoder):
    blank = np.full((640, 640, 3), 127, dtype=np.uint8)
    with pytest.raises(NoFaceFound):
        encoder.encode(blank)


# --- quality gate ----------------------------------------------------------


@pytest.mark.slow
@needs_fixtures
def test_quality_gate_rejects_a_tiny_face_with_a_reason(encoder):
    """A refusal must name its measurement, not just fail."""
    original = load_image(PERSON_A)
    # Shrink until the face is comfortably under the pixel floor.
    tiny = cv2.resize(original, (original.shape[1] // 12, original.shape[0] // 12))
    with pytest.raises(QualityRejected, match="face too small"):
        encoder.encode(tiny)


@pytest.mark.slow
@needs_fixtures
def test_quality_gate_can_be_waived_for_candidates(encoder):
    """We do not control the quality of someone else's posted photo."""
    original = load_image(PERSON_A)
    tiny = cv2.resize(original, (original.shape[1] // 12, original.shape[0] // 12))
    face = encoder.encode(tiny, enforce_quality=False)
    assert face.quality.face_px < MIN_FACE_PX  # gate would have rejected it


@pytest.mark.slow
@needs_fixtures
def test_ambiguous_probe_is_refused(encoder):
    """Two comparably sized faces: refuse rather than silently pick one."""
    a = load_image(PERSON_A)
    b = load_image(PERSON_B)
    height = min(a.shape[0], b.shape[0])
    scale = lambda img: cv2.resize(img, (int(img.shape[1] * height / img.shape[0]), height))  # noqa: E731
    side_by_side = np.hstack([scale(a), scale(b)])
    with pytest.raises(AmbiguousProbe, match="cannot tell which is the subject"):
        encoder.encode(side_by_side)


# --- evidence integration --------------------------------------------------


@pytest.mark.slow
@needs_fixtures
def test_quality_json_is_canonicalizable(encoder):
    """Guards a real bug: numpy scalars leaked out of the landmark maths and
    only failed later, at hashing time, with no useful stack trace."""
    face = encoder.encode_file(PERSON_A)
    payload = face.quality.to_json()
    for key, value in payload.items():
        assert type(value) in (int, float), f"{key} is {type(value).__name__}, not a builtin"
    canonical(payload)  # must not raise
