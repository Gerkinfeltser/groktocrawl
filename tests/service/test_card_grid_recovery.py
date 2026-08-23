"""Regression tests for card-grid extraction yield recovery (issue #587).

The open-neuromorphic.org hardware directory wraps every card's ``<h3>``/
``<p>`` inside its parent ``<a>`` and places the card grid in a SIBLING of
the intro container. readability-lxml scores nothing in the grid (link
density 1.0) and silently drops it, returning intro-only output (~766 chars
from >10KB of HTML). These tests pin the fix:

- Primary: low-yield detection recovers the full body via an uncapped
  full-page conversion (output must exceed the 10,000-char structural cap).
- Secondary: anchor-unwrap preprocessing preserves card hrefs as markdown
  links on the card titles.
- Tertiary: a volume-comparison quality check surfaces a low-yield warning
  on below-floor extractions and stays silent on recovered pages.
- Shared consumers (adapters helper, ``filter_sections``, Tier wiring) all
  benefit from the single shared recovery path.

The deterministic fixture under ``tests/fixtures/html/`` is modeled on a
saved snapshot of the live reproduction URL (same topology: intro container
plus sibling anchor-wrapped card grid, 25 cards, >10KB HTML).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRAPER_SVC = Path(__file__).resolve().parents[2] / "scraper-svc"
if str(SCRAPER_SVC) not in sys.path:
    sys.path.insert(0, str(SCRAPER_SVC))

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "html"
    / "card_grid_anchor_wrapped.html"
)

# The 25 card titles/hrefs encoded in the deterministic fixture.
CARD_HREFS = [
    ("/neuromorphic-computing/hardware/ada-neucom/", "ADA - Neucom"),
    (
        "/neuromorphic-computing/hardware/tsp1-time-series-processor-applied-brain-research/",
        "TSP1 - Applied Brain Research",
    ),
    ("/neuromorphic-computing/hardware/texel/", "TEXEL - University of Groningen"),
    ("/neuromorphic-computing/hardware/pulsar-by-innatera/", "Pulsar - Innatera"),
    (
        "/neuromorphic-computing/hardware/snp-by-innatera/",
        "Spiking Neural Processor T1 by Innatera",
    ),
    (
        "/neuromorphic-computing/hardware/dynap-se2-institute-of-neuroinformatics/",
        "DYNAP-SE2 - Institute of Neuroinformatics",
    ),
    ("/neuromorphic-computing/hardware/northpole-ibm/", "NorthPole - IBM"),
    ("/neuromorphic-computing/hardware/speck-synsense/", "Speck - SynSense"),
    ("/neuromorphic-computing/hardware/akida-brainchip/", "Akida - BrainChip"),
    ("/neuromorphic-computing/hardware/seneca-imec/", "SENeCA by imec"),
    (
        "/neuromorphic-computing/hardware/brainscales-2-universitat-heidelberg/",
        "BrainScaleS-2 - Heidelberg University",
    ),
    ("/neuromorphic-computing/hardware/reckon-frenkel/", "ReckOn - Charlotte Frenkel"),
    ("/neuromorphic-computing/hardware/xylo-synsense/", "Xylo - SynSense"),
    ("/neuromorphic-computing/hardware/loihi-2-intel/", "Loihi 2 - Intel"),
    (
        "/neuromorphic-computing/hardware/spinnaker-2-university-of-dresden/",
        "SpiNNaker 2 - University of Dresden",
    ),
    (
        "/neuromorphic-computing/hardware/tianjic-tsinghua-university/",
        "Tianjic - Tsinghua University",
    ),
    ("/neuromorphic-computing/hardware/dynap-cnn-synsense/", "DynapCNN - SynSense"),
    ("/neuromorphic-computing/hardware/odin-frenkel/", "Odin by Charlotte Frenkel"),
    ("/neuromorphic-computing/hardware/loihi-intel/", "Loihi - Intel"),
    (
        "/neuromorphic-computing/hardware/brainscales-1-universitat-heidelberg/",
        "BrainScaleS-1 - Heidelberg University",
    ),
    ("/neuromorphic-computing/hardware/rolls-ini/", "ROLLS - INI"),
    ("/neuromorphic-computing/hardware/truenorth-ibm/", "TrueNorth - IBM"),
    (
        "/neuromorphic-computing/hardware/neurogrid-braindrop-stanford/",
        "NeuroGrid (BrainDrop) - Stanford",
    ),
    (
        "/neuromorphic-computing/hardware/spikey-universitat-heidelberg/",
        "Spikey - Heidelberg University",
    ),
    (
        "/neuromorphic-computing/hardware/sakura-example-institute/",
        "Sakura - Example Institute",
    ),
]

SENTINEL = "The directory index was last reconciled by the maintainers guild."


@pytest.fixture(scope="module")
def card_grid_html() -> str:
    return FIXTURE.read_text()


# ── Fixture sanity ───────────────────────────────────────────────


def test_card_grid_fixture_replicates_bug_topology(card_grid_html):
    """Fixture mirrors the live bug: >10KB, anchor-wrapped cards, sibling grid."""
    from bs4 import BeautifulSoup

    assert FIXTURE.stat().st_size > 10240
    soup = BeautifulSoup(card_grid_html, "html.parser")
    cards = soup.select("a.hardware-card-wide-link")
    assert len(cards) == 25
    # Every card's h3 lives INSIDE its parent anchor (link density trap).
    wrapped = sum(1 for a in cards if a.find("h3") is not None)
    assert wrapped == 25
    # Intro container and the card-grid tree are siblings under a common
    # parent (climb from the card anchor to the OUTERMOST enclosing list).
    prose = soup.select_one("div.prose")
    top_list = cards[0].find_parent("ul")
    while top_list.parent.name in ("li", "ul"):
        top_list = top_list.parent
    assert prose is not None and top_list is not None
    assert prose.parent is top_list.parent


# ── VAL-YIELD-003: card-grid body survives html_to_markdown ──────


def test_html_to_markdown_recovers_card_grid_body(card_grid_html):
    """Output far exceeds the intro-only regime and exceeds the 10K cap."""
    from scraper.fetch_quality import html_to_markdown

    markdown = html_to_markdown(card_grid_html)
    # Must beat BOTH the intro-only regime (~766 chars) and the structural
    # extractor's hard 10,000-char cap.
    assert len(markdown) >= 10240
    titles_present = sum(1 for _, title in CARD_HREFS if title in markdown)
    assert titles_present >= 20, f"only {titles_present}/25 card titles retained"


def test_html_to_markdown_card_grid_contains_directory_terms(card_grid_html):
    """The contract tokens (Loihi, Akida, SpiNNaker) appear in recovered output."""
    from scraper.fetch_quality import html_to_markdown

    markdown = html_to_markdown(card_grid_html)
    assert "Loihi" in markdown
    assert "Akida" in markdown
    assert "SpiNNaker" in markdown


def test_html_to_markdown_card_grid_intro_only_regime_gone(card_grid_html):
    """Pre-fix, exactly the intro paragraphs came back and nothing else."""
    from scraper.fetch_quality import html_to_markdown

    markdown = html_to_markdown(card_grid_html)
    # Card descriptions live only in the grid; their presence proves the
    # sibling block was extracted rather than dropped.
    assert "Event-based neural network processor" in markdown
    assert "Wafer-scale analog system" in markdown


# ── VAL-YIELD-011: href preservation on unwrapped card anchors ───


def test_html_to_markdown_preserves_card_hrefs_as_title_links(card_grid_html):
    """Unwrapped anchors keep their href as [Title](href) on the title."""
    from scraper.fetch_quality import html_to_markdown

    markdown = html_to_markdown(card_grid_html)
    linked = sum(
        1
        for href, title in CARD_HREFS
        if f"[{title}]({href})" in markdown.replace("\n", "")
    )
    assert linked >= 20, f"only {linked}/25 card hrefs preserved as title links"


# ── VAL-YIELD-004: sibling-topology sentinel survives ────────────


def test_sibling_block_sentinel_survives_recovery(card_grid_html):
    """Text living ONLY in the sibling card-grid tree must survive."""
    from scraper.fetch_quality import html_to_markdown

    markdown = html_to_markdown(card_grid_html)
    assert SENTINEL in markdown


# ── VAL-YIELD-005: no regression on normal articles ──────────────


def test_html_to_markdown_article_no_regression():
    """A representative article keeps its full body through the fix."""
    from scraper.fetch_quality import html_to_markdown

    mid_sentence = (
        "Deep in the middle of the article the author explains the tradeoffs "
        "between analog cores and digital meshes with unusual candor."
    )
    closing = "The closing section ties the survey together with deployment guidance."
    html = f"""<html><head><title>Neuromorphic Survey</title></head>
    <body>
    <header>Site Header Boilerplate</header>
    <nav><a href="/">Home</a><a href="/archive">Archive</a></nav>
    <article>
      <h1>A Survey of Neuromorphic Processors</h1>
      <p>The survey opens with a history of spiking hardware from the late
      eighties onward, setting context for the comparisons that follow.</p>
      <p>{mid_sentence}</p>
      <p>Later sections benchmark throughput per watt across three generations
      of devices, with methodology notes appended for reproducibility.</p>
      <p>{closing}</p>
    </article>
    <footer>Copyright Boilerplate</footer>
    </body></html>"""

    markdown = html_to_markdown(html)
    assert mid_sentence in markdown
    assert closing in markdown
    # Chrome filtering still applies on the normal readability path.
    assert "Site Header Boilerplate" not in markdown
    assert "Copyright Boilerplate" not in markdown
    assert "[Home](/)" not in markdown


# ── VAL-YIELD-009: SPA shell / tiny input degradation parity ─────


def test_html_to_markdown_large_spa_shell_still_degrades_small():
    """Huge script-only shells still degrade gracefully (no fabricated body)."""
    from scraper.fetch_quality import html_to_markdown

    filler = "".join(f"console.log('bundle chunk {i} payload');\n" for i in range(400))
    html = (
        "<html><head><title>Single Page App</title>"
        '<meta name="description" content="Client-rendered dashboard.">'
        f"<script>{filler}</script></head>"
        "<body><div id='root'></div><footer>Legal</footer></body></html>"
    )
    assert len(html) > 10240  # source is large; recovered text must not be
    markdown = html_to_markdown(html)
    assert len(markdown) < 2000  # no fabricated content from scripts
    assert "Single Page App" in markdown
    assert "console.log" not in markdown


def test_html_to_markdown_tiny_input_unchanged():
    """Tiny pages keep today's exact structural-fallback behavior."""
    from scraper.fetch_quality import html_to_markdown

    html = "<html><head><title>Page</title></head><body><p>Hello</p></body></html>"
    markdown = html_to_markdown(html)
    assert 0 < len(markdown) < 200
    assert "Page" in markdown or "Hello" in markdown


# ── VAL-YIELD-007/010: low-yield diagnostic pairing ──────────────


def test_assess_quality_volume_check_flags_below_floor_extraction():
    """Markdown far below the sanity floor on a large source trips the check."""
    from scraper.extract import assess_quality

    thin_markdown = "# Intro\n\n" + "Short intro paragraph only. " * 15  # ~450 chars
    result = assess_quality(thin_markdown, html_size=94978)
    assert result["checks"]["volume"] == "fail"
    assert "volume:fail" in result["detail"]


def test_assess_quality_volume_check_passes_on_recovered_page(card_grid_html):
    """Recovered yield is above the floor — the diagnostic must not fire."""
    from scraper.extract import assess_quality
    from scraper.fetch_quality import html_to_markdown

    markdown = html_to_markdown(card_grid_html)
    result = assess_quality(markdown, html_size=len(card_grid_html))
    assert result["checks"]["volume"] == "pass"


def test_assess_quality_volume_check_skipped_without_source_size():
    """No source-size information -> check passes without opinion."""
    from scraper.extract import assess_quality

    result = assess_quality("Some modest content here.", html_size=0)
    assert result["checks"]["volume"] == "pass"
    result = assess_quality("Some modest content here.")
    assert result["checks"]["volume"] == "pass"


def test_assess_quality_volume_check_skipped_for_small_sources():
    """Sources below the minimum size gate never trip the ratio check."""
    from scraper.extract import assess_quality

    result = assess_quality("Tiny page, tiny source.", html_size=900)
    assert result["checks"]["volume"] == "pass"


def test_add_quality_sets_warning_for_below_floor_result():
    """Below-floor extraction surfaces the warning on the result dict."""
    from scraper.fetch_quality import _add_quality

    result = {
        "markdown": "# Intro\n\n" + "Short intro paragraph only. " * 15,
        "url": "https://example.test/hardware",
        "source_html_size": 94978,
    }
    enriched = _add_quality(result)
    assert enriched["quality"]["checks"]["volume"] == "fail"
    assert enriched.get("warning")
    assert "low yield" in enriched["warning"].lower()


def test_add_quality_no_warning_for_recovered_result(card_grid_html):
    """Recovered pages present as clean successes — no warning field."""
    from scraper.fetch_quality import _add_quality, html_to_markdown

    result = {
        "markdown": html_to_markdown(card_grid_html),
        "url": "https://example.test/hardware",
        "source_html_size": len(card_grid_html),
    }
    enriched = _add_quality(result)
    assert enriched["quality"]["checks"]["volume"] == "pass"
    assert not enriched.get("warning")


def test_tier2_fallback_carries_source_html_size():
    """Tier 2 HTML-fallback results expose their source size for the check."""
    from scraper import fetch_tiers

    source = inspect_getsource(fetch_tiers.fetch_via_content_negotiation)
    assert "source_html_size" in source


def inspect_getsource(func):
    import inspect

    return inspect.getsource(func)


# ── VAL-YIELD-008: shared consumers aligned ──────────────────────


@pytest.mark.asyncio
async def test_scrape_page_full_body(monkeypatch):
    """adapters/_helpers.scrape_page() must return the full card-grid body via
    the shared recovery path instead of its private readability pipeline."""
    import httpx
    from scraper.adapters import _helpers

    class _Resp:
        status_code = 200
        text = FIXTURE.read_text()

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    result = await _helpers.scrape_page("https://example.test/hardware/")
    assert result is not None
    titles_present = sum(1 for _, title in CARD_HREFS if title in result)
    assert titles_present >= 20
    assert SENTINEL in result


def test_scrape_page_delegates_to_shared_html_to_markdown():
    """The helper must call the shared implementation, not re-roll readability."""
    import inspect

    from scraper.adapters import _helpers

    source = inspect.getsource(_helpers)
    assert "html_to_markdown" in source


def test_filter_sections_standard_returns_full_card_grid_body(card_grid_html):
    """filter_sections (standard verbosity) recovers the sibling card grid."""
    from scraper.extract import filter_sections

    markdown = filter_sections(card_grid_html, verbosity="standard")
    titles_present = sum(1 for _, title in CARD_HREFS if title in markdown)
    assert titles_present >= 20
    assert SENTINEL in markdown


def test_filter_sections_delegates_to_shared_html_to_markdown():
    """Standard verbosity must reuse html_to_markdown (single shared path)."""
    import inspect

    import scraper.extract as extract_mod

    source = inspect.getsource(extract_mod)
    assert source.count("Document(") <= 1, (
        "filter_sections should delegate to html_to_markdown instead of "
        "running a second private readability pipeline"
    )


def test_fetch_tiers_uses_shared_html_to_markdown():
    """Tier implementations import the shared converter (wiring sentinel)."""
    import inspect

    from scraper import fetch_tiers

    source = inspect.getsource(fetch_tiers)
    assert "from .fetch_quality import" in source or ("from .fetch_quality" in source)
    assert "html_to_markdown" in source


# ── Review hardening: recovery must not replace complete fragments ──


def test_recovery_keeps_complete_short_article_fragment():
    """A complete short article on a large page is NOT swapped for a
    full-page conversion that would merge sidebars/div-footers into it."""
    from scraper.fetch_quality import html_to_markdown

    article = (
        "<p>This compact article is entirely complete despite its brevity. "
        "It explains one narrow idea across three tidy paragraphs and needs "
        "no further sections to stand alone as useful extracted content.</p>"
        "<p>The second paragraph rounds out the argument with a concrete "
        "example that readers can reproduce on their own hardware quickly.</p>"
    )
    # Filler bytes (HTML comments) push the source past the low-yield size
    # gate without adding extractable text.
    filler = "<!-- analytics blob " + "x" * 12000 + " -->"
    html = (
        "<html><head><title>Compact Note</title></head><body>"
        f"{filler}<article>{article}</article>"
        '<aside class="sidebar">Sidebar Navigation Text About Widgets</aside>'
        "<footer>Div Footer Boilerplate Line</footer>"
        "</body></html>"
    )
    markdown = html_to_markdown(html)
    # Article survives intact...
    assert "entirely complete despite its brevity" in markdown
    # ...without the surrounding chrome a full-page dump would drag in.
    assert "Sidebar Navigation Text About Widgets" not in markdown
    assert "Div Footer Boilerplate Line" not in markdown


@pytest.mark.asyncio
async def test_scrape_page_does_not_duplicate_title(monkeypatch):
    """When the shared pipeline already starts with the page title, the
    helper must not prepend it again."""
    import httpx
    from scraper.adapters import _helpers

    html = (
        "<html><head><title>Dup Title Probe</title></head><body><p>Hello"
        "</p></body></html>"
    )

    class _Resp:
        status_code = 200
        text = html

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    result = await _helpers.scrape_page("https://example.test/note")
    assert result is not None
    assert result.count("Dup Title Probe") == 1
