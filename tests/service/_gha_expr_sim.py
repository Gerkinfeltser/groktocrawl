"""Tiny simulator for the GitHub Actions expression subset used by gate `if:`s.

Supported: parentheses, ``!``/``&&``/``||``, dotted context names (hyphenated
job ids become underscores), the literals ``true``/``false``/``null``, single
quoted strings, ``format()``, ``always()``, and LOOSE EQUALITY with numeric
coercion (Null->0, Boolean false->0, Boolean true->1; non-numeric strings
never equal a number). Truthiness follows the documented falsy set
(null/false/''/0). Semantics per the official expressions reference ("Loose
equality comparisons") and actions/runner
``src/Sdk/Expressions/EvaluationResult.cs`` ``ConvertToNumber`` (null=0d,
false=0d).

Why this exists: PR #604 shipped ``.github/workflows/docker.yml`` conditions
built on the wrong premise that ``null != false`` is TRUE. Under loose
equality it is FALSE, so a deleted-fork PR (``head.repo.fork == null``)
skipped the fork-PR detector AND was admitted onto the self-hosted lane by
``fork == false`` (#562 scrutiny round 1, corrected 2026-08-24). The
workflow-condition contract tests evaluate the ACTUAL ``if:`` text from
docker.yml against these semantics, so a similar inversion cannot land again
without a failing test.
"""

from __future__ import annotations

import math
import re
from types import SimpleNamespace

_LITERAL_RE = re.compile(r"\b(true|false|null)\b")
_QUOTED_RE = re.compile(r"'[^']*'")
_HYPHEN_RE = re.compile(r"(?<=[\w.])-(?=[\w.])")
_LITERALS = {
    "true": "GhaScalar(True)",
    "false": "GhaScalar(False)",
    "null": "GhaScalar(None)",
}


class GhaScalar:
    """A GitHub-Actions scalar whose ``==`` models loose (numeric) equality."""

    __slots__ = ("raw",)

    def __init__(self, raw: object) -> None:
        self.raw = raw

    def _as_number(self) -> float:
        raw = self.raw
        if raw is None or raw is False:
            return 0.0
        if raw is True:
            return 1.0
        if isinstance(raw, (int, float)):
            return float(raw)
        try:
            return float(str(raw))
        except ValueError:
            return float("nan")  # non-numeric strings never equal a number

    def __eq__(self, other: object) -> bool:
        if isinstance(other, GhaScalar):
            mine = self._as_number()
            theirs = other._as_number()
            # NaN (coerced non-numeric strings, raw NaN) never equals anything
            # — including another NaN. Python's IEEE `float ==` already
            # provides this; the explicit guard keeps the contract independent
            # of that accident (#562 round 2).
            if math.isnan(mine) or math.isnan(theirs):
                return False
            return mine == theirs
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        equal = self.__eq__(other)
        if equal is NotImplemented:
            return equal
        return not equal

    def __bool__(self) -> bool:
        # Runner IsTruthy falsifies only null, Boolean false, the EMPTY
        # string, and number zero. Strings '0' and 'false' are TRUTHY
        # (JavaScript-style string-zero falsiness is NOT GHA semantics;
        # corrected #562 round 2).
        raw = self.raw
        if raw is None or raw is False or raw == "":
            return False
        return bool(raw)

    def __hash__(self) -> int:
        return hash(("GhaScalar", self._as_number()))

    def __repr__(self) -> str:
        return f"GhaScalar({self.raw!r})"


def gha_render(value: object) -> str:
    """Render a scalar the way GHA string interpolation does."""
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def gha_format(template: str, *args: object) -> str:
    """Mirror GHA ``format()``: positional ``{N}`` substitution; null -> ''."""
    rendered = []
    for arg in args:
        raw = arg.raw if isinstance(arg, GhaScalar) else arg
        rendered.append(gha_render(raw))
    return template.format(*rendered)


def namespace(mapping: dict[str, object]) -> SimpleNamespace:
    """Expose a dict as attribute access; hyphens become underscores (job ids)."""

    def convert(value: object) -> object:
        if isinstance(value, dict):
            return namespace(value)
        return value

    return SimpleNamespace(
        **{key.replace("-", "_"): convert(val) for key, val in mapping.items()}
    )


def _prepare_context(variables: dict[str, object]) -> dict[str, object]:
    """Convert nested context dicts to attribute access (recursively)."""
    prepared: dict[str, object] = {}
    for key, value in variables.items():
        prepared[key] = namespace(value) if isinstance(value, dict) else value
    return prepared


def _segments_outside_quotes(expression: str) -> list[tuple[str, bool]]:
    """Split into ``(segment, is_quoted)`` chunks preserving quoted strings."""
    parts: list[tuple[str, bool]] = []
    pos = 0
    for match in _QUOTED_RE.finditer(expression):
        if match.start() > pos:
            parts.append((expression[pos : match.start()], False))
        parts.append((match.group(0), True))
        pos = match.end()
    if pos < len(expression):
        parts.append((expression[pos:], False))
    return parts


def _to_python(segment: str) -> str:
    segment = _LITERAL_RE.sub(lambda m: _LITERALS[m.group(1)], segment)
    segment = segment.replace("&&", " and ").replace("||", " or ")
    segment = re.sub(r"!(?!=)", " not ", segment)
    # Job ids contain hyphens (needs.build-and-push.result); Python names
    # cannot, so mirror them to underscores inside dotted names.
    segment = _HYPHEN_RE.sub("_", segment)
    return segment


def gha_eval(expression: str, variables: dict[str, object]) -> object:
    """Evaluate a GHA expression subset against ``variables`` (GHA semantics).

    ``variables`` maps top-level context names (``github``, ``needs``, ...) to
    nested dicts (converted with :func:`namespace`), plus callables such as
    ``always``. Tri-state values that participate in equality (e.g. the fork
    flag) must be wrapped in :class:`GhaScalar` by the caller.
    """
    python_expr = "".join(
        segment if quoted else _to_python(segment)
        for segment, quoted in _segments_outside_quotes(expression)
    )
    env: dict[str, object] = {"GhaScalar": GhaScalar, "format": gha_format}
    env.update(_prepare_context(variables))
    # The expression text is repo-owned workflow configuration read by the
    # contract tests, not untrusted input; eval is restricted to a minimal
    # environment with no builtins.
    return eval(python_expr, {"__builtins__": {}}, env)
