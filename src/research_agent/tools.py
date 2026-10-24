"""Network tools used by the research graph, with offline stand-ins for demos and tests."""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import time
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from ddgs import DDGS
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, tool

from .state import Source

LOGGER = logging.getLogger(__name__)

USER_AGENT = (
    "sample-research-agent/0.1 (+https://github.com/akhiil03/sample-research-agent) python-httpx"
)
MAX_PAGE_BYTES = 2_000_000
MAX_REDIRECTS = 3
BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
    "metadata.goog",
}
ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class ToolError(RuntimeError):
    """Base error for tool failures that are safe to report back to the model."""


class UnsafeUrlError(ToolError):
    """Raised when a URL would reach a non-public network destination."""


class FetchError(ToolError):
    """Raised when a page cannot be fetched or is not readable content."""


class PageTooLarge(FetchError):
    """Raised when a response exceeds the configured byte budget."""


def _is_public_ip(raw_ip: str) -> bool:
    try:
        address = ipaddress.ip_address(raw_ip)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global


def _resolve_host(hostname: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise FetchError(f"could not resolve host {hostname!r}") from exc
    return sorted({info[4][0] for info in infos})


def assert_public_url(url: str) -> str:
    """Return a normalized URL, or raise if it targets a private/reserved address."""
    raw = (url or "").strip()
    if not raw:
        raise UnsafeUrlError("URL is empty")
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"unsupported URL scheme {parsed.scheme!r}")
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise UnsafeUrlError("URL has no hostname")
    if hostname in BLOCKED_HOSTNAMES or hostname.endswith((".local", ".internal", ".localhost")):
        raise UnsafeUrlError(f"hostname {hostname!r} is not allowed")
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if not _is_public_ip(str(literal_ip)):
            raise UnsafeUrlError(f"address {hostname} is not public")
        return parsed.geturl()
    resolved = _resolve_host(hostname)
    if not resolved:
        raise FetchError(f"could not resolve host {hostname!r}")
    blocked = [address for address in resolved if not _is_public_ip(address)]
    if blocked:
        raise UnsafeUrlError(f"hostname {hostname!r} resolves to non-public address {blocked[0]}")
    return parsed.geturl()


def _charset_from_headers(headers: httpx.Headers) -> str:
    match = re.search(r"charset=([\w.-]+)", headers.get("content-type", ""), re.IGNORECASE)
    return match.group(1) if match else "utf-8"


def _fetch_html(url: str, *, max_bytes: int = MAX_PAGE_BYTES) -> tuple[str, str]:
    """Fetch a public HTML page, following redirects only after re-validating each hop."""
    current = assert_public_url(url)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
    }
    timeout = httpx.Timeout(10.0, connect=5.0)
    with httpx.Client(timeout=timeout, follow_redirects=False, headers=headers) as client:
        for _ in range(MAX_REDIRECTS + 1):
            with client.stream("GET", current) as response:
                if response.status_code in REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        raise FetchError(f"redirect from {current} had no Location header")
                    current = assert_public_url(urljoin(current, location))
                    continue
                if response.status_code >= 400:
                    raise FetchError(f"HTTP {response.status_code} for {current}")
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                if content_type and content_type.lower() not in ALLOWED_CONTENT_TYPES:
                    raise FetchError(f"unsupported content type {content_type!r}")
                declared_length = response.headers.get("content-length")
                if (
                    declared_length
                    and declared_length.isdigit()
                    and int(declared_length) > max_bytes
                ):
                    raise PageTooLarge(f"page is {declared_length} bytes, limit is {max_bytes}")
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise PageTooLarge(f"page exceeds {max_bytes} bytes")
                    chunks.append(chunk)
                charset = _charset_from_headers(response.headers)
                try:
                    html = b"".join(chunks).decode(charset, errors="replace")
                except LookupError:
                    html = b"".join(chunks).decode("utf-8", errors="replace")
                return html, str(response.url)
    raise FetchError(f"too many redirects while fetching {url}")


def _extract_text(html: str) -> str:
    try:
        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
    except Exception:  # noqa: BLE001 - extraction must never crash a run
        LOGGER.warning("trafilatura extraction failed", exc_info=True)
        extracted = None
    if not extracted:
        extracted = _strip_tags(html)
    return _collapse_whitespace(extracted)


def _strip_tags(html: str) -> str:
    without_scripts = re.sub(
        r"<(script|style|noscript)\b.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL
    )
    return unescape(re.sub(r"<[^>]+>", " ", without_scripts))


def _collapse_whitespace(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _page_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    return _collapse_whitespace(unescape(match.group(1))) if match else ""


def _ddgs_search(query: str, max_results: int) -> list[dict[str, str]]:
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


def _search_with_retries(query: str, max_results: int, attempts: int = 3) -> list[dict[str, str]]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _ddgs_search(query, max_results)
        except Exception as exc:  # noqa: BLE001 - backend failures are transient
            last_error = exc
            LOGGER.warning("web_search attempt %s/%s failed: %s", attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(1.5 * attempt)
    raise ToolError(f"search backend failed: {last_error}")


def _error_payload(tool_name: str, exc: Exception) -> str:
    return json.dumps({"tool": tool_name, "error": str(exc)}, ensure_ascii=False)


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the public web and return a JSON list of {title, url, snippet} results."""
    query = " ".join((query or "").split())
    if not query:
        return _error_payload("web_search", ToolError("query must not be empty"))
    limit = max(1, min(int(max_results or 5), 8))
    try:
        rows = _search_with_retries(query, limit)
    except Exception as exc:  # noqa: BLE001 - reported back to the model
        return _error_payload("web_search", exc)
    results = [
        {
            "title": (row.get("title") or "").strip(),
            "url": (row.get("href") or row.get("url") or "").strip(),
            "snippet": " ".join((row.get("body") or "").split())[:400],
        }
        for row in rows
        if row.get("href") or row.get("url")
    ]
    return json.dumps(results, ensure_ascii=False)


@tool
def fetch_page(url: str, max_chars: int = 6000) -> str:
    """Read the main text of a public web page. Returns JSON with title, url, and text."""
    limit = max(1000, min(int(max_chars or 6000), 12000))
    try:
        html, final_url = _fetch_html(url)
        text = _extract_text(html)
        if not text:
            raise FetchError(f"no readable text found at {final_url}")
        title = _page_title(html) or urlparse(final_url).netloc
        truncated = len(text) > limit
        return json.dumps(
            {
                "url": final_url,
                "title": title,
                "text": text[:limit],
                "truncated": truncated,
            },
            ensure_ascii=False,
        )
    except Exception as exc:  # noqa: BLE001 - reported back to the model
        return _error_payload("fetch_page", exc)


DEFAULT_TOOLS: list[BaseTool] = [web_search, fetch_page]


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content)


def collect_sources(messages: list[Any]) -> list[Source]:
    """Derive a deduplicated, order-stable source list from tool messages."""
    ordered: list[Source] = []
    index: dict[str, int] = {}
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        name = getattr(message, "name", "") or ""
        try:
            payload = json.loads(_message_text(message.content))
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and "error" in payload:
            continue
        if name == "web_search" and isinstance(payload, list):
            for row in payload:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or "").strip()
                if not url:
                    continue
                source: Source = {
                    "title": str(row.get("title") or url),
                    "url": url,
                    "snippet": str(row.get("snippet") or "")[:400],
                    "kind": "search",
                }
                _upsert_source(ordered, index, source)
        elif name == "fetch_page" and isinstance(payload, dict):
            url = str(payload.get("url") or "").strip()
            if not url:
                continue
            source = {
                "title": str(payload.get("title") or url),
                "url": url,
                "snippet": str(payload.get("text") or "")[:300],
                "kind": "page",
            }
            _upsert_source(ordered, index, source)
    return ordered


def _upsert_source(ordered: list[Source], index: dict[str, int], source: Source) -> None:
    url = source["url"]
    if url not in index:
        index[url] = len(ordered)
        ordered.append(source)
        return
    existing = ordered[index[url]]
    if source["kind"] == "page" and existing["kind"] == "search":
        ordered[index[url]] = source
    elif not existing["title"] or existing["title"] == existing["url"]:
        existing["title"] = source["title"]


def _offline_search_results(query: str) -> list[dict[str, str]]:
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-") or "topic"
    return [
        {
            "title": f"{query}: overview and current state",
            "url": f"https://example.com/{slug}/overview",
            "snippet": (
                f"A high-level overview of {query}, including recent developments and "
                "the main open questions researchers are tracking."
            ),
        },
        {
            "title": f"A skeptical look at {query}",
            "url": f"https://example.org/{slug}/critique",
            "snippet": (
                f"An analysis of the limits, failure modes, and contested claims around "
                f"{query}, with pointers to primary sources."
            ),
        },
    ]


@tool("web_search")
def offline_web_search(query: str, max_results: int = 5) -> str:
    """Search the public web and return a JSON list of {title, url, snippet} results."""
    limit = max(1, min(int(max_results or 5), 8))
    return json.dumps(_offline_search_results(query)[:limit], ensure_ascii=False)


@tool("fetch_page")
def offline_fetch_page(url: str, max_chars: int = 6000) -> str:
    """Read the main text of a public web page. Returns JSON with title, url, and text."""
    limit = max(1000, min(int(max_chars or 6000), 12000))
    text = (
        "This is an offline placeholder page used for demos and tests. It stands in for "
        "the real article so the full LangGraph pipeline can run without network access. "
        "A real run would contain the article body, quotations, and publication details. "
    ) * 4
    return json.dumps(
        {
            "url": url,
            "title": url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title(),
            "text": text[:limit],
            "truncated": len(text) > limit,
        },
        ensure_ascii=False,
    )


OFFLINE_TOOLS: list[BaseTool] = [offline_web_search, offline_fetch_page]
