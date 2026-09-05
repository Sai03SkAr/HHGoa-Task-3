"""Search provider interface, candidates, and the search trail.

Stage 2. The contract every provider honours is deliberately narrow:

    a provider returns CANDIDATES, never answers.

Nothing downstream trusts a provider's opinion that two images show the same
person. The face encoder re-embeds each candidate image and the cosine score
decides, which is what makes the search step verifiable rather than merely
believed - see docs/DECISIONS.md D-003.

The other half of this module is the **search trail**: every HTTP request, its
raw response body, the status code and a timestamp, written to disk and hashed
into the evidence bundle. That is the artefact that answers requirement 2's
"not a hardcoded/pre-picked result" - a reader can replay exactly what was
asked and what came back, and the recording can scroll it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)


def utc_now() -> str:
    """ISO-8601 UTC, second precision. Used everywhere a timestamp is recorded."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Candidate:
    """One post a provider thinks is worth looking at.

    `images` are URLs, not bytes: downloading is the scrape stage's job, and
    keeping this record small keeps the search trail readable.
    """

    post_url: str
    platform: str
    author: str
    images: list[str]
    posted_at: str = ""
    text: str = ""
    provider: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "post_url": self.post_url,
            "platform": self.platform,
            "author": self.author,
            "images": list(self.images),
            "posted_at": self.posted_at,
            "text": self.text,
            "provider": self.provider,
        }


@dataclass
class TrailEntry:
    """One request/response pair, recorded for the evidence bundle."""

    ts: str
    provider: str
    method: str
    url: str
    params: dict[str, Any]
    status: int
    response_sha256: str
    response_bytes: int
    duration_ms: int
    error: str = ""
    # Where the raw body was written, relative to the run directory.
    body_path: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "provider": self.provider,
            "method": self.method,
            "url": self.url,
            "params": self.params,
            "status": self.status,
            "response_sha256": self.response_sha256,
            "response_bytes": self.response_bytes,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "body_path": self.body_path,
        }


class SearchTrail:
    """Records every provider call, and caches responses on disk.

    The cache is keyed by a hash of (provider, method, url, params). It exists
    for one specific reason: a re-run during a screen recording must not burn
    an API quota or trip a rate limit at the worst possible moment. It is
    explicitly recorded in each entry whether a response was served from cache,
    so the trail never misrepresents what happened on the wire.
    """

    def __init__(self, run_dir: Path | None = None, cache_dir: Path | None = None) -> None:
        self.entries: list[TrailEntry] = []
        self.run_dir = Path(run_dir) if run_dir else None
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.run_dir:
            (self.run_dir / "search_trail").mkdir(parents=True, exist_ok=True)
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(provider: str, method: str, url: str, params: dict) -> str:
        blob = json.dumps(
            {"p": provider, "m": method, "u": url, "q": params}, sort_keys=True
        ).encode()
        return hashlib.sha256(blob).hexdigest()[:32]

    def cached(self, provider: str, method: str, url: str, params: dict) -> bytes | None:
        if not self.cache_dir:
            return None
        path = self.cache_dir / f"{self._key(provider, method, url, params)}.json"
        if path.exists():
            log.debug("cache hit for %s %s", provider, url)
            return path.read_bytes()
        return None

    def store_cache(self, provider: str, method: str, url: str, params: dict, body: bytes) -> None:
        if not self.cache_dir:
            return
        (self.cache_dir / f"{self._key(provider, method, url, params)}.json").write_bytes(body)

    def record(self, *, provider: str, method: str, url: str, params: dict,
               status: int, body: bytes, duration_ms: int, error: str = "",
               from_cache: bool = False) -> TrailEntry:
        """Log one call and persist its raw body."""
        entry = TrailEntry(
            ts=utc_now(),
            provider=provider,
            method=method,
            url=url,
            params=dict(params),
            status=status,
            response_sha256=hashlib.sha256(body).hexdigest(),
            response_bytes=len(body),
            duration_ms=duration_ms,
            error=error,
        )
        if from_cache:
            # Never let the trail imply a live call that did not happen.
            entry.params = {**entry.params, "_served_from_cache": True}
        if self.run_dir:
            index = len(self.entries)
            name = f"{index:02d}_{provider}.json"
            (self.run_dir / "search_trail" / name).write_bytes(body)
            entry.body_path = f"search_trail/{name}"
        self.entries.append(entry)
        return entry

    def to_json(self) -> list[dict[str, Any]]:
        return [e.to_json() for e in self.entries]


@runtime_checkable
class SearchProvider(Protocol):
    """A source of candidate posts."""

    name: str

    def available(self) -> bool:
        """Whether this provider is configured well enough to try."""
        ...

    def search(self, query: str, trail: SearchTrail, limit: int = 40) -> list[Candidate]:
        """Return candidates for `query`, recording every call in `trail`."""
        ...


class ProviderUnavailable(Exception):
    """Raised when a provider cannot run - missing key, unreachable, etc."""


@dataclass
class LadderResult:
    """Outcome of running the provider ladder."""

    candidates: list[Candidate]
    provider_used: str
    providers_tried: list[str] = field(default_factory=list)
    # Why each skipped/failed provider did not produce the answer. Printed on
    # screen during the demo: a visible fall-through is a feature.
    notes: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "provider_used": self.provider_used,
            "providers_tried": list(self.providers_tried),
            "notes": dict(self.notes),
            "candidate_count": len(self.candidates),
        }


def run_ladder(providers: list[SearchProvider], query: str, trail: SearchTrail,
               limit: int = 40) -> LadderResult:
    """Try each provider in order until one yields candidates.

    A provider that is unconfigured, errors, or simply returns nothing is
    recorded and the ladder moves on. Falling through is normal operation, not
    an error path - live demos die when one API rate-limits, and a ladder that
    visibly falls through on screen is the mitigation.
    """
    tried: list[str] = []
    notes: dict[str, str] = {}

    for provider in providers:
        if not provider.available():
            notes[provider.name] = "not configured"
            log.info("search: %s unavailable, skipping", provider.name)
            continue
        tried.append(provider.name)
        try:
            candidates = provider.search(query, trail, limit=limit)
        except Exception as exc:  # noqa: BLE001 - a bad provider must not end the run
            notes[provider.name] = f"error: {exc}"
            log.warning("search: %s failed (%s), falling through", provider.name, exc)
            continue
        if candidates:
            log.info("search: %s returned %d candidates", provider.name, len(candidates))
            return LadderResult(candidates, provider.name, tried, notes)
        notes[provider.name] = "no candidates"
        log.info("search: %s returned nothing, falling through", provider.name)

    return LadderResult([], "", tried, notes)
