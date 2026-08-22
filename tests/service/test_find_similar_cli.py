"""CLI tests for find-similar backend-failure vs. clean-empty behavior.

Covers issue #588's user-facing contract: when the API answers non-200
(vector backend down), ``groktocrawl find-similar`` must exit non-zero
with a structured error — never print "No similar pages found". A true
empty result (HTTP 200, ``data: []``) keeps the legacy exit-0 behavior.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from tests.service.test_cli import _cli_ns


def _make_client(api_error):
    client = MagicMock()
    client.dry_run = False
    client.find_similar.side_effect = api_error
    return client


def _make_args():
    args = MagicMock()
    args.url = "https://example.com/herbs"
    args.limit = 10
    args.search_mode = "qdrant"
    return args


class TestFindSimilarBackendFailure:
    def test_backend_error_exits_non_zero_with_stderr_message(self, capsys):
        """Non-200 answer → SystemExit(1), error on stderr, no empty-success."""
        api_error = _cli_ns["ApiError"](
            "API error (502): semantic-svc vector search failed",
            status_code=502,
            body={
                "success": False,
                "error": "semantic-svc vector search failed",
                "error_code": "SEMANTIC_SERVICE_ERROR",
            },
        )
        cmd_find_similar = _cli_ns["cmd_find_similar"]
        client = _make_client(api_error)

        with pytest.raises(SystemExit) as exit_info:
            cmd_find_similar(client, _make_args())

        assert exit_info.value.code != 0
        captured = capsys.readouterr()
        assert "API error (502)" in captured.err
        assert "No similar pages found" not in captured.out + captured.err

    def test_backend_error_json_mode_emits_structured_body_on_stdout(self, capsys):
        """--json mode: die() dumps the response body carrying the error code."""
        original_json = _cli_ns["JSON_OUTPUT"]
        _cli_ns["JSON_OUTPUT"] = True
        try:
            api_error = _cli_ns["ApiError"](
                "API error (502): semantic-svc vector search failed",
                status_code=502,
                body={
                    "success": False,
                    "error": "semantic-svc vector search failed",
                    "error_code": "SEMANTIC_SERVICE_ERROR",
                },
            )
            cmd_find_similar = _cli_ns["cmd_find_similar"]
            with pytest.raises(SystemExit) as exit_info:
                cmd_find_similar(_make_client(api_error), _make_args())
        finally:
            _cli_ns["JSON_OUTPUT"] = original_json

        assert exit_info.value.code != 0
        out = capsys.readouterr().out
        body = json.loads(out.strip())
        assert body["error_code"] == "SEMANTIC_SERVICE_ERROR"
        assert body["success"] is False


class TestFindSimilarCleanEmpty:
    def test_empty_data_prints_no_similar_pages_and_exits_zero(self, capsys):
        """200 + data:[] → 'No similar pages found for <url>' and no raise."""
        client = MagicMock()
        client.dry_run = False
        client.find_similar.return_value = {"success": True, "data": []}

        cmd_find_similar = _cli_ns["cmd_find_similar"]
        # cmd_find_similar returns normally on a clean-empty payload: any
        # SystemExit (non-zero error path) would fail this test.
        cmd_find_similar(client, _make_args())

        captured = capsys.readouterr()
        assert "No similar pages found for https://example.com/herbs" in captured.out
        assert captured.err == ""
