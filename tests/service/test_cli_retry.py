"""CLI retry behavior tests for rate-limited responses (ADR-0053).

Covers eligibility classification, retry-delay parsing/clamping with
injected jitter, bounded retry loops (429 → success, exhaustion), the
absence of retries for non-429 errors, valid ``--json`` stdout with
retry messages on stderr, duplicate-job safety, and interruption during
a retry wait.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.outcome_governance import governed_skip

_CLI_PATH = Path(__file__).resolve().parents[2] / "groktocrawl"
if not _CLI_PATH.is_file():
    governed_skip(
        "groktocrawl CLI not found at project root",
        owner="repository-maintainer",
        issue="#502",
        classification="retained",
        environment="local checkout does not expose the root CLI",
        allow_module_level=True,
    )
_CLI_PATH = str(_CLI_PATH)

_cli_ns: dict = {}
with open(_CLI_PATH, encoding="utf-8") as f:
    _code = compile(f.read(), _CLI_PATH, "exec")
exec(_code, _cli_ns)


def _response(status_code: int, body: dict, headers: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.headers = headers or {}
    resp.url = "http://test-server:8080/v2/answer"
    return resp


_RATE_LIMITED_BODY = {
    "success": False,
    "error": "Per-client rate limit exceeded",
    "error_code": "RATE_LIMITED",
    "retryable": True,
    "retry_after_seconds": 37,
}


class TestEligibility:
    def test_429_with_rate_limited_code_is_retryable(self):
        assert _cli_ns["_is_retryable_rate_limit"](429, _RATE_LIMITED_BODY) is True

    def test_429_without_code_is_not_retryable(self):
        assert _cli_ns["_is_retryable_rate_limit"](429, {"error": "nope"}) is False

    def test_non_429_statuses_are_not_retryable(self):
        for status in (200, 400, 401, 404, 422, 502):
            assert (
                _cli_ns["_is_retryable_rate_limit"](status, _RATE_LIMITED_BODY) is False
            )

    def test_missing_body_is_not_retryable(self):
        assert _cli_ns["_is_retryable_rate_limit"](429, None) is False


class TestRetryDelay:
    def test_body_field_takes_precedence(self):
        delay = _cli_ns["_retry_delay_from_response"](
            {"retry_after_seconds": 37}, {"Retry-After": "5"}
        )
        assert delay == 37

    def test_header_fallback(self):
        delay = _cli_ns["_retry_delay_from_response"]({}, {"Retry-After": "5"})
        assert delay == 5

    def test_malformed_header_is_absent(self):
        assert (
            _cli_ns["_retry_delay_from_response"]({}, {"Retry-After": "soon"}) is None
        )
        assert _cli_ns["_retry_delay_from_response"]({}, {"Retry-After": "-3"}) is None
        assert _cli_ns["_retry_delay_from_response"]({}, {"Retry-After": "inf"}) is None
        assert _cli_ns["_retry_delay_from_response"]({}, {"Retry-After": "nan"}) is None
        assert _cli_ns["_retry_delay_from_response"]({}, {}) is None

    def test_negative_body_delay_is_absent(self):
        assert (
            _cli_ns["_retry_delay_from_response"]({"retry_after_seconds": -1}, {})
            is None
        )
        assert (
            _cli_ns["_retry_delay_from_response"](
                {"retry_after_seconds": float("inf")}, {}
            )
            is None
        )

    def test_server_delay_clamped(self, monkeypatch):
        monkeypatch.setenv("GROKTOCRAWL_RETRY_MAX_WAIT_SECONDS", "60")
        compute = _cli_ns["_compute_retry_delay"]
        assert compute(_RATE_LIMITED_BODY, {}, 1, jitter_fn=lambda: 0.0) == 37
        assert (
            compute({"retry_after_seconds": 9999}, {}, 1, jitter_fn=lambda: 0.0) == 60
        )
        assert compute({"retry_after_seconds": 0}, {}, 1, jitter_fn=lambda: 0.0) == 1.0

    def test_fallback_backoff_with_jitter(self, monkeypatch):
        monkeypatch.delenv("GROKTOCRAWL_RETRY_MAX_WAIT_SECONDS", raising=False)
        monkeypatch.delenv("GROKTOCRAWL_RETRY_FALLBACK_SECONDS", raising=False)
        compute = _cli_ns["_compute_retry_delay"]
        assert compute({}, {}, 1, jitter_fn=lambda: 0.0) == 1.0
        assert compute({}, {}, 2, jitter_fn=lambda: 0.0) == 2.0
        assert compute({}, {}, 3, jitter_fn=lambda: 0.0) == 4.0
        assert compute({}, {}, 1, jitter_fn=lambda: 0.5) == 1.5


class TestRequestRetry:
    @pytest.fixture
    def client(self):
        return _cli_ns["Client"](server="http://test-server:8080", dry_run=False)

    def test_429_then_success_returns_and_retries_once(
        self, client, capsys, monkeypatch
    ):
        import requests as requests_module

        responses = [
            _response(429, _RATE_LIMITED_BODY, {"Retry-After": "37"}),
            _response(200, {"success": True, "id": "job_1"}),
        ]
        monkeypatch.setitem(_cli_ns, "_interruptible_sleep", lambda s: None)
        with patch.object(requests_module, "request", side_effect=responses) as req:
            result = client._request(
                "POST",
                "/answer",
                json_data={"query": "q"},
                retry=True,
                operation="answer",
            )
        assert result["id"] == "job_1"
        assert req.call_count == 2
        err = capsys.readouterr().err
        assert "Rate limited (answer)" in err
        assert "attempt 1/3" in err
        assert "37s" in err

    def test_exhaustion_raises_structured_error(self, client, monkeypatch):
        import requests as requests_module

        responses = [
            _response(429, _RATE_LIMITED_BODY),
            _response(429, _RATE_LIMITED_BODY),
            _response(429, _RATE_LIMITED_BODY),
        ]
        monkeypatch.setitem(_cli_ns, "_interruptible_sleep", lambda s: None)
        with patch.object(requests_module, "request", side_effect=responses) as req:
            with pytest.raises(_cli_ns["RetryExhaustedError"]) as exc:
                client._request(
                    "POST",
                    "/answer",
                    json_data={"query": "q"},
                    retry=True,
                    operation="answer",
                )
        assert exc.value.attempts == 3
        assert exc.value.status_code == 429
        assert req.call_count == 3

    def test_non_429_error_is_not_retried(self, client, monkeypatch):
        import requests as requests_module

        responses = [_response(400, {"error_code": "INVALID_REQUEST", "error": "bad"})]
        with patch.object(requests_module, "request", side_effect=responses) as req:
            with pytest.raises(_cli_ns["ApiError"]) as exc:
                client._request(
                    "POST",
                    "/answer",
                    json_data={"query": "q"},
                    retry=True,
                    operation="answer",
                )
        assert exc.value.status_code == 400
        assert req.call_count == 1

    def test_no_retry_without_retry_flag(self, client, monkeypatch):
        import requests as requests_module

        responses = [_response(429, _RATE_LIMITED_BODY)]
        with patch.object(requests_module, "request", side_effect=responses) as req:
            with pytest.raises(_cli_ns["ApiError"]):
                client._request("POST", "/answer", json_data={"query": "q"})
        assert req.call_count == 1

    def test_success_after_retry_has_single_job_id(self, client, monkeypatch):
        """Admission 429 → success: exactly one job ID ever appears."""
        import requests as requests_module

        responses = [
            _response(429, _RATE_LIMITED_BODY),
            _response(200, {"success": True, "id": "job_1"}),
        ]
        monkeypatch.setitem(_cli_ns, "_interruptible_sleep", lambda s: None)
        with patch.object(requests_module, "request", side_effect=responses):
            result = client._request(
                "POST",
                "/agent",
                json_data={"prompt": "p"},
                retry=True,
                operation="agent",
            )
        assert result["id"] == "job_1"

    def test_interruption_during_wait_exits_without_another_attempt(
        self, client, monkeypatch
    ):
        import requests as requests_module

        responses = [
            _response(429, _RATE_LIMITED_BODY),
            _response(200, {"success": True}),
        ]

        # The real _interruptible_sleep catches KeyboardInterrupt and exits
        # 130 before any second attempt is made.
        def _interrupting_sleep(_seconds: float) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(_cli_ns["time"], "sleep", _interrupting_sleep)
        with patch.object(requests_module, "request", side_effect=responses) as req:
            with pytest.raises(SystemExit) as exc:
                client._request(
                    "POST",
                    "/answer",
                    json_data={"query": "q"},
                    retry=True,
                    operation="answer",
                )
        assert exc.value.code == 130
        assert req.call_count == 1  # interrupted before the second attempt

    def test_interruptible_sleep_exits_130(self, monkeypatch):
        def _interrupting_sleep(_seconds: float) -> None:
            raise KeyboardInterrupt

        with patch.object(_cli_ns["time"], "sleep", _interrupting_sleep):
            with pytest.raises(SystemExit) as exc:
                _cli_ns["_interruptible_sleep"](60)
        assert exc.value.code == 130


class TestJsonOutput:
    @pytest.fixture
    def client(self):
        return _cli_ns["Client"](server="http://test-server:8080", dry_run=False)

    def test_die_renders_exhaustion_as_valid_json(self, monkeypatch, capsys):
        monkeypatch.setitem(_cli_ns, "JSON_OUTPUT", True)
        error = _cli_ns["RetryExhaustedError"](
            "Rate limit exceeded after 3 attempt(s): nope",
            status_code=429,
            body=_RATE_LIMITED_BODY,
            attempts=3,
            last_delay=37.0,
        )
        with pytest.raises(SystemExit) as exc:
            _cli_ns["die"](error)
        assert exc.value.code == 1
        out = capsys.readouterr().out
        payload = json.loads(out)  # must be valid JSON
        assert payload["error_code"] == "RATE_LIMITED"
        assert payload["retryable"] is True
        assert payload["attempts"] == 3
        assert payload["retry_after_seconds"] == 37.0
        err = capsys.readouterr().err
        assert err == ""

    def test_retry_progress_goes_to_stderr_not_stdout(
        self, client, monkeypatch, capsys
    ):
        import requests as requests_module

        responses = [
            _response(429, _RATE_LIMITED_BODY),
            _response(200, {"success": True, "id": "job_1"}),
        ]
        monkeypatch.setitem(_cli_ns, "_interruptible_sleep", lambda s: None)
        monkeypatch.setitem(_cli_ns, "JSON_OUTPUT", True)
        with patch.object(requests_module, "request", side_effect=responses):
            client._request(
                "POST",
                "/agent",
                json_data={"prompt": "p"},
                retry=True,
                operation="agent",
            )
        captured = capsys.readouterr()
        # Machine-readable stdout stays clean during retries; progress is
        # emitted only on stderr (AC-002.6 / NFR-003).
        assert captured.out == ""
        assert "Rate limited" in captured.err


class TestStreamingRetry:
    @pytest.fixture
    def client(self):
        return _cli_ns["Client"](server="http://test-server:8080", dry_run=False)

    def test_stream_429_then_success_opens_stream_once_retried(
        self, client, monkeypatch
    ):
        import requests as requests_module

        ok = MagicMock()
        ok.status_code = 200
        ok.headers = {}
        responses = [_response(429, _RATE_LIMITED_BODY), ok]
        monkeypatch.setitem(_cli_ns, "_interruptible_sleep", lambda s: None)
        with patch.object(requests_module, "post", side_effect=responses) as post:
            result = client.create_agent_stream(prompt="p", retry=True)
        assert result["_stream"] is ok
        assert post.call_count == 2

    def test_stream_exhaustion_raises_structured_error(self, client, monkeypatch):
        import requests as requests_module

        responses = [
            _response(429, _RATE_LIMITED_BODY),
            _response(429, _RATE_LIMITED_BODY),
            _response(429, _RATE_LIMITED_BODY),
        ]
        monkeypatch.setitem(_cli_ns, "_interruptible_sleep", lambda s: None)
        with patch.object(requests_module, "post", side_effect=responses) as post:
            with pytest.raises(_cli_ns["RetryExhaustedError"]) as exc:
                client.answer(query="q", stream=True, retry=True)
        assert exc.value.attempts == 3
        assert post.call_count == 3
