"""Hermetic tests for the Gutenberg adapter's upstream fetch tiers.

Covers the base-URL override contract (ADAPTER_GUTENBERG_CACHE_BASE /
ADAPTER_GUTENDEX_API_BASE, issue #581), the EPUB → plain-text → fall-through
tier flow, and boilerplate/chapter handling against deterministic fixtures
mirroring the test-site digital twin endpoints.
"""

from io import BytesIO
from zipfile import ZipFile

import pytest
from scraper.adapters import gutenberg

# ── Fixtures mirroring test_site's twin payloads ────────────────────


def _fixture_epub_bytes() -> bytes:
    buffer = BytesIO()
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0">'
        "<metadata>"
        "<dc:title>Alice's Adventures in Wonderland</dc:title>"
        "<dc:creator>Lewis Carroll</dc:creator>"
        "<dc:language>en</dc:language>"
        "</metadata>"
        "</package>"
    )
    chapter = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        "<h1>Chapter I \u2014 Down the Rabbit-Hole</h1>"
        "<p>Alice was beginning to get very tired of sitting by her sister "
        "on the bank, and of having nothing to do.</p>"
        "</body></html>"
    )
    with ZipFile(buffer, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/chapter1.xhtml", chapter)
    return buffer.getvalue()


_PLAIN_TEXT = (
    "The Project Gutenberg eBook of Alice's Adventures in Wonderland\n"
    "\n"
    "*** START OF THE PROJECT GUTENBERG EBOOK ALICE'S ADVENTURES IN WONDERLAND ***\n"
    "\n"
    "CHAPTER I.\n"
    "Down the Rabbit-Hole\n"
    "\n"
    "Alice was beginning to get very tired of sitting by her sister on the bank.\n"
    "\n"
    "*** END OF THE PROJECT GUTENBERG EBOOK ALICE'S ADVENTURES IN WONDERLAND ***\n"
)


_GUTENDEX_PAYLOAD = {
    "id": 11,
    "title": "Alice's Adventures in Wonderland",
    "authors": [{"name": "Carroll, Lewis", "birth_year": 1832, "death_year": 1898}],
    "languages": ["en"],
    "subjects": ["Fantasy fiction"],
    "download_count": 51000,
}


class _FakeResponse:
    def __init__(self, status_code=200, content=b"", text="", json_data=None):
        self.status_code = status_code
        self.content = content
        self.text = text
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError("no JSON body configured")
        return self._json_data


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient; maps URL → response."""

    requests: list[str] = []

    def __init__(self, responses: dict[str, _FakeResponse], **kwargs):
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url):
        type(self).requests.append(url)
        for pattern, response in self._responses.items():
            if pattern in url:
                return response
        return _FakeResponse(status_code=404, content=b"", text="")


@pytest.fixture(autouse=True)
def _clean_base_env(monkeypatch):
    monkeypatch.delenv("ADAPTER_GUTENBERG_CACHE_BASE", raising=False)
    monkeypatch.delenv("ADAPTER_GUTENDEX_API_BASE", raising=False)


# ── Base-URL override contract (#581) ───────────────────────────────


def test_default_urls_target_real_internet():
    assert gutenberg._epub_url("11") == (
        "https://www.gutenberg.org/cache/epub/11/pg11-images-3.epub"
    )
    assert gutenberg._txt_url("11") == (
        "https://www.gutenberg.org/cache/epub/11/pg11.txt"
    )


def test_cache_base_override_rewrites_download_urls(monkeypatch):
    monkeypatch.setenv("ADAPTER_GUTENBERG_CACHE_BASE", "http://test-site:8005")
    assert gutenberg._epub_url("11") == (
        "http://test-site:8005/cache/epub/11/pg11-images-3.epub"
    )
    assert gutenberg._txt_url("11") == ("http://test-site:8005/cache/epub/11/pg11.txt")


def test_trailing_slash_in_override_is_normalized(monkeypatch):
    monkeypatch.setenv("ADAPTER_GUTENBERG_CACHE_BASE", "http://test-site:8005/")
    assert "/cache/epub//11/" not in gutenberg._epub_url("11")


def test_empty_override_means_unset(monkeypatch):
    # Compose interpolation (${VAR:-}) yields an empty string, which must
    # behave exactly like an unset variable.
    monkeypatch.setenv("ADAPTER_GUTENBERG_CACHE_BASE", "")
    assert gutenberg._cache_base() == ""
    assert gutenberg._epub_url("11").startswith("https://www.gutenberg.org/")


def test_gutendex_base_override(monkeypatch):
    monkeypatch.setenv("ADAPTER_GUTENDEX_API_BASE", "http://test-site:8005")
    url = gutenberg._gutendex_base() or "https://gutendex.com"
    assert f"{url}/books/11" == "http://test-site:8005/books/11"


# ── Tier flow: EPUB success ─────────────────────────────────────────


async def test_fetch_epub_parses_fixture_archive(monkeypatch):
    epub = _fixture_epub_bytes()

    class Client(_FakeAsyncClient):
        def __init__(self, **kwargs):
            super().__init__({}, **kwargs)
            self._responses = {"/cache/epub/": _FakeResponse(200, content=epub)}

    monkeypatch.setattr(gutenberg.httpx, "AsyncClient", Client)
    data = await gutenberg._fetch_epub("11")
    assert data == epub


async def test_scrape_prefers_epub_tier_and_emits_metadata(monkeypatch):
    epub = _fixture_epub_bytes()

    class Client(_FakeAsyncClient):
        def __init__(self, **kwargs):
            super().__init__(
                {
                    "-images-3.epub": _FakeResponse(200, content=epub),
                    "/books/": _FakeResponse(json_data=_GUTENDEX_PAYLOAD),
                },
                **kwargs,
            )

    monkeypatch.setattr(gutenberg.httpx, "AsyncClient", Client)
    adapter = gutenberg.GutenbergAdapter()
    result = await adapter.scrape(
        "https://www.gutenberg.org/ebooks/11", gutenberg.AdapterContext()
    )

    assert result.success is True
    assert result.source == "gutenberg-epub"
    assert result.markdown.startswith("## Chapter I")
    assert result.metadata["gutenberg_id"] == 11
    assert result.metadata["author"] == "Carroll, Lewis (1832-1898)"
    assert result.metadata["chapters"], "chapter headings should be detected"


# ── Tier flow: degraded EPUB → plain-text fallback (#581 scenario) ──


async def test_degraded_epub_falls_back_to_plain_text(monkeypatch):
    class Client(_FakeAsyncClient):
        def __init__(self, **kwargs):
            super().__init__(
                {
                    "-images-3.epub": _FakeResponse(
                        200,
                        content=b"<html><body>upstream maintenance page</body></html>",
                    ),
                    "pg11.txt": _FakeResponse(200, text=_PLAIN_TEXT),
                    "/books/": _FakeResponse(json_data=_GUTENDEX_PAYLOAD),
                },
                **kwargs,
            )

    monkeypatch.setattr(gutenberg.httpx, "AsyncClient", Client)
    adapter = gutenberg.GutenbergAdapter()
    result = await adapter.scrape(
        "https://www.gutenberg.org/ebooks/11", gutenberg.AdapterContext()
    )

    assert result.success is True
    assert result.source == "gutenberg-plaintext"
    assert "Down the Rabbit-Hole" in result.markdown
    assert "START OF THE PROJECT GUTENBERG" not in result.markdown


async def test_both_tiers_down_raise_adapter_error(monkeypatch):
    class Client(_FakeAsyncClient):
        def __init__(self, **kwargs):
            super().__init__({}, **kwargs)

    monkeypatch.setattr(gutenberg.httpx, "AsyncClient", Client)
    adapter = gutenberg.GutenbergAdapter()
    with pytest.raises(gutenberg.AdapterError):
        await adapter.scrape(
            "https://www.gutenberg.org/ebooks/11", gutenberg.AdapterContext()
        )


# ── Gutendex enrichment is non-fatal ────────────────────────────────


async def test_gutendex_failure_does_not_block_plain_text_tier(monkeypatch):
    class Client(_FakeAsyncClient):
        def __init__(self, **kwargs):
            super().__init__(
                {
                    "pg11.txt": _FakeResponse(200, text=_PLAIN_TEXT),
                },
                **kwargs,
            )

    monkeypatch.setattr(gutenberg.httpx, "AsyncClient", Client)
    meta = await gutenberg._fetch_gutendex_metadata("11")
    assert meta is None

    adapter = gutenberg.GutenbergAdapter()
    result = await adapter.scrape(
        "https://www.gutenberg.org/ebooks/11", gutenberg.AdapterContext()
    )
    assert result.success is True
    assert result.source == "gutenberg-plaintext"


async def test_gutendex_metadata_parsing(monkeypatch):
    class Client(_FakeAsyncClient):
        def __init__(self, **kwargs):
            super().__init__(
                {"/books/": _FakeResponse(json_data=_GUTENDEX_PAYLOAD)},
                **kwargs,
            )

    monkeypatch.setattr(gutenberg.httpx, "AsyncClient", Client)
    meta = await gutenberg._fetch_gutendex_metadata("11")
    assert meta == {
        "title": "Alice's Adventures in Wonderland",
        "author": "Carroll, Lewis (1832-1898)",
        "language": "en",
        "subjects": ["Fantasy fiction"],
        "download_count": 51000,
    }
