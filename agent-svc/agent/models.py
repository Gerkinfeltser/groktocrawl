"""Pydantic models matching the Firecrawl v2 agent API contract."""

from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


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
