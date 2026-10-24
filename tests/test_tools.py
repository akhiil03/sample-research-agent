from __future__ import annotations

import pytest

import research_agent.tools as tools


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://127.1.2.3/",
        "http://10.0.0.5/",
        "http://192.168.1.10/",
        "http://172.16.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[fd00::1]/",
        "file:///etc/passwd",
        "ftp://example.com/file",
        "http://localhost/",
        "http://printer.local/",
        "http://metadata.google.internal/computeMetadata/v1/",
    ],
)
def test_assert_public_url_rejects_private_and_internal_targets(url):
    with pytest.raises(tools.ToolError):
        tools.assert_public_url(url)


def test_assert_public_url_accepts_public_ip_literal():
    assert tools.assert_public_url("https://93.184.216.34/page") == "https://93.184.216.34/page"


def test_assert_public_url_accepts_public_dns(monkeypatch):
    monkeypatch.setattr(tools, "_resolve_host", lambda host: ["93.184.216.34"])
    assert tools.assert_public_url("example.com/page") == "https://example.com/page"


def test_assert_public_url_rejects_public_dns_with_private_answer(monkeypatch):
    monkeypatch.setattr(tools, "_resolve_host", lambda host: ["93.184.216.34", "10.1.2.3"])
    with pytest.raises(tools.UnsafeUrlError, match="non-public"):
        tools.assert_public_url("https://looks-public.example/page")


def test_fetch_page_returns_error_json_for_ssrf_targets():
    payload = tools.fetch_page.invoke({"url": "http://169.254.169.254/latest/meta-data/"})
    assert '"tool": "fetch_page"' in payload
    assert "error" in payload


def test_fetch_page_extracts_text_and_title(monkeypatch):
    html = (
        "<html><head><title>Test Article</title></head><body><article>"
        "<p>Hello from the test page.</p></article></body></html>"
    )
    monkeypatch.setattr(tools, "_fetch_html", lambda url, **kwargs: (html, "https://example.com/a"))
    payload = tools.fetch_page.invoke({"url": "https://example.com/a"})
    assert '"title": "Test Article"' in payload
    assert "Hello from the test page." in payload
    assert '"truncated": false' in payload


def test_fetch_page_truncates_long_text(monkeypatch):
    html = "<html><body><article>" + ("word " * 600) + "</article></body></html>"
    monkeypatch.setattr(tools, "_fetch_html", lambda url, **kwargs: (html, "https://example.com/a"))
    payload = tools.fetch_page.invoke({"url": "https://example.com/a", "max_chars": 1000})
    assert '"truncated": true' in payload
    assert len(payload) < 3000


def test_fetch_page_reports_fetch_errors(monkeypatch):
    def boom(url, **kwargs):
        raise tools.FetchError("HTTP 404 for https://example.com/missing")

    monkeypatch.setattr(tools, "_fetch_html", boom)
    payload = tools.fetch_page.invoke({"url": "https://example.com/missing"})
    assert "HTTP 404" in payload
    assert '"tool": "fetch_page"' in payload


def test_extract_text_falls_back_when_trafilatura_returns_nothing(monkeypatch):
    monkeypatch.setattr(tools.trafilatura, "extract", lambda *args, **kwargs: None)
    html = "<html><script>bad()</script><style>.x{}</style><p>Visible text</p></html>"
    text = tools._extract_text(html)
    assert text == "Visible text"


def test_web_search_shapes_results(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_ddgs_search",
        lambda query, limit: [
            {"title": "A title", "href": "https://example.com/a", "body": "A snippet"},
            {"title": "No link", "body": "dropped"},
        ],
    )
    payload = tools.web_search.invoke({"query": "  example   query ", "max_results": 3})
    assert '"url": "https://example.com/a"' in payload
    assert "No link" not in payload


def test_web_search_rejects_empty_query():
    payload = tools.web_search.invoke({"query": "   "})
    assert '"tool": "web_search"' in payload


def test_web_search_reports_backend_failure(monkeypatch):
    monkeypatch.setattr(tools.time, "sleep", lambda seconds: None)

    def boom(query, limit):
        raise RuntimeError("backend down")

    monkeypatch.setattr(tools, "_ddgs_search", boom)
    payload = tools.web_search.invoke({"query": "anything"})
    assert "backend down" in payload
    assert '"error"' in payload


def test_collect_sources_dedupes_and_prefers_page_metadata():
    from langchain_core.messages import ToolMessage

    messages = [
        ToolMessage(
            name="web_search",
            content=('[{"title": "Search title", "url": "https://example.com/a", "snippet": "s"}]'),
            tool_call_id="1",
        ),
        ToolMessage(
            name="fetch_page",
            content=('{"title": "Page title", "url": "https://example.com/a", "text": "body"}'),
            tool_call_id="2",
        ),
    ]
    sources = tools.collect_sources(messages)
    assert len(sources) == 1
    assert sources[0]["title"] == "Page title"
    assert sources[0]["kind"] == "page"


def test_collect_sources_ignores_errors_and_bad_json():
    from langchain_core.messages import ToolMessage

    messages = [
        ToolMessage(name="fetch_page", content='{"error": "nope"}', tool_call_id="1"),
        ToolMessage(name="web_search", content="not json", tool_call_id="2"),
    ]
    assert tools.collect_sources(messages) == []
