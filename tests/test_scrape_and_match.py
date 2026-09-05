"""Downloading candidates safely, and adjudicating them against the probe."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.face.encoder import FaceError, NoFaceFound
from src.scrape.fetch import FetchError, parse_meta, sniff_image
from src.search.base import Candidate
from src.search.matcher import adjudicate

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
HTML = b"<!DOCTYPE html>\n<html><title>404 Not Found</title></html>"


# --- content sniffing ------------------------------------------------------


@pytest.mark.parametrize(
    "data,expected",
    [
        (JPEG, "jpeg"),
        (PNG, "png"),
        (b"GIF89a" + b"\x00" * 16, "gif"),
        (b"BM" + b"\x00" * 16, "bmp"),
        (b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 8, "webp"),
        (b"\x00" * 4 + b"ftyp" + b"\x00" * 8, "heif"),
    ],
)
def test_sniff_recognises_real_images(data, expected):
    assert sniff_image(data) == expected


def test_sniff_rejects_html():
    """The failure that cost real time - see docs/FINDINGS.md F-7.

    An error page arrives with a 200 status and a .jpg URL. Only the bytes tell
    the truth.
    """
    assert sniff_image(HTML) is None


def test_sniff_rejects_empty_and_short():
    assert sniff_image(b"") is None
    assert sniff_image(b"\xff") is None


# --- OpenGraph parsing -----------------------------------------------------


def test_parse_meta_extracts_opengraph():
    html = """
    <html><head><title>  A Post  </title>
    <meta property="og:image" content="https://x.test/i.jpg">
    <meta property="og:title" content="Look at this">
    <meta property="og:description" content="Some words">
    </head></html>
    """
    meta = parse_meta(html, "https://x.test/p/1")
    assert meta.title == "A Post"
    assert meta.og_image == "https://x.test/i.jpg"
    assert meta.og_title == "Look at this"
    assert meta.og_description == "Some words"
    assert meta.url == "https://x.test/p/1"


def test_parse_meta_handles_reversed_attribute_order():
    """Real HTML does not agree on whether content or property comes first."""
    html = '<meta content="https://x.test/i.jpg" property="og:image">'
    assert parse_meta(html).og_image == "https://x.test/i.jpg"


def test_parse_meta_survives_missing_tags():
    meta = parse_meta("<html><body>nothing here</body></html>")
    assert meta.og_image == "" and meta.title == ""


def test_parse_meta_is_serializable():
    parse_meta('<meta property="og:image" content="x">').to_json()


# --- adjudication ----------------------------------------------------------


class FakeEncoder:
    """Returns a scripted embedding per call, so scoring is deterministic."""

    def __init__(self, scores: list[float | Exception]):
        self._scores = list(scores)
        self.calls = 0

    def encode(self, image, enforce_quality=True):
        from src.face.encoder import Face, Quality

        value = self._scores[self.calls % len(self._scores)]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        # Build a unit vector whose dot with [1,0,0,...] is exactly `value`.
        vec = np.zeros(512, dtype=np.float32)
        vec[0] = value
        remainder = float(np.sqrt(max(0.0, 1.0 - value * value)))
        vec[1] = remainder
        return Face(
            embedding=vec, bbox=(0, 0, 10, 10),
            quality=Quality(100, 0.9, 100.0, 0.1), faces_seen=1,
        )


PROBE = np.zeros(512, dtype=np.float32)
PROBE[0] = 1.0


def make_candidates(n_images: int) -> list[Candidate]:
    return [
        Candidate(
            post_url=f"https://x.test/p/{i}", platform="test", author=f"a{i}",
            images=[f"https://x.test/i{i}.jpg"], posted_at="2026-09-05T00:00:00Z",
        )
        for i in range(n_images)
    ]


@pytest.fixture
def fake_fetch(monkeypatch):
    """Serve a valid JPEG for every image URL."""
    from src.scrape import fetch as fetch_mod
    from src.search import matcher as matcher_mod

    class Got:
        content = JPEG
        sha256 = "deadbeef"

        def save(self, path: Path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(JPEG)
            return path

    monkeypatch.setattr(matcher_mod, "fetch_image", lambda url, **kw: Got())
    # The matcher decodes bytes when no workdir is given; give it an image.
    monkeypatch.setattr(matcher_mod, "load_image", lambda p: np.zeros((64, 64, 3), np.uint8))
    return Got


def test_match_above_threshold(fake_fetch, tmp_path):
    result = adjudicate(PROBE, make_candidates(1), FakeEncoder([0.71]),
                        threshold=0.45, workdir=tmp_path)
    assert result.matched is True
    assert result.best.cosine == pytest.approx(0.71, abs=1e-4)
    assert "MATCH" in result.summary()


def test_no_match_below_threshold(fake_fetch, tmp_path):
    result = adjudicate(PROBE, make_candidates(1), FakeEncoder([0.30]),
                        threshold=0.45, workdir=tmp_path)
    assert result.matched is False
    assert "NO MATCH" in result.summary()
    # The score is still recorded - a near miss is evidence too.
    assert result.best.cosine == pytest.approx(0.30, abs=1e-4)


def test_threshold_boundary_is_inclusive(fake_fetch, tmp_path):
    result = adjudicate(PROBE, make_candidates(1), FakeEncoder([0.45]),
                        threshold=0.45, workdir=tmp_path)
    assert result.matched is True, "score == threshold must count as a match"


def test_best_of_several_is_chosen(fake_fetch, tmp_path):
    result = adjudicate(PROBE, make_candidates(3), FakeEncoder([0.20, 0.80, 0.50]),
                        threshold=0.45, workdir=tmp_path)
    assert result.best.cosine == pytest.approx(0.80, abs=1e-4)
    scores = [s.cosine for s in result.scored]
    assert scores == sorted(scores, reverse=True), "table must read best-first"


def test_every_score_is_recorded_not_just_the_winner(fake_fetch, tmp_path):
    """A bundle recording only the winner would be unfalsifiable."""
    result = adjudicate(PROBE, make_candidates(3), FakeEncoder([0.20, 0.80, 0.50]),
                        threshold=0.45, workdir=tmp_path)
    assert result.considered == 3
    assert len(result.to_json()["scored"]) == 3


def test_faceless_candidate_is_recorded_with_a_reason(fake_fetch, tmp_path):
    result = adjudicate(PROBE, make_candidates(2),
                        FakeEncoder([NoFaceFound("no face detected in image"), 0.9]),
                        threshold=0.45, workdir=tmp_path)
    assert result.considered == 2
    assert result.comparable == 1
    failed = [s for s in result.scored if not s.ok]
    assert len(failed) == 1 and "no face" in failed[0].error


def test_unfetchable_candidate_does_not_end_the_run(monkeypatch, tmp_path):
    from src.search import matcher as matcher_mod

    def boom(url, **kw):
        raise FetchError("did not return an image")

    monkeypatch.setattr(matcher_mod, "fetch_image", boom)
    result = adjudicate(PROBE, make_candidates(2), FakeEncoder([0.9]),
                        threshold=0.45, workdir=tmp_path)
    assert result.matched is False
    assert result.considered == 2
    assert all(not s.ok and "did not return an image" in s.error for s in result.scored)


def test_no_candidates_gives_a_clean_no_match(tmp_path):
    result = adjudicate(PROBE, [], FakeEncoder([0.9]), threshold=0.45, workdir=tmp_path)
    assert result.matched is False
    assert result.considered == 0
    assert "no candidate image" in result.summary()


def test_result_is_canonicalizable(fake_fetch, tmp_path):
    """The match result goes straight into the hashed bundle."""
    from src.evidence.canonical import canonical

    result = adjudicate(PROBE, make_candidates(2), FakeEncoder([0.71, 0.20]),
                        threshold=0.45, workdir=tmp_path)
    canonical(result.to_json())  # must not raise


def test_cosine_is_rounded_before_hashing(fake_fetch, tmp_path):
    """Raw model floats are not bit-reproducible across machines."""
    result = adjudicate(PROBE, make_candidates(1), FakeEncoder([0.123456789]),
                        threshold=0.45, workdir=tmp_path)
    assert result.to_json()["best"]["cosine"] == pytest.approx(0.123457, abs=1e-9)


def test_downloaded_images_are_saved_for_evidence(fake_fetch, tmp_path):
    result = adjudicate(PROBE, make_candidates(2), FakeEncoder([0.5]),
                        threshold=0.45, workdir=tmp_path)
    saved = sorted(p.name for p in tmp_path.iterdir())
    assert len(saved) == 2
    assert all(s.local_path for s in result.scored)


def test_images_per_candidate_is_capped(fake_fetch, tmp_path):
    many = [Candidate(post_url="https://x.test/p/0", platform="t", author="a",
                      images=[f"https://x.test/{i}.jpg" for i in range(10)])]
    result = adjudicate(PROBE, many, FakeEncoder([0.1]), threshold=0.45,
                        workdir=tmp_path, max_images_per_candidate=3)
    assert result.considered == 3
