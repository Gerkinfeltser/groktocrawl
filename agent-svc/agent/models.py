"""Pydantic models matching the Firecrawl v2 agent API contract."""

from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

# ── Valid scrape format values ──────────────────────────────────
VALID_SCRAPE_FORMATS: frozenset[str] = frozenset(
    {"markdown", "html", "links", "screenshot", "rawHtml", "screenshot@fullPage"}
)


class ErrorDetail(BaseModel):
    """A single field-level validation error."""

    field: str
    message: str


class ErrorResponse(BaseModel):
    """Standard error response body for all API endpoints."""

    success: bool = False
    error: str = "An unexpected error occurred"
    error_code: str = "INTERNAL_ERROR"
    details: list[ErrorDetail] | dict | None = None


class ScrapeOptions(BaseModel):
    """Firecrawl-compatible scrape options for controlling per-page extraction.

    All fields are optional with documented defaults. When ``None`` (or omitted),
    the scraper-svc applies its own sensible defaults for each field.

    Attributes:
        formats: List of output formats to return. Allowed values:
            ``markdown`` (default), ``html``, ``links``, ``screenshot``,
            ``rawHtml``, ``screenshot@fullPage``.
        only_main_content: When True, strip navigation, header, footer and
            other boilerplate from the extracted content (default: True).
        include_tags: If set, only content from these CSS/tag selectors is
            included in the output.
        exclude_tags: If set, content from these CSS/tag selectors is removed
            from the output.
        wait_for: Time in milliseconds to wait for the page to load/stabilize
            before extracting content. Useful for JS-rendered SPAs.
        mobile: When True, use a mobile user-agent and viewport dimensions
            (default: False).
        timeout: Per-page timeout in milliseconds (default: 30000, minimum: 1000).
        headers: Custom HTTP headers to forward with the request (e.g.,
            ``{"Authorization": "Bearer ..."}``).
        remove_base64_images: When True, strip ``data:image/...`` URIs from
            the extracted content (default: False).
    """

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    formats: list[str] = Field(
        default=["markdown"],
        description="Output formats: markdown, html, links, etc.",
    )
    only_main_content: bool = Field(
        default=True,
        description="Strip navigation/header/footer boilerplate",
    )
    include_tags: list[str] | None = Field(
        default=None, description="Only include content from these selectors"
    )
    exclude_tags: list[str] | None = Field(
        default=None, description="Exclude content from these selectors"
    )
    wait_for: int | None = Field(
        default=None, ge=0, description="Wait time in milliseconds before extraction"
    )
    mobile: bool = Field(default=False, description="Use mobile viewport and UA")
    timeout: int = Field(
        default=30000, ge=1000, description="Per-page timeout in milliseconds"
    )
    headers: dict[str, str] | None = Field(
        default=None, description="Custom HTTP headers"
    )
    remove_base64_images: bool = Field(
        default=False, description="Strip data:image/... URIs from output"
    )
    max_age: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Maximum age of cached content in milliseconds. If the cached response"
            " is younger than ``max_age``, it is returned without re-scraping."
            " When set to 0, caching is bypassed entirely (every request is fresh)."
        ),
    )
    min_age: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Minimum age for cache-only mode in milliseconds. When set, only cached"
            " content is returned. A cache miss produces a cache_miss error for that"
            " URL rather than fetching fresh content."
        ),
    )

    @field_validator("formats")
    @classmethod
    def validate_formats(cls, value: list[str]) -> list[str]:
        """Validate that each format is a known/recognised value."""
        if not value:
            raise ValueError("formats must be a non-empty list")
        for fmt in value:
            if fmt not in VALID_SCRAPE_FORMATS:
                allowed = ", ".join(sorted(VALID_SCRAPE_FORMATS))
                raise ValueError(f"Invalid format '{fmt}'. Allowed values: {allowed}")
        return value

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, value: int) -> int:
        """Reject out-of-range timeout values."""
        if value < 1000:
            raise ValueError(f"timeout must be >= 1000ms, got {value}")
        return value

    @field_validator("wait_for")
    @classmethod
    def validate_wait_for(cls, value: int | None) -> int | None:
        """Reject negative wait_for values."""
        if value is not None and value < 0:
            raise ValueError(f"wait_for must be >= 0, got {value}")
        return value

    @field_validator("max_age")
    @classmethod
    def validate_max_age(cls, value: int | None) -> int | None:
        """Reject negative max_age values.

        VAL-SCRAPE-032: negative maxAge returns 422.
        """
        if value is not None and value < 0:
            raise ValueError(f"max_age must be >= 0, got {value}")
        return value

    @model_validator(mode="after")
    def validate_cache_ages(self) -> "ScrapeOptions":
        """Validate that min_age does not exceed max_age.

        VAL-SCRAPE-033: minAge greater than maxAge is rejected.
        """
        min_age = self.min_age
        max_age = self.max_age
        if min_age is not None and max_age is not None and min_age > max_age:
            raise ValueError(
                f"min_age ({min_age}ms) cannot exceed max_age ({max_age}ms)"
            )
        return self


class ScrapeRequest(BaseModel):
    url: str
    formats: list[str] = ["markdown"]
    only_main_content: bool = True
    timeout: int = 30000


class DownloadData(BaseModel):
    """Binary content metadata for non-HTML responses."""

    filename: str
    content_type: str
    size: int
    data_url: str | None = None


class ScrapeData(BaseModel):
    markdown: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    download: DownloadData | None = None
    quality: dict[str, Any] | None = None


class ScrapeResponse(BaseModel):
    success: bool
    data: ScrapeData | None = None
    error: str | None = None


class AgentRequest(BaseModel):
    prompt: str = Field(
        ..., max_length=100000, description="What the agent should research"
    )
    urls: list[str] | None = Field(
        None, description="Optional seed URLs to constrain research"
    )
    schema_: dict[str, Any] | None = Field(
        None, alias="schema", description="JSON Schema for structured output"
    )
    model: str = Field(default="default", description="Model hint")
    max_credits: int | None = None
    webhook: dict[str, Any] | None = None
    strict_constrain_to_urls: bool = False
    stream: bool = Field(default=False, description="SSE streaming response")

    model_config = ConfigDict(populate_by_name=True)


class AgentCreateResponse(BaseModel):
    success: bool = True
    id: str


class AgentStatusResponse(BaseModel):
    success: bool = True
    status: str = "processing"  # processing | completed | failed | cancelled
    data: dict[str, Any] | None = None
    error: str | None = None
    expires_at: str | None = None
    credits_used: int | None = None


class AgentCancelResponse(BaseModel):
    success: bool = True


class CrawlRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    url: str
    max_pages: int = Field(
        default=10, ge=1, description="Maximum pages to scrape, must be >= 1"
    )
    max_depth: int = Field(
        default=2, ge=0, description="Maximum link-follow depth, must be >= 0"
    )
    limit: int | None = None
    ignore_sitemap: bool = False
    sitemap: str = Field(
        default="include",
        description="Sitemap mode: 'include' (default), 'skip', or 'only'",
    )
    ignore_query_parameters: bool = False
    include_paths: list[str] | None = None
    exclude_paths: list[str] | None = None
    regex_on_full_url: bool = False
    verbose: bool = False
    webhook: dict[str, Any] | None = None
    crawl_entire_domain: bool = False
    allow_subdomains: bool = False
    allow_external_links: bool = False
    max_concurrency: int = Field(
        default=3,
        ge=1,
        description="Maximum concurrent page scrapes (1-50, values > 50 are capped)",
    )
    delay: float | None = Field(
        default=None,
        ge=0,
        description="Delay in seconds between scrapes. Forces concurrency to 1 when set.",
    )
    ignore_robots_txt: bool = Field(
        default=False,
        description="When True, bypass robots.txt enforcement. All discovered URLs are scraped regardless of robots.txt Disallow rules.",
    )
    robots_user_agent: str | None = Field(
        default=None,
        description="Custom User-Agent string for robots.txt evaluation. When set, robots.txt rules are evaluated against this User-Agent instead of the default bot UA.",
    )
    scrape_options: ScrapeOptions | None = Field(
        default=None,
        description="Per-page scrape options controlling output format, content filtering, viewport, and timeout behavior. Applied to every page in the crawl, including the start URL.",
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """Validate that url is a well-formed HTTP/HTTPS URL."""
        parsed = urlparse(value)
        if not parsed.scheme:
            raise ValueError("URL must have a scheme (http:// or https://)")
        if parsed.scheme.lower() not in ("http", "https"):
            raise ValueError(f"URL scheme must be http or https, got '{parsed.scheme}'")
        if not parsed.netloc:
            raise ValueError("URL must have a network location (host)")
        return value

    @field_validator("max_concurrency")
    @classmethod
    def validate_max_concurrency(cls, value: int) -> int:
        """Validate and cap max_concurrency values.

        Values of 0 or negative are rejected (would deadlock the semaphore).
        Values above 50 are silently capped to 50 to prevent resource exhaustion.
        """
        if value < 1:
            raise ValueError(f"max_concurrency must be >= 1, got {value}")
        return min(value, 50)

    @field_validator("delay")
    @classmethod
    def validate_delay(cls, value: float | None) -> float | None:
        """Reject negative delay values."""
        if value is not None and value < 0:
            raise ValueError(f"delay must be >= 0, got {value}")
        return value

    @model_validator(mode="after")
    def validate_regex_patterns(self) -> "CrawlRequest":
        """When regex_on_full_url is True, validate that all path
        patterns are valid Python regular expressions."""
        if not self.regex_on_full_url:
            return self
        import re as _re

        for field_name in ("include_paths", "exclude_paths"):
            patterns = getattr(self, field_name)
            if not patterns:
                continue
            for i, pattern in enumerate(patterns):
                try:
                    _re.compile(pattern)
                except _re.error as exc:
                    raise ValueError(
                        f"Invalid regex in {field_name}[{i}]: '{pattern}' — {exc}"
                    ) from exc
        return self

    @model_validator(mode="after")
    def resolve_sitemap_mode(self) -> "CrawlRequest":
        """Backward compatibility: ignore_sitemap=true → sitemap='skip'.

        Also validates that sitemap is one of the allowed values.
        """
        # Backward compatibility: ignore_sitemap overrides sitemap field
        if self.ignore_sitemap:
            self.sitemap = "skip"

        # Validate sitemap value
        allowed = ("include", "skip", "only")
        if self.sitemap not in allowed:
            raise ValueError(
                f"Invalid sitemap mode '{self.sitemap}'. Must be one of: {', '.join(allowed)}"
            )
        return self


class CrawlCreateResponse(BaseModel):
    success: bool = True
    id: str


class CrawlStatusResponse(BaseModel):
    success: bool = True
    status: str = "processing"
    completed: int = 0
    total: int = 0
    credits_used: int | None = None
    data: list[dict[str, Any]] | None = None
    error: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    expires_at: str | None = None
    duration: int | None = None


class BatchScrapeRequest(BaseModel):
    urls: list[str]
    max_concurrency: int = 3
    webhook: dict[str, Any] | None = None


class SearchRequest(BaseModel):
    query: str
    limit: int = 5
    search_type: str = "fast"  # "fast" | "rich"
    retrieval_mode: str = (
        "keyword"  # "keyword" | "semantic" | "hybrid" | "vector" | "hybrid_vector"
    )
    categories: list[str] | None = None
    sources: list[str] | None = None
    output_schema: dict[str, Any] | None = None  # JSON Schema for structured extraction
    system_prompt: str | None = None  # Guidance for synthesis


class SearchResult(BaseModel):
    url: str
    title: str
    description: str = ""


class SearchResponse(BaseModel):
    success: bool = True
    data: dict = Field(default_factory=lambda: {"web": [], "images": [], "news": []})
    output: dict[str, Any] | None = None  # Present only when output_schema provided


class MapRequest(BaseModel):
    url: str
    limit: int = 100
    search: str | None = None
    allow_subdomains: bool = False
    allow_external_links: bool = False


class MapResponse(BaseModel):
    success: bool = True
    links: list[str] = Field(default_factory=list)


class BrowserCreateRequest(BaseModel):
    ttl: int = Field(default=300, ge=30, le=3600, description="Session TTL in seconds")


class BrowserExecuteRequest(BaseModel):
    action: str = Field(
        ...,
        description="Action: navigate, click, type, screenshot, scroll, wait, getContent, executeScript",
    )
    url: str | None = None
    selector: str | None = None
    text: str | None = None
    script: str | None = None
    timeout: int = 10000


class BrowserCreateResponse(BaseModel):
    success: bool = True
    id: str


class BrowserExecuteResponse(BaseModel):
    success: bool = True
    result: Any = None
    error: str | None = None


class BrowserListResponse(BaseModel):
    success: bool = True
    sessions: list[dict] = Field(default_factory=list)


class BrowserDeleteResponse(BaseModel):
    success: bool = True
    id: str


class ExtractRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, description="URLs to extract data from")
    prompt: str | None = Field(
        None, max_length=10000, description="Optional instruction for extraction"
    )
    schema_: dict[str, Any] | None = Field(
        None, alias="schema", description="JSON Schema for structured output"
    )
    model: str = Field(default="default", description="Model hint")
    webhook: dict[str, Any] | None = None

    model_config = ConfigDict(populate_by_name=True)


class ExtractCreateResponse(BaseModel):
    success: bool = True
    id: str


class ExtractStatusResponse(BaseModel):
    success: bool = True
    status: str = "processing"  # processing | completed | failed
    data: dict[str, Any] | None = None
    error: str | None = None
    expires_at: str | None = None


class MonitorCreateRequest(BaseModel):
    url: str = Field(..., description="URL to monitor for changes")
    schedule: str = Field(
        default="0 */6 * * *", description="Cron expression for check frequency"
    )
    webhook: str | None = Field(None, description="Webhook URL called on change")


class MonitorUpdateRequest(BaseModel):
    url: str | None = None
    schedule: str | None = None
    webhook: str | None = None


class MonitorResponse(BaseModel):
    success: bool = True
    id: str
    url: str
    schedule: str
    webhook: str | None = None
    last_checked: str | None = None
    last_result: str | None = None
    created_at: str


class MonitorListResponse(BaseModel):
    success: bool = True
    monitors: list[MonitorResponse] = Field(default_factory=list)


class MonitorDeleteResponse(BaseModel):
    success: bool = True


class ParseResponse(BaseModel):
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None


class LLMsTextRequest(BaseModel):
    url: str = Field(..., description="Site URL to generate llms.txt for")
    max_pages: int = Field(default=50, ge=1, le=500, description="Max pages to scan")
    webhook: dict[str, Any] | None = None


class LLMsTextCreateResponse(BaseModel):
    success: bool = True
    id: str


class LLMsTextStatusResponse(BaseModel):
    success: bool = True
    status: str = "processing"
    data: dict[str, Any] | None = None
    error: str | None = None
    expires_at: str | None = None


class Source(BaseModel):
    """A source used to ground an answer."""

    url: str
    title: str = ""
    relevance: str = ""


class Citation(BaseModel):
    """An inline citation mapping [N] to a URL."""

    index: int
    url: str


class AnswerRequest(BaseModel):
    query: str = Field(..., max_length=10000, description="Natural language question")
    search_type: str = Field(default="auto", description="Hint for search depth")
    retrieval_mode: str = Field(
        default="keyword",
        description="keyword | semantic | hybrid | vector | hybrid_vector",
    )
    num_sources: int = Field(
        default=5, ge=1, le=20, description="How many sources to ground the answer"
    )
    model: str = Field(default="default", description="Per-request LLM override")
    stream: bool = Field(default=False, description="SSE streaming response")


class AnswerResponse(BaseModel):
    success: bool = True
    answer: str = ""
    sources: list[Source] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    search_type: str = "auto"
    latency_ms: int = 0


class ActivityItem(BaseModel):
    """A single job entry in the activity feed."""

    id: str
    kind: str
    status: str
    url: str | None = None
    created_at: str
    completed_at: str | None = None


class ActivityResponse(BaseModel):
    """Response model for the unified activity endpoint."""

    success: bool = True
    data: list[ActivityItem] = Field(default_factory=list)
