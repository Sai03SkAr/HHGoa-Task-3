"""Stage 2: the provider ladder, the search trail, and Mastodon parsing.

Offline by design. Live-network behaviour is recorded in docs/FINDINGS.md F-3
and F-10; these tests pin the logic, so the suite stays runnable on a plane.
"""

from __future__ import annotations

import json

import pytest

from src.search.base import (
    Candidate,
    SearchTrail,
    run_ladder,
    utc_now,
)
from src.search.mastodon import MastodonProvider, _strip_html


# --- fakes -----------------------------------------------------------------


class FakeProvider:
    """A provider whose behaviour the test dictates."""

    def __init__(self, name, candidates=None, *, available=True, raises=None):
        self.name = name
        self._candidates = candidates or []
        self._available = available
        self._raises = raises
        self.calls = 0

    def available(self):
        return self._available

    def search(self, query, trail, limit=40):
        self.calls += 1
        if self._raises:
            raise self._raises
        return list(self._candidates)


def candidate(url="https://example.test/p/1") -> Candidate:
    return Candidate(
        post_url=url, platform="test", author="someone",
        images=["https://example.test/img.jpg"], posted_at="2026-09-05T00:00:00Z",
    )


# --- the ladder ------------------------------------------------------------


def test_first_working_provider_wins():
    a = FakeProvider("a", [candidate()])
    b = FakeProvider("b", [candidate()])
    result = run_ladder([a, b], "q", SearchTrail())
    assert result.provider_used == "a"
    assert b.calls == 0, "ladder must stop at the first success"


def test_unconfigured_provider_is_skipped_not_tried():
    off = FakeProvider("off", [candidate()], available=False)
    on = FakeProvider("on", [candidate()])
    result = run_ladder([off, on], "q", SearchTrail())
    assert result.provider_used == "on"
    assert off.calls == 0
    assert result.notes["off"] == "not configured"
    assert "off" not in result.providers_tried


def test_ladder_falls_through_an_erroring_provider():
    """A rate-limited API mid-demo must not end the run."""
    boom = FakeProvider("boom", raises=RuntimeError("429 rate limited"))
    good = FakeProvider("good", [candidate()])
    result = run_ladder([boom, good], "q", SearchTrail())
    assert result.provider_used == "good"
    assert "429" in result.notes["boom"]
    assert result.providers_tried == ["boom", "good"]


def test_ladder_falls_through_an_empty_provider():
    empty = FakeProvider("empty", [])
    good = FakeProvider("good", [candidate()])
    result = run_ladder([empty, good], "q", SearchTrail())
    assert result.provider_used == "good"
    assert result.notes["empty"] == "no candidates"


def test_ladder_exhausted_returns_empty_not_error():
    result = run_ladder([FakeProvider("a", []), FakeProvider("b", [])], "q", SearchTrail())
    assert result.candidates == []
    assert result.provider_used == ""
    assert result.providers_tried == ["a", "b"]


def test_ladder_result_serializes():
    result = run_ladder([FakeProvider("a", [candidate()])], "q", SearchTrail())
    payload = result.to_json()
    assert payload["provider_used"] == "a"
    assert payload["candidate_count"] == 1


# --- the trail -------------------------------------------------------------


def test_trail_records_hash_and_body(tmp_path):
    trail = SearchTrail(run_dir=tmp_path)
    body = b'{"hello":"world"}'
    entry = trail.record(provider="p", method="GET", url="https://x.test",
                         params={"q": 1}, status=200, body=body, duration_ms=12)
    assert entry.response_sha256 == __import__("hashlib").sha256(body).hexdigest()
    assert entry.response_bytes == len(body)
    written = tmp_path / "search_trail" / "00_p.json"
    assert written.read_bytes() == body, "raw response must be on disk for the evidence"
    assert entry.body_path == "search_trail/00_p.json"


def test_trail_entries_are_numbered_in_order(tmp_path):
    trail = SearchTrail(run_dir=tmp_path)
    for i in range(3):
        trail.record(provider="p", method="GET", url="u", params={},
                     status=200, body=str(i).encode(), duration_ms=1)
    names = sorted(p.name for p in (tmp_path / "search_trail").iterdir())
    assert names == ["00_p.json", "01_p.json", "02_p.json"]


def test_cache_round_trip(tmp_path):
    trail = SearchTrail(cache_dir=tmp_path / "cache")
    params = {"limit": 5}
    assert trail.cached("p", "GET", "https://x.test", params) is None
    trail.store_cache("p", "GET", "https://x.test", params, b"payload")
    assert trail.cached("p", "GET", "https://x.test", params) == b"payload"
    # A different query must not collide.
    assert trail.cached("p", "GET", "https://x.test", {"limit": 6}) is None


def test_cached_responses_are_flagged_in_the_trail(tmp_path):
    """The trail must never imply a live call that did not happen."""
    trail = SearchTrail(run_dir=tmp_path)
    entry = trail.record(provider="p", method="GET", url="u", params={"a": 1},
                         status=200, body=b"{}", duration_ms=0, from_cache=True)
    assert entry.params["_served_from_cache"] is True


def test_utc_now_shape():
    assert utc_now().endswith("Z") and len(utc_now()) == 20


# --- Mastodon parsing ------------------------------------------------------


STATUS = {
    "id": "1",
    "created_at": "2026-09-05T07:04:10.000Z",
    "url": "https://pixelfed.social/p/someone/123",
    "uri": "https://mastodon.social/users/someone/statuses/123",
    "content": "<p>Hello <br/>world</p>",
    "account": {"acct": "someone@pixelfed.social"},
    "media_attachments": [
        {"type": "image", "url": "https://files.test/a.jpg"},
        {"type": "video", "url": "https://files.test/b.mp4"},
        {"type": "image", "url": "https://files.test/c.jpg"},
    ],
}


def test_status_to_candidate_keeps_only_images():
    got = MastodonProvider()._to_candidate(STATUS)
    assert got is not None
    assert got.images == ["https://files.test/a.jpg", "https://files.test/c.jpg"]
    assert got.author == "someone@pixelfed.social"
    assert got.platform == "mastodon"
    assert got.posted_at == "2026-09-05T07:04:10.000Z"


def test_candidate_prefers_the_human_openable_permalink():
    """`url` points at the origin instance; `uri` is the ActivityPub id.

    The demo opens this link in a browser, so it must be the readable one.
    """
    assert MastodonProvider()._to_candidate(STATUS).post_url == "https://pixelfed.social/p/someone/123"


def test_candidate_falls_back_to_uri():
    status = {**STATUS, "url": None}
    assert MastodonProvider()._to_candidate(status).post_url == STATUS["uri"]


def test_status_without_images_is_dropped():
    status = {**STATUS, "media_attachments": [{"type": "video", "url": "https://x/v.mp4"}]}
    assert MastodonProvider()._to_candidate(status) is None


def test_html_is_stripped_for_the_bundle():
    assert _strip_html("<p>Hello <br/>world</p>") == "Hello \nworld"
    assert _strip_html("<p>a</p><p>b</p>") == "a\n\nb"
    assert _strip_html("caf&eacute; &amp; bar &lt;3") == "caf&eacute; & bar <3"


def test_account_queries_are_detected():
    is_account = MastodonProvider._is_account_query
    assert is_account("@user@instance.social")
    assert is_account("@user")
    assert not is_account("portrait")
    assert not is_account("#portrait")
    assert not is_account("two words")


def test_empty_hashtag_rejected():
    with pytest.raises(ValueError, match="empty hashtag"):
        MastodonProvider()._tag_timeline("#", SearchTrail(), 5)


def test_provider_is_always_available():
    """No credentials required - that is the entire point of this provider."""
    assert MastodonProvider().available() is True


def test_instance_url_is_normalized():
    assert MastodonProvider("https://example.social/").instance == "https://example.social"
