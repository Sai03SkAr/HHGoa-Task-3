"""Downloading candidate images and post pages.

Everything here is fetched from the open internet, so everything here is
treated as hostile: bounded size, bounded time, and content checked by its
bytes rather than by its URL or its Content-Type header.

That last point is not paranoia. A failed download lands as an HTML error page
that keeps its `.jpg` name and a 200 status - the exact failure that cost real
time against Wikimedia during the spike (docs/FINDINGS.md F-7). Sniffing magic
bytes is the only reliable check.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "faceanchor/0.1 (HH Goa 2026 Task 3; +https://github.com/Sai03SkAr/HHGoa-Task-3)"

# A social media photo that does not fit in 25 MB is not a photo we need.
MAX_BYTES = 25 * 1024 * 1024
TIMEOUT = 30.0

# Magic numbers for the formats OpenCV can actually decode.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
)


class FetchError(Exception):
    pass


def sniff_image(data: bytes) -> str | None:
    """Identify an image by its leading bytes. None if it is not one."""
    for magic, kind in _MAGIC:
        if data.startswith(magic):
            return kind
    # WEBP and HEIF carry a container signature at a fixed offset.
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "heif"
    return None


@dataclass
class Fetched:
    """Bytes retrieved from a URL, with the provenance evidence needs."""

    url: str
    status: int
    content: bytes
    content_type: str = ""

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.content)
        return path


def fetch(url: str, *, max_bytes: int = MAX_BYTES, timeout: float = TIMEOUT) -> Fetched:
    """GET a URL with a size cap, streaming so an oversized body is cut early."""
    try:
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": USER_AGENT}) as response:
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise FetchError(
                        f"{url} exceeds the {max_bytes // 1024 // 1024} MB cap"
                    )
                chunks.append(chunk)
            return Fetched(
                url=url,
                status=response.status_code,
                content=b"".join(chunks),
                content_type=response.headers.get("content-type", ""),
            )
    except httpx.HTTPError as exc:
        raise FetchError(f"could not fetch {url}: {exc}") from exc


def fetch_image(url: str, **kwargs: Any) -> Fetched:
    """Fetch a URL and insist the bytes really are a decodable image."""
    got = fetch(url, **kwargs)
    if not 200 <= got.status < 300:
        raise FetchError(f"{url} returned HTTP {got.status}")
    kind = sniff_image(got.content)
    if kind is None:
        head = got.content[:48]
        raise FetchError(
            f"{url} did not return an image "
            f"(content-type said {got.content_type!r}, first bytes {head!r}). "
            "A failed download often arrives as an HTML error page with a 200 status."
        )
    log.debug("fetched %s (%s, %d bytes)", url, kind, len(got.content))
    return got


# --- OpenGraph metadata ----------------------------------------------------

_META_RE = re.compile(
    r"<meta\s+[^>]*?(?:property|name)\s*=\s*[\"']([^\"']+)[\"'][^>]*?content\s*=\s*[\"']([^\"']*)[\"']",
    re.IGNORECASE | re.DOTALL,
)
_META_RE_REVERSED = re.compile(
    r"<meta\s+[^>]*?content\s*=\s*[\"']([^\"']*)[\"'][^>]*?(?:property|name)\s*=\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE | re.DOTALL,
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


@dataclass
class PageMeta:
    """OpenGraph metadata scraped from a post page."""

    url: str
    title: str = ""
    og_image: str = ""
    og_title: str = ""
    og_description: str = ""
    author: str = ""
    published: str = ""
    raw: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "og_image": self.og_image,
            "og_title": self.og_title,
            "og_description": self.og_description,
            "author": self.author,
            "published": self.published,
        }


def parse_meta(html: str, url: str = "") -> PageMeta:
    """Extract OpenGraph tags.

    Attribute order is not fixed in real HTML, so both orderings are matched -
    `property` before `content` and the reverse.
    """
    tags: dict[str, str] = {}
    for key, value in _META_RE.findall(html):
        tags.setdefault(key.lower(), value)
    for value, key in _META_RE_REVERSED.findall(html):
        tags.setdefault(key.lower(), value)

    title_match = _TITLE_RE.search(html)
    return PageMeta(
        url=url,
        title=(title_match.group(1).strip() if title_match else ""),
        og_image=tags.get("og:image", ""),
        og_title=tags.get("og:title", ""),
        og_description=tags.get("og:description", ""),
        author=tags.get("profile:username") or tags.get("author", ""),
        published=tags.get("article:published_time", ""),
        raw=tags,
    )


def fetch_page(url: str, *, timeout: float = TIMEOUT) -> tuple[Fetched, PageMeta]:
    """Fetch a post page and parse its OpenGraph metadata.

    The raw HTML is returned alongside, because its hash goes into the evidence
    bundle - it is the record of what the page said at anchor time.
    """
    got = fetch(url, timeout=timeout)
    html = got.content.decode("utf-8", errors="replace")
    return got, parse_meta(html, url)
