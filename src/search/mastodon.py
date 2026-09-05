"""Mastodon public-API search provider.

The default provider, and the reason stage 2 works at all. Verified in
docs/FINDINGS.md F-3: no API key, no quota, no anti-bot, returning genuine
social media posts with real permalinks, authors, timestamps and directly
downloadable images - federated across instances rather than one silo.

Two query forms:

  * ``#tag`` or a bare word  - the public hashtag timeline. Discovery: we ask
    what is currently posted under a tag and get whatever is there.
  * ``@user@instance``       - that account's public posts.

Why choosing a query is not "hardcoding the result": picking a *query* is what
every search does - a reverse image search picks one too, it is just implicit.
What must not be pre-picked is the **result**. The candidate set here is fetched
live and changes minute to minute, and which candidate (if any) matches is
decided by the face encoder's cosine score, recorded either way. Point this at a
tag full of other people and it correctly finds nothing.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx

from .base import Candidate, SearchTrail

log = logging.getLogger(__name__)

USER_AGENT = "faceanchor/0.1 (HH Goa 2026 Task 3; +https://github.com/Sai03SkAr/HHGoa-Task-3)"

# Mastodon caps page size at 40 for these endpoints.
MAX_LIMIT = 40


def _strip_html(html: str) -> str:
    """Post content arrives as HTML; the evidence bundle wants plain text."""
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"</p>\s*<p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    # Only the handful of entities Mastodon actually emits.
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                         ("&quot;", '"'), ("&#39;", "'"), ("&apos;", "'")):
        text = text.replace(entity, char)
    return text.strip()


class MastodonProvider:
    """Searches a Mastodon instance's public API."""

    def __init__(self, instance: str = "https://mastodon.social", timeout: float = 20.0) -> None:
        self.instance = instance.rstrip("/")
        self.timeout = timeout
        # The instance is part of the name so a ladder spanning several of them
        # reads unambiguously - both in the log and in the hashed search trail,
        # where "which server answered" is part of the evidence.
        host = self.instance.split("://", 1)[-1]
        self.name = f"mastodon:{host}"

    def available(self) -> bool:
        # No credentials required, so this provider is always worth trying.
        return True

    # --- HTTP ------------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any], trail: SearchTrail) -> Any:
        url = f"{self.instance}{path}"
        cached = trail.cached(self.name, "GET", url, params)
        if cached is not None:
            trail.record(provider=self.name, method="GET", url=url, params=params,
                         status=200, body=cached, duration_ms=0, from_cache=True)
            return json.loads(cached)

        started = time.perf_counter()
        try:
            response = httpx.get(url, params=params, timeout=self.timeout,
                                 headers={"User-Agent": USER_AGENT},
                                 follow_redirects=True)
            body = response.content
            status = response.status_code
            error = "" if response.is_success else response.reason_phrase
        except httpx.HTTPError as exc:
            trail.record(provider=self.name, method="GET", url=url, params=params,
                         status=0, body=b"", duration_ms=int((time.perf_counter() - started) * 1000),
                         error=str(exc))
            raise

        duration_ms = int((time.perf_counter() - started) * 1000)
        trail.record(provider=self.name, method="GET", url=url, params=params,
                     status=status, body=body, duration_ms=duration_ms, error=error)

        if not 200 <= status < 300:
            raise httpx.HTTPStatusError(
                f"{self.instance} returned {status} for {path}",
                request=response.request, response=response,
            )
        trail.store_cache(self.name, "GET", url, params, body)
        return json.loads(body)

    # --- query parsing ---------------------------------------------------

    @staticmethod
    def _is_account_query(query: str) -> bool:
        return query.startswith("@") and query.count("@") >= 1 and " " not in query

    # --- search ----------------------------------------------------------

    def search(self, query: str, trail: SearchTrail, limit: int = MAX_LIMIT) -> list[Candidate]:
        limit = max(1, min(limit, MAX_LIMIT))
        if self._is_account_query(query):
            statuses = self._account_statuses(query, trail, limit)
        else:
            statuses = self._tag_timeline(query, trail, limit)
        return [c for c in (self._to_candidate(s) for s in statuses) if c is not None]

    def _tag_timeline(self, query: str, trail: SearchTrail, limit: int) -> list[dict]:
        tag = query.lstrip("#").strip()
        if not tag:
            raise ValueError("empty hashtag query")
        return self._get(
            f"/api/v1/timelines/tag/{tag}",
            # only_media filters out text-only posts, which can never match a
            # face and would otherwise fill the page.
            {"limit": limit, "only_media": "true"},
            trail,
        )

    def _account_statuses(self, handle: str, trail: SearchTrail, limit: int) -> list[dict]:
        """Resolve @user@instance to an id, then fetch their public posts."""
        found = self._get("/api/v1/accounts/lookup", {"acct": handle.lstrip("@")}, trail)
        account_id = found["id"]
        return self._get(
            f"/api/v1/accounts/{account_id}/statuses",
            {"limit": limit, "only_media": "true", "exclude_replies": "true"},
            trail,
        )

    def _to_candidate(self, status: dict) -> Candidate | None:
        images = [
            m["url"] for m in status.get("media_attachments", [])
            if m.get("type") == "image" and m.get("url")
        ]
        if not images:
            return None
        account = status.get("account") or {}
        return Candidate(
            # `url` is the canonical permalink and may point at the origin
            # instance (e.g. a pixelfed post federated in); `uri` is the
            # ActivityPub id. Prefer the human-openable one for the demo.
            post_url=status.get("url") or status.get("uri", ""),
            platform="mastodon",
            author=account.get("acct", ""),
            images=images,
            posted_at=status.get("created_at", ""),
            text=_strip_html(status.get("content", ""))[:500],
            provider=self.name,
        )
