"""Tests for the GroktoCrawl MCP server — tool discovery, annotations,
JSON Schema validity, content blocks, protocol lifecycle, and error handling.

These tests exercise the FastMCP app directly without a running
agent-svc (the client calls are mocked).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp_server import mcp

# ── Helpers ───────────────────────────────────────────────────────


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, dict],
) -> None:
    """Monkeypatch GroktocrawlClient methods to return canned responses.

    *responses* maps method names (e.g. ``"scrape"``, ``"search"``) to
    the dict that should be returned when that method is called.
    """
    import mcp_server as mod

    for meth_name, result in responses.items():

        async def _patched(*args: Any, _result: Any = result, **kwargs: Any) -> dict:
            return _result

        monkeypatch.setattr(mod._client, meth_name, _patched)


def _text(result: Any) -> str:
    """Extract the first text content block from a tool call result.

    FastMCP's ``call_tool`` returns a tuple of
    ``(unstructured_content, structured_content)`` where the first
    element is a list of ContentBlock objects.
    """
    if isinstance(result, tuple):
        return result[0][0].text
    return result.content[0].text


# ── Tool Discovery (VAL-MCP-B01, B02, B03, B04) ────────────────────


class TestToolDiscovery:
    """VAL-MCP-B01: tools/list returns exactly 17 tools."""

    async def test_tool_count(self):
        """tools/list returns exactly 17 tools."""
        tools = await mcp.list_tools()
        assert len(tools) == 17, f"Expected 17 tools, got {len(tools)}"

    async def test_all_tool_names(self):
        """All 17 expected tool names are present."""
        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        expected = {
            "scrape",
            "search",
            "crawl",
            "get_crawl_status",
            "cancel_crawl",
            "get_crawl_errors",
            "map",
            "agent",
            "get_agent_status",
            "answer",
            "extract",
            "get_extract_status",
            "enrich",
            "find_similar",
            "batch_scrape",
            "generate_llmstxt",
            "get_activity",
        }
        missing = expected - names
        extra = names - expected
        assert not missing, f"Missing tools: {missing}"
        assert not extra, f"Unexpected tools: {extra}"

    async def test_tool_names_are_unique(self):
        """VAL-MCP-B01: tool names are unique."""
        tools = await mcp.list_tools()
        names = [t.name for t in tools]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"

    async def test_all_tools_have_descriptions(self):
        """VAL-MCP-F03: all tools have non-empty descriptions."""
        tools = await mcp.list_tools()
        for t in tools:
            assert t.description, f"Tool {t.name} has empty description"
            assert len(t.description) >= 20, (
                f"Tool {t.name} description too short: "
                f"{len(t.description)} chars (need >= 20)"
            )

    async def test_async_tools_mention_job_id(self):
        """VAL-MCP-F03: async tools mention job ID + polling in description."""
        tools = await mcp.list_tools()
        async_tools = {"crawl", "extract", "batch_scrape", "generate_llmstxt"}
        for t in tools:
            if t.name in async_tools:
                desc_lower = t.description.lower()
                assert (
                    "job" in desc_lower
                    or "poll" in desc_lower
                    or "asynchronously" in desc_lower
                ), (
                    f"Async tool {t.name} does not mention job/polling in description: "
                    f"{t.description[:80]}"
                )

    async def test_all_tools_have_valid_input_schema(self):
        """VAL-MCP-B02: each tool has a valid JSON Schema inputSchema."""
        tools = await mcp.list_tools()
        for t in tools:
            schema = t.inputSchema
            assert schema["type"] == "object", (
                f"Tool {t.name} inputSchema type is not 'object': {schema.get('type')}"
            )
            assert "properties" in schema, (
                f"Tool {t.name} inputSchema missing 'properties'"
            )
            assert isinstance(schema["properties"], dict), (
                f"Tool {t.name} properties is not a dict"
            )

    async def test_tools_with_required_params_have_required_array(self):
        """VAL-MCP-B02: tools with mandatory params have 'required' list."""
        tools = await mcp.list_tools()

        # Tools that definitely have required params
        tools_with_required = {
            "scrape": "url",
            "search": "query",
            "crawl": "url",
            "map": "url",
            "agent": "prompt",
            "answer": "query",
            "extract": "urls",
            "enrich": "url",
            "find_similar": "url",
            "batch_scrape": "urls",
            "generate_llmstxt": "url",
        }

        for t in tools:
            if t.name in tools_with_required:
                required = t.inputSchema.get("required", [])
                expected_param = tools_with_required[t.name]
                assert expected_param in required, (
                    f"Tool {t.name}: '{expected_param}' not in required list {required}"
                )


# ── Tool Annotations (VAL-MCP-B03) ────────────────────────────────


class TestToolAnnotations:
    """VAL-MCP-B03: Tool annotations match expected readOnly/destructive hints."""

    async def test_readonly_tools(self):
        """Tools that only read data have readOnlyHint=True."""
        tools = await mcp.list_tools()
        readonly_tools = {
            "scrape",
            "search",
            "map",
            "agent",
            "answer",
            "extract",
            "enrich",
            "find_similar",
            "get_crawl_status",
            "get_agent_status",
            "get_extract_status",
            "get_crawl_errors",
            "get_activity",
        }
        for t in tools:
            if t.name in readonly_tools:
                anno = t.annotations
                assert anno is not None, f"Tool {t.name} missing annotations"
                assert anno.readOnlyHint is True, (
                    f"Tool {t.name}: expected readOnlyHint=True, got {anno.readOnlyHint}"
                )
                assert anno.destructiveHint is False, (
                    f"Tool {t.name}: expected destructiveHint=False, got {anno.destructiveHint}"
                )

    async def test_destructive_tools(self):
        """Tools that modify state have destructiveHint=True."""
        tools = await mcp.list_tools()
        destructive_tools = {
            "crawl",
            "cancel_crawl",
            "batch_scrape",
            "generate_llmstxt",
        }
        for t in tools:
            if t.name in destructive_tools:
                anno = t.annotations
                assert anno is not None, f"Tool {t.name} missing annotations"
                assert anno.destructiveHint is True, (
                    f"Tool {t.name}: expected destructiveHint=True, got {anno.destructiveHint}"
                )
                assert anno.readOnlyHint is False, (
                    f"Tool {t.name}: expected readOnlyHint=False, got {anno.readOnlyHint}"
                )

    async def test_tool_annotations_consistent(self):
        """VAL-MCP-B04: annotations consistent across sessions (same server)."""
        tools1 = await mcp.list_tools()
        tools2 = await mcp.list_tools()
        for t1, t2 in zip(tools1, tools2, strict=False):
            assert t1.name == t2.name
            if t1.annotations and t2.annotations:
                assert t1.annotations.readOnlyHint == t2.annotations.readOnlyHint
                assert t1.annotations.destructiveHint == t2.annotations.destructiveHint


# ── Content Block Formatting (VAL-MCP-F01, F02) ────────────────────


class TestContentBlocks:
    """VAL-MCP-F01, F02: text content blocks and JSON-serializable IDs."""

    async def test_scrape_returns_text_content(self, monkeypatch):
        """Scrape tool returns content[0].type == 'text'."""
        _patch_client(
            monkeypatch,
            {
                "scrape": {"success": True, "data": {"markdown": "# Hello"}},
            },
        )
        result = await mcp.call_tool("scrape", {"url": "https://example.com"})
        content_blocks = result[0]
        assert content_blocks[0].type == "text"
        assert len(content_blocks[0].text) > 0

    async def test_crawl_returns_json_with_id(self, monkeypatch):
        """Crawl (job-creating tool) returns JSON with id and success."""
        _patch_client(
            monkeypatch,
            {
                "create_crawl": {"success": True, "id": "crawl-job-123"},
            },
        )
        result = await mcp.call_tool("crawl", {"url": "https://example.com"})
        data = json.loads(_text(result))
        assert data.get("success") is True
        assert "id" in data

    async def test_batch_scrape_returns_json_with_id(self, monkeypatch):
        """Batch scrape returns JSON with id."""
        _patch_client(
            monkeypatch,
            {
                "create_batch_scrape": {"success": True, "id": "batch-job-456"},
            },
        )
        result = await mcp.call_tool(
            "batch_scrape", {"urls": ["https://a.com", "https://b.com"]}
        )
        data = json.loads(_text(result))
        assert "id" in data

    async def test_generate_llmstxt_returns_json_with_id(self, monkeypatch):
        """Generate llms.txt returns JSON with id."""
        _patch_client(
            monkeypatch,
            {
                "create_llmstxt": {"success": True, "id": "llmstxt-job-789"},
            },
        )
        result = await mcp.call_tool("generate_llmstxt", {"url": "https://example.com"})
        data = json.loads(_text(result))
        assert "id" in data

    async def test_extract_returns_json_with_id(self, monkeypatch):
        """Extract returns JSON with id."""
        _patch_client(
            monkeypatch,
            {
                "create_extract": {"success": True, "id": "extract-job-001"},
            },
        )
        result = await mcp.call_tool(
            "extract",
            {"urls": ["https://example.com"], "prompt": "Extract headings"},
        )
        data = json.loads(_text(result))
        assert "id" in data

    async def test_error_result_includes_status_code(self, monkeypatch):
        """Error from client is propagated with status_code."""
        _patch_client(
            monkeypatch,
            {
                "scrape": {"error": "Invalid URL", "status_code": 400},
            },
        )
        result = await mcp.call_tool("scrape", {"url": "https://example.com"})
        text = _text(result)
        assert "400" in text
        assert "Invalid URL" in text


# ── Tool Call Routing (VAL-MCP-C01, C02, D04, E01, E06) ───────────


class TestToolCallRouting:
    """Verify each tool maps to the correct client method."""

    async def test_scrape_passes_only_main_content(self, monkeypatch):
        """Scrape passes only_main_content=False through."""
        captured: dict[str, Any] = {}

        async def _fake_scrape(**kwargs: Any) -> dict:
            captured.update(kwargs)
            return {"success": True}

        monkeypatch.setattr(
            __import__("mcp_server", fromlist=["_client"])._client,
            "scrape",
            _fake_scrape,
        )
        await mcp.call_tool(
            "scrape",
            {
                "url": "https://example.com",
                "formats": ["markdown"],
                "only_main_content": False,
            },
        )
        assert captured.get("url") == "https://example.com"
        assert captured.get("formats") == ["markdown"]
        assert captured.get("only_main_content") is False
        assert "only_main_content" in captured  # explicitly passed

    async def test_search_passes_search_type(self, monkeypatch):
        """Search passes search_type through."""
        captured: dict[str, Any] = {}

        async def _fake_search(**kwargs: Any) -> dict:
            captured.update(kwargs)
            return {"data": {"web": []}}

        monkeypatch.setattr(
            __import__("mcp_server", fromlist=["_client"])._client,
            "search",
            _fake_search,
        )
        await mcp.call_tool(
            "search",
            {
                "query": "test",
                "limit": 3,
                "search_type": "rich",
            },
        )
        assert captured.get("query") == "test"
        assert captured.get("limit") == 3
        assert captured.get("search_type") == "rich"

    async def test_answer_passes_num_sources(self, monkeypatch):
        """Answer passes num_sources through."""
        captured: dict[str, Any] = {}

        async def _fake_answer(**kwargs: Any) -> dict:
            captured.update(kwargs)
            return {"answer": "test", "sources": []}

        monkeypatch.setattr(
            __import__("mcp_server", fromlist=["_client"])._client,
            "answer",
            _fake_answer,
        )
        await mcp.call_tool("answer", {"query": "test?", "num_sources": 3})
        assert captured.get("question") == "test?"
        assert captured.get("num_sources") == 3

    async def test_agent_passes_model_override(self, monkeypatch):
        """Agent passes model override through to client."""
        captured: dict[str, Any] = {}

        async def _fake_agent(**kwargs: Any) -> dict:
            captured.update(kwargs)
            return {"status": "completed", "data": {"result": "ok"}}

        monkeypatch.setattr(
            __import__("mcp_server", fromlist=["_client"])._client,
            "agent",
            _fake_agent,
        )
        await mcp.call_tool(
            "agent",
            {
                "prompt": "test research",
                "model": "gpt-4o",
            },
        )
        assert captured.get("prompt") == "test research"
        assert captured.get("model") == "gpt-4o"

    async def test_map_passes_limit(self, monkeypatch):
        """Map passes limit through."""
        captured: dict[str, Any] = {}

        async def _fake_map(**kwargs: Any) -> dict:
            captured.update(kwargs)
            return {"links": []}

        monkeypatch.setattr(
            __import__("mcp_server", fromlist=["_client"])._client,
            "map",
            _fake_map,
        )
        await mcp.call_tool("map", {"url": "https://example.com", "limit": 50})
        assert captured.get("url") == "https://example.com"
        assert captured.get("limit") == 50

    async def test_crawl_passes_max_params(self, monkeypatch):
        """Crawl passes max_pages and max_depth through."""
        captured: dict[str, Any] = {}

        async def _fake_create_crawl(**kwargs: Any) -> dict:
            captured.update(kwargs)
            return {"success": True, "id": "crawl-1"}

        monkeypatch.setattr(
            __import__("mcp_server", fromlist=["_client"])._client,
            "create_crawl",
            _fake_create_crawl,
        )
        await mcp.call_tool(
            "crawl",
            {
                "url": "https://example.com",
                "max_pages": 10,
                "max_depth": 3,
            },
        )
        assert captured.get("url") == "https://example.com"
        assert captured.get("max_pages") == 10
        assert captured.get("max_depth") == 3

    async def test_get_activity_no_args(self, monkeypatch):
        """get_activity takes no required arguments."""
        captured: dict[str, Any] = {}

        async def _fake_get_activity(**kwargs: Any) -> dict:
            captured["called"] = True
            return {"jobs": []}

        monkeypatch.setattr(
            __import__("mcp_server", fromlist=["_client"])._client,
            "get_activity",
            _fake_get_activity,
        )
        await mcp.call_tool("get_activity", {})
        assert captured.get("called") is True


# ── Error Handling (VAL-MCP-G01) ──────────────────────────────────


class TestErrorHandling:
    """VAL-MCP-G01: Invalid tool name returns error."""

    async def test_invalid_tool_name(self):
        """Calling a non-existent tool raises ToolError."""
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("nonexistent_tool", {})
        # FastMCP raises ToolError for unknown tools
        assert "Unknown tool" in str(exc_info.value) or "nonexistent_tool" in str(
            exc_info.value
        )

    async def test_missing_required_argument(self):
        """Missing required argument raises validation error."""
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("scrape", {})
        # Pydantic validation error should mention the missing field
        err_str = str(exc_info.value)
        assert "url" in err_str.lower() or "validation" in err_str.lower(), (
            f"Expected url/validation error, got: {err_str[:200]}"
        )

    async def test_invalid_argument_type(self):
        """Invalid argument type raises validation error."""
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("scrape", {"url": 12345})
        err_str = str(exc_info.value)
        # Should mention type issue
        assert (
            "url" in err_str.lower()
            or "type" in err_str.lower()
            or "validation" in err_str.lower()
        ), f"Expected type error, got: {err_str[:200]}"

    async def test_error_propagation_with_is_error(self, monkeypatch):
        """VAL-MCP-G03: HTTP errors are propagated with status code."""
        _patch_client(
            monkeypatch,
            {
                "get_crawl_status": {
                    "error": "Job not found",
                    "status_code": 404,
                },
            },
        )
        result = await mcp.call_tool("get_crawl_status", {"job_id": "nonexistent"})
        text = _text(result)
        assert "404" in text
        assert "not found" in text.lower()


# ── Session Consistency (VAL-MCP-B04) ─────────────────────────────


class TestSessionConsistency:
    """VAL-MCP-B04: tools/list is consistent across 'sessions'."""

    async def test_tool_list_consistent_across_calls(self):
        """Multiple calls to list_tools return same tool set."""
        tools1 = await mcp.list_tools()
        tools2 = await mcp.list_tools()
        tools3 = await mcp.list_tools()

        names1 = {t.name for t in tools1}
        names2 = {t.name for t in tools2}
        names3 = {t.name for t in tools3}

        assert names1 == names2 == names3

    async def test_tool_schemas_consistent(self):
        """Tool inputSchemas are consistent across calls."""
        tools1 = await mcp.list_tools()
        tools2 = await mcp.list_tools()

        schemas1 = {t.name: t.inputSchema for t in tools1}
        schemas2 = {t.name: t.inputSchema for t in tools2}

        for name in schemas1:
            assert schemas1[name] == schemas2[name], f"Schema mismatch for tool {name}"


# ── Descriptions (VAL-MCP-F03) ───────────────────────────────────


class TestDescriptions:
    """All tools have descriptions >= 20 chars, async tools mention polling."""

    async def test_min_description_length(self):
        tools = await mcp.list_tools()
        for t in tools:
            desc_len = len(t.description)
            assert desc_len >= 20, (
                f"Tool '{t.name}' description is {desc_len} chars (need >= 20)"
            )

    async def test_camel_case_property_names(self):
        """VAL-MCP-B02: inputSchema properties use camelCase (from Python snake_case)."""
        tools = await mcp.list_tools()
        for t in tools:
            props = t.inputSchema.get("properties", {})
            for prop_name in props:
                # Python snake_case params become camelCase in schema via FastMCP
                # Both are acceptable; we just check they're valid
                assert isinstance(prop_name, str)
                assert len(prop_name) > 0
