"""Hermetic unit tests for the Project Gutenberg adapter (#581).

All network interaction flows through a monkeypatched ``httpx.AsyncClient``
seam (precedent: ``tests/unit/test_github_adapter.py``): the fake client is
an async-context manager that records requested URLs and serves canned
responses for exactly three fixture endpoints —

  * EPUB cache: ``https://www.gutenberg.org/cache/epub/{id}/pg{id}-images-3.epub``
  * txt cache:  ``https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt``
  * gutendex:   ``https://gutendex.com/books/{id}``

Fixtures are built in-test (real EPUB zip via ``zipfile``, PG-boilerplate
plain text, gutendex-shaped JSON) so the whole suite passes with sockets
disabled and zero live gutenberg.org / gutendex.com traffic.

Assertion conventions (per validation contract): the txt-tier chapter title
is assembled as stripped-prefix + first content line, so tests assert on
chapter COUNT, distinctive prose, and boilerplate absence — never on exact
heading strings like ``## CHAPTER I``.

Hardening conventions: every happy-path scrape goes through
:func:`_scrape`, which asserts endpoint containment on the seam it used
(``set(seam.requests) <= allowed fixture endpoints``); error-path tests
call :func:`_assert_seam_contained` directly — hermeticity is enforced for
every test rather than one dedicated containment test. The seam routes
responses OR exception instances; routing is decided with ``isinstance(...,
BaseException)`` plus an exact-type check so an exception CLASS can never
be mistaken for a response object.
"""

import re
import zipfile
from io import BytesIO
from typing import Any

import pytest
from scraper.adapters import gutenberg
from scraper.adapters.base import (
    AdapterContext,
    AdapterError,
    AdapterRegistry,
    AdapterResult,
    SiteAdapter,
)

from common.metrics import METRICS

BOOK_ID = "11"

EBOOKS_URL = "https://www.gutenberg.org/ebooks/11"
FILES_URL = "https://www.gutenberg.org/files/11/"
CACHE_URL = "https://gutenberg.org/cache/epub/11/"
INVALID_ID_URL = "https://www.gutenberg.org/ebooks/notanumber"
NONEXISTENT_URL = "https://www.gutenberg.org/ebooks/99999999"

OPF_TITLE = "Alice's Adventures Under Ground"
OPF_AUTHOR = "Lewis Carroll"

GUTENDEX_TITLE = "Alice's Adventures in Wonderland"
GUTENDEX_AUTHOR_NAME = "Carroll, Lewis"

PROSE_CHAPTER_ONE = "daisy-chain"
PROSE_CHAPTER_TWO = "golden key"


# ── Fake seam (monkeypatched httpx.AsyncClient) ───────────────────


class _FakeResponse:
    """Canned ``httpx.Response`` stand-in serving bytes / JSON."""

    def __init__(
        self,
        status_code: int = 200,
        content: bytes = b"",
        json_data: Any = None,
    ):
        self.status_code = status_code
        self.content = content
        self._json_data = json_data

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        if self._json_data is None:
            raise ValueError("fake response carries no JSON body")
        return self._json_data


class _FixtureSeam:
    """Fake async-context client serving only the gutenberg fixture endpoints.

    Routes are keyed ``"epub"`` / ``"txt"`` / ``"gutendex"``; a route value
    may be a ``_FakeResponse`` or an exception INSTANCE (raised to simulate
    transport failures). Unrouted endpoints answer 404. An exception class
    is deliberately NOT accepted as a route value — dispatch checks
    ``isinstance(response, BaseException)`` plus an exact-type guard, so a
    misused class cannot silently pass through as a response object.
    """

    def __init__(self, book_id: str = BOOK_ID):
        self.book_id = str(book_id)
        self.requests: list[str] = []
        self.routes: dict[str, Any] = {}

    def endpoint_urls(self) -> set[str]:
        bid = self.book_id
        return {
            f"https://www.gutenberg.org/cache/epub/{bid}/pg{bid}-images-3.epub",
            f"https://www.gutenberg.org/cache/epub/{bid}/pg{bid}.txt",
            f"https://gutendex.com/books/{bid}",
        }

    async def __aenter__(self) -> "_FixtureSeam":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def get(self, url: str, headers: Any = None) -> _FakeResponse:
        self.requests.append(url)
        allowed = self.endpoint_urls()
        assert url in allowed, f"seam contacted an off-fixture endpoint: {url}"
        if url.endswith("-images-3.epub"):
            kind = "epub"
        elif url.endswith(f"/pg{self.book_id}.txt"):
            kind = "txt"
        else:
            kind = "gutendex"
        response = self.routes.get(kind)
        if isinstance(response, type) and issubclass(response, BaseException):
            raise AssertionError(
                f"seam route {kind!r} holds an exception CLASS ({response!r}); "
                "routes must hold response objects or exception instances"
            )
        if isinstance(response, BaseException):
            raise response
        if response is None:
            # Unrouted endpoint: answer 404 like the real origin would.
            return _FakeResponse(status_code=404)
        if not isinstance(response, _FakeResponse):
            raise AssertionError(
                f"seam route {kind!r} holds neither a response nor an "
                f"exception instance: {type(response).__name__}"
            )
        return response


def _install_seam(
    monkeypatch: pytest.MonkeyPatch, book_id: str = BOOK_ID, **routes: Any
) -> _FixtureSeam:
    """Patch ``gutenberg.httpx.AsyncClient`` onto the fake seam and return it."""
    seam = _FixtureSeam(book_id)
    seam.routes.update(routes)
    monkeypatch.setattr(gutenberg.httpx, "AsyncClient", lambda **kwargs: seam)
    return seam


def _install_routes(seam: _FixtureSeam, **routes: Any) -> _FixtureSeam:
    """Update a seam's routes in place and return it (for re-patching)."""
    seam.routes.update(routes)
    return seam


# ── In-test fixture builders ──────────────────────────────────────


_OPF_XML = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{OPF_TITLE}</dc:title>
    <dc:creator>{OPF_AUTHOR}</dc:creator>
    <dc:language>en</dc:language>
    <dc:subject>Fantasy fiction</dc:subject>
    <dc:subject>Animals in literature</dc:subject>
  </metadata>
</package>
"""

_CHAPTER_ONE_XHTML = """<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <h1>CHAPTER I Down the Rabbit-Hole</h1>
    <p>Alice was beginning to get very tired of sitting by her sister on
    the bank, and of having nothing to do.</p>
    <p>She considered whether the pleasure of making a daisy-chain would
    be worth the trouble of getting up and picking the daisies.</p>
  </body>
</html>
"""

_CHAPTER_TWO_XHTML = """<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <h1>CHAPTER II The Pool of Tears</h1>
    <p>'Curiouser and curiouser!' cried Alice she was much surprised.</p>
    <p>The white rabbit with pink eyes ran close by her.</p>
    <p>The golden key gleamed on the little glass table.</p>
  </body>
</html>
"""


def _build_epub_bytes() -> bytes:
    """A real EPUB zip (>100-byte gate) with an OPF and two XHTML chapters."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/content.opf", _OPF_XML)
        zf.writestr("ch01.xhtml", _CHAPTER_ONE_XHTML)
        zf.writestr("ch02.xhtml", _CHAPTER_TWO_XHTML)
    return buf.getvalue()


def _build_book_text() -> str:
    """Plain-text fixture: PG boilerplate gutter + two CHAPTER sections."""
    header_filler = (
        "The Project Gutenberg eBook of Alice's Adventures in Wonderland\n\n"
        "Release date: July 29, 2022\n"
        "Credits: produced by the hermetic fixture team\n\n"
    )
    start_marker = (
        "*** START OF THIS PROJECT GUTENBERG EBOOK "
        "ALICE'S ADVENTURES IN WONDERLAND ***\n\n"
    )
    # License-preamble gutter filler, mirroring the real pg<id>.txt layout
    # (that sentence opens the boilerplate between the START marker and the
    # first chapter heading). It must stay strippable so the
    # ``'Updated editions' not in md`` negative assertion has teeth: the
    # chapter splitter drops all text preceding the first CHAPTER heading,
    # so any regression leaking pre-heading gutter into the markdown fails
    # the test. Deliberately NOT placed after the END marker — the adapter's
    # known artifact appends post-END trailer text to the last chapter body,
    # which would make the negative assertion permanently red.
    license_preamble = (
        '"Updated editions will replace the previous one—the old '
        'editions will be renamed."\n'
        "Please check the Project Gutenberg web pages of this eBook "
        "for further details.\n\n"
    )
    chapter_one = (
        "CHAPTER I\nDown the Rabbit-Hole\n\n"
        "Alice was beginning to get very tired of sitting by her sister on "
        "the bank.\nShe wondered whether the pleasure of making a "
        f"{PROSE_CHAPTER_ONE} would be worth the trouble.\n\n"
    )
    chapter_two = (
        "CHAPTER II\nThe Pool of Tears\n\n"
        "'Curiouser and curiouser!' cried Alice she was much surprised.\n"
        f"The white rabbit ran close by her, and the {PROSE_CHAPTER_TWO}\n"
        "gleamed on the little glass table.\n\n"
        # No post-END trailer filler here: the adapter's boilerplate stripper
        # removes only up to (not including) the END marker, so anything past
        # it is appended to the last chapter's body — a known artifact we
        # must NOT pin in assertions; keep the prose fixtures clean of it.
    )
    end_marker = (
        "*** END OF THIS PROJECT GUTENBERG EBOOK ALICE'S ADVENTURES IN WONDERLAND ***\n"
    )
    return (
        header_filler
        + start_marker
        + license_preamble
        + chapter_one
        + chapter_two
        + end_marker
    )


def _build_boilerplate_only_text() -> str:
    """PG boilerplate markers with no prose between them (>100-byte gate).

    Only marker-to-marker content is stripped by ``_strip_boilerplate``, so
    the fixture must consist of the START/END markers alone: any text before
    START or after END would leak through as a degenerate non-empty success
    (the adapter drops pre-marker header text only via the chapter splitter,
    which never fires without headings).
    """
    return (
        "*** START OF THIS PROJECT GUTENBERG EBOOK NOTHING HERE ***\n"
        "\n"
        "*** END OF THIS PROJECT GUTENBERG EBOOK NOTHING HERE ***\n"
    )


def _gutendex_payload(authors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Payload shaped like the real gutendex API response."""
    return {
        "id": int(BOOK_ID),
        "title": GUTENDEX_TITLE,
        "authors": authors
        if authors is not None
        else [{"name": GUTENDEX_AUTHOR_NAME, "birth_year": 1832, "death_year": 1898}],
        "languages": ["en", "fr"],
        "subjects": ["Fantasy fiction", "Alice (Fictitious character)"],
        "download_count": 54321,
    }


def _healthy_routes(epub_bytes: bytes | None = None) -> dict[str, Any]:
    """Default happy-path route table: EPUB hit + gutendex 200."""
    return {
        "epub": _FakeResponse(
            content=epub_bytes if epub_bytes is not None else _build_epub_bytes()
        ),
        "gutendex": _FakeResponse(json_data=_gutendex_payload()),
    }


def _assert_seam_contained(seam: _FixtureSeam) -> None:
    """Every recorded request stayed inside the fixture endpoints."""
    assert set(seam.requests) <= seam.endpoint_urls(), (
        f"seam contacted off-fixture endpoints: "
        f"{set(seam.requests) - seam.endpoint_urls()}"
    )


def seam_requests(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Return the current seam's recorded requests (via the patched factory)."""
    return getattr(monkeypatch, "_gutenberg_seam_requests", [])


async def _scrape(url: str, monkeypatch: pytest.MonkeyPatch, **routes: Any) -> Any:
    """Install the seam with ``routes`` and scrape ``url`` hermetically.

    Asserts endpoint containment afterwards, so every scrape-driven test
    (not just the dedicated containment test) verifies that no traffic left
    the three fixture endpoints.
    """
    seam = _install_seam(monkeypatch, **routes)
    monkeypatch.setattr(
        monkeypatch,
        "_gutenberg_seam_requests",
        seam.requests,
        raising=False,
    )
    result = await gutenberg.GutenbergAdapter().scrape(url, AdapterContext())
    _assert_seam_contained(seam)
    return result


# ── Hermeticity containment ───────────────────────────────────────


@pytest.mark.asyncio
async def test_seam_serves_only_fixture_endpoints(monkeypatch):
    """Every recorded request stays inside the three fixture endpoints.

    This dedicated test additionally asserts WHICH endpoints were touched;
    endpoint containment itself is asserted for every scrape via
    :func:`_scrape`, so no test can leak off-fixture traffic silently.
    """
    txt = _FakeResponse(content=_build_book_text().encode())
    # One EPUB-hit scrape...
    seam = _install_seam(
        monkeypatch,
        epub=_FakeResponse(content=_build_epub_bytes()),
        gutendex=_FakeResponse(json_data=_gutendex_payload()),
        txt=txt,
    )
    result = await gutenberg.GutenbergAdapter().scrape(EBOOKS_URL, AdapterContext())
    assert result.success is True
    # ...plus one txt-tier fallback scrape (an EPUB hit short-circuits
    # before the txt tier, so both tiers need separate runs for coverage).
    monkeypatch.setattr(
        gutenberg.httpx,
        "AsyncClient",
        lambda **kwargs: _install_routes(
            seam, epub=_FakeResponse(status_code=504), txt=txt
        ),
    )
    result = await gutenberg.GutenbergAdapter().scrape(EBOOKS_URL, AdapterContext())
    assert result.success is True

    endpoints = seam.endpoint_urls()
    assert set(seam.requests) <= endpoints
    assert any(u.endswith(f"pg{BOOK_ID}-images-3.epub") for u in seam.requests)
    assert any(u.endswith(f"pg{BOOK_ID}.txt") for u in seam.requests)
    assert any(u.startswith("https://gutendex.com/books/") for u in seam.requests)


# ── Tier 1: EPUB parsing ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_epub_tier_parses_metadata_and_chapters(monkeypatch):
    """A canned EPUB zip parses into OPF metadata + chapter-structured markdown."""
    # gutendex answers 500 here so the surviving metadata is pure OPF.
    result = await _scrape(
        EBOOKS_URL,
        monkeypatch,
        epub=_FakeResponse(content=_build_epub_bytes()),
        gutendex=_FakeResponse(status_code=500),
    )

    assert result.success is True
    assert result.source == "gutenberg-epub"
    md = result.markdown
    assert PROSE_CHAPTER_ONE in md
    assert PROSE_CHAPTER_TWO in md
    assert "\n\n---\n\n" in md  # chapter separator
    assert len(re.findall(r"^## ", md, flags=re.MULTILINE)) >= 2
    assert result.metadata["title"] == OPF_TITLE
    assert result.metadata["author"] == OPF_AUTHOR
    assert result.metadata["language"] == "en"
    assert result.metadata["subjects"] == ["Fantasy fiction", "Animals in literature"]
    assert result.metadata["gutenberg_id"] == 11
    assert isinstance(result.metadata["gutenberg_id"], int)
    chapters = result.metadata["chapters"]
    assert chapters == [
        "CHAPTER I Down the Rabbit-Hole",
        "CHAPTER II The Pool of Tears",
    ]
    assert seam_requests(monkeypatch), "adapter never reached the seam"


# ── Tier 2: plain-text fallback ───────────────────────────────────


@pytest.mark.asyncio
async def test_txt_fallback_when_epub_returns_504(monkeypatch):
    """EPUB 504 (observed outage shape) recovers via the plaintext tier."""
    result = await _scrape(
        EBOOKS_URL,
        monkeypatch,
        epub=_FakeResponse(status_code=504),
        txt=_FakeResponse(content=_build_book_text().encode()),
        gutendex=_FakeResponse(json_data=_gutendex_payload()),
    )

    assert result.success is True
    assert result.source == "gutenberg-plaintext"
    md = result.markdown
    assert PROSE_CHAPTER_ONE in md
    assert PROSE_CHAPTER_TWO in md
    assert len(re.findall(r"^## ", md, flags=re.MULTILINE)) == 2
    assert "*** START" not in md
    assert "END OF" not in md
    assert "Release date: July 29, 2022" not in md
    assert "hermetic fixture team" not in md
    assert "Updated editions" not in md
    # Metadata/frontmatter populated from the gutendex 200 merge.
    assert result.metadata["author"] == "Carroll, Lewis (1832-1898)"
    assert result.metadata["language"] == "en"
    assert result.metadata["gutenberg_id"] == 11
    assert result.with_frontmatter().startswith("---")


# ── Gutendex metadata merge ───────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("author_entry", "expected_author"),
    [
        (
            {"name": GUTENDEX_AUTHOR_NAME, "birth_year": 1832, "death_year": 1898},
            "Carroll, Lewis (1832-1898)",
        ),
        (
            {"name": GUTENDEX_AUTHOR_NAME, "birth_year": 1832},
            "Carroll, Lewis (1832-)",
        ),
        ({"name": GUTENDEX_AUTHOR_NAME}, GUTENDEX_AUTHOR_NAME),
    ],
    ids=["birth-death", "death-absent", "bare-name"],
)
async def test_gutendex_author_formats_birth_death(
    monkeypatch, author_entry, expected_author
):
    """The (birth-death) formatting branch covers present/absent death years."""
    seam = _install_seam(
        monkeypatch,
        gutendex=_FakeResponse(json_data=_gutendex_payload(authors=[author_entry])),
    )

    meta = await gutenberg._fetch_gutendex_metadata(BOOK_ID)

    assert meta is not None
    assert meta["author"] == expected_author
    assert seam.requests == [f"https://gutendex.com/books/{BOOK_ID}"]


@pytest.mark.asyncio
async def test_gutendex_overrides_opf_metadata_on_epub_path(monkeypatch):
    """On the EPUB path the gutendex merge wins over differing OPF values."""
    payload = _gutendex_payload()
    result = await _scrape(
        EBOOKS_URL,
        monkeypatch,
        epub=_FakeResponse(content=_build_epub_bytes()),
        gutendex=_FakeResponse(json_data=payload),
    )

    assert result.success is True
    assert result.source == "gutenberg-epub"
    # Dict-update precedence: distinct OPF value != final metadata value.
    assert OPF_TITLE != GUTENDEX_TITLE
    assert result.metadata["title"] == GUTENDEX_TITLE
    assert result.metadata["author"] == "Carroll, Lewis (1832-1898)"
    assert result.metadata["language"] == payload["languages"][0]
    assert result.metadata["subjects"] == payload["subjects"]
    assert result.metadata["download_count"] == 54321
    assert seam_requests(monkeypatch), "adapter never reached the seam"


@pytest.mark.asyncio
async def test_gutendex_failure_is_nonfatal(monkeypatch):
    """A gutendex 500 degrades to OPF metadata without breaking the scrape."""
    result = await _scrape(
        EBOOKS_URL,
        monkeypatch,
        epub=_FakeResponse(content=_build_epub_bytes()),
        gutendex=_FakeResponse(status_code=500),
    )

    assert result.success is True
    assert result.source == "gutenberg-epub"
    assert result.metadata["title"] == OPF_TITLE
    assert result.metadata["author"] == OPF_AUTHOR
    assert result.metadata["subjects"] == ["Fantasy fiction", "Animals in literature"]
    assert PROSE_CHAPTER_ONE in result.markdown


# ── Both tiers dead → typed error → registry fall-through ────────


@pytest.mark.asyncio
async def test_both_tiers_dead_raises_adapter_error(monkeypatch):
    """EPUB and txt both failing raises a typed AdapterError."""
    seam = _install_seam(
        monkeypatch,
        epub=_FakeResponse(status_code=504),
        txt=_FakeResponse(status_code=504),
    )

    with pytest.raises(AdapterError, match="Could not extract content"):
        await gutenberg.GutenbergAdapter().scrape(EBOOKS_URL, AdapterContext())

    _assert_seam_contained(seam)


@pytest.mark.asyncio
async def test_registry_dispatch_falls_through_to_stub_adapter(monkeypatch):
    """AdapterError inside dispatch falls through to a lower-priority stub."""
    _install_seam(
        monkeypatch,
        epub=_FakeResponse(status_code=504),
        txt=_FakeResponse(status_code=504),
    )

    class StubGenericAdapter(SiteAdapter):
        name = "stub-generic"
        patterns = [re.compile(r"^https://www\.gutenberg\.org/ebooks/\d+")]
        priority = 100  # below the gutenberg adapter's native priority 200

        async def scrape(self, url: str, ctx: AdapterContext) -> AdapterResult:
            return AdapterResult(
                success=True,
                markdown="generic pipeline markdown",
                source="generic-fallback",
                url=url,
            )

    registry = AdapterRegistry()
    registry.register(gutenberg.GutenbergAdapter())
    registry.register(StubGenericAdapter())

    result = await registry.dispatch(EBOOKS_URL, AdapterContext())

    assert result is not None
    assert result.source == "generic-fallback"
    assert result.markdown == "generic pipeline markdown"
    assert result.url == EBOOKS_URL
    # Optional corroboration per VAL-GUTT-005: the dispatch-error counter
    # path executed for the failing gutenberg adapter, and the stub recorded
    # a hit — proving both dispatch outcomes were exercised end-to-end.
    # Label-set presence (not absolute values): METRICS is a process-global
    # singleton, so counter totals accumulate across tests in one pytest run.
    metrics_text = METRICS.generate_openmetrics()
    assert (
        'groktocrawl_adapter_dispatch_total{adapter_group="gutenberg",'
        'outcome="error"}' in metrics_text
    )
    assert (
        'groktocrawl_adapter_dispatch_total{adapter_group="stub-generic",'
        'outcome="hit"}' in metrics_text
    )


# ── Invalid ids ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_book_id_errors_without_network(monkeypatch):
    """A URL matching no pattern fails ID extraction before any HTTP attempt."""
    seam = _install_seam(monkeypatch)

    with pytest.raises(AdapterError, match="Could not extract book ID"):
        await gutenberg.GutenbergAdapter().scrape(INVALID_ID_URL, AdapterContext())

    assert seam.requests == []
    _assert_seam_contained(seam)


@pytest.mark.asyncio
async def test_nonexistent_book_id_deterministic(monkeypatch):
    """A well-formed nonexistent id fails identically on repeated calls."""
    seam = _install_seam(monkeypatch, book_id="99999999")

    results = []
    for _ in range(2):
        with pytest.raises(AdapterError) as excinfo:
            await gutenberg.GutenbergAdapter().scrape(NONEXISTENT_URL, AdapterContext())
        results.append((type(excinfo.value).__name__, str(excinfo.value)))

    assert results[0] == results[1]
    assert results[0][0] == "AdapterError"
    # Only fixture endpoints were attempted (and answered 404 by the seam).
    _assert_seam_contained(seam)


# ── EPUB acceptance gate ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_epub_tiny_payload_falls_through_to_txt(monkeypatch):
    """A 200 EPUB response at/below the 100-byte gate falls through to txt."""
    tiny = b"x" * 87  # accepted gate is strictly ">100 bytes"
    result = await _scrape(
        EBOOKS_URL,
        monkeypatch,
        epub=_FakeResponse(status_code=200, content=tiny),
        txt=_FakeResponse(content=_build_book_text().encode()),
        gutendex=_FakeResponse(json_data=_gutendex_payload()),
    )
    assert len(tiny) <= 100

    assert result.success is True
    assert result.source == "gutenberg-plaintext"
    assert PROSE_CHAPTER_ONE in result.markdown


# ── Alternate URL forms ───────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "url"),
    [("ebooks", EBOOKS_URL), ("files", FILES_URL), ("cache-epub", CACHE_URL)],
)
async def test_alternate_url_forms_dispatch_to_same_book_id(monkeypatch, label, url):
    """All three pattern families extract id 11 and succeed hermetically."""
    result = await _scrape(url, monkeypatch, **_healthy_routes())

    assert gutenberg._extract_book_id(url) == BOOK_ID

    assert result.success is True, f"{label} form failed"
    assert result.source == "gutenberg-epub"
    assert result.metadata["gutenberg_id"] == 11


# ── Boilerplate-only plaintext ────────────────────────────────────


@pytest.mark.asyncio
async def test_boilerplate_only_txt_raises_adapter_error(monkeypatch):
    """A txt payload with only PG boilerplate must not yield empty success."""
    raw = _build_boilerplate_only_text()
    assert len(raw) > 100  # clears the download gate, strips to nothing
    seam = _install_seam(
        monkeypatch,
        epub=_FakeResponse(status_code=504),
        txt=_FakeResponse(content=raw.encode()),
    )

    with pytest.raises(AdapterError):
        await gutenberg.GutenbergAdapter().scrape(EBOOKS_URL, AdapterContext())

    _assert_seam_contained(seam)
