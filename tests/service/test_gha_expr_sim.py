"""Fidelity tests for the GHA expression simulator's scalar semantics (#562).

``tests/service/_gha_expr_sim.py`` backs the workflow-condition contract
tests; its :class:`~tests.service._gha_expr_sim.GhaScalar` must track
actions/runner semantics, not Python accidents. The two fidelity edge cases
pinned here are unreachable from the current workflow pins, so tightening
them cannot shift those pins' outcomes:

- **NaN equality**: a non-numeric string coerces to NaN in ``_as_number``, and
  NaN never equals ANYTHING -- including another NaN. The explicit
  ``math.isnan`` guard in ``__eq__`` keeps that guarantee independent of the
  Python ``float ==`` accident (IEEE NaN != NaN) that previously supplied it.
- **Truthiness**: actions/runner ``IsTruthy`` falsifies only null, Boolean
  false, the EMPTY string, and number zero. String ``'0'`` and ``'false'``
  are TRUTHY; the previous ``raw not in ("", "0")`` check wrongly made string
  ``'0'`` falsy (a JavaScript-flavored mistake GHA does not share).
"""

from __future__ import annotations

import math

from tests.service._gha_expr_sim import GhaScalar, gha_eval


class TestNanEquality:
    """Non-numeric strings coerce to NaN, and NaN never equals anything."""

    def test_non_numeric_string_never_equals_itself(self) -> None:
        # Direct __eq__ call: the NaN guard returns False, never NotImplemented.
        assert GhaScalar("abc").__eq__(GhaScalar("abc")) is False
        assert GhaScalar("abc") != GhaScalar("abc")

    def test_distinct_unparseable_strings_are_unequal_both_ways(self) -> None:
        assert GhaScalar("abc") != GhaScalar("xyz")
        assert GhaScalar("xyz") != GhaScalar("abc")

    def test_nan_bearing_scalar_never_equals_a_number(self) -> None:
        assert GhaScalar("abc") != GhaScalar(5)
        assert GhaScalar(5) != GhaScalar("abc")
        assert GhaScalar("abc").__eq__(GhaScalar(5)) is False

    def test_raw_nan_value_never_equals_itself(self) -> None:
        nan = float("nan")
        assert math.isnan(nan)
        assert GhaScalar(nan) != GhaScalar(nan)

    def test_eq_against_plain_python_values_stays_not_implemented(self) -> None:
        # Quoted literals in an expression stay plain Python strs; the
        # format()-rendered comparisons rely on the NotImplemented fallback
        # (reflected str.__eq__) rather than numeric coercion.
        assert GhaScalar("abc").__eq__("abc") is NotImplemented

    def test_numeric_coercion_semantics_are_unchanged(self) -> None:
        # Core loose-equality behaviors the existing pins depend on.
        assert GhaScalar(2) == GhaScalar(2.0)
        assert GhaScalar("3") == GhaScalar(3)  # parseable string coerces
        assert GhaScalar(None) == GhaScalar(False)  # Null->0, false->0
        assert GhaScalar(True) == GhaScalar(1)
        assert GhaScalar(True).__eq__(GhaScalar(1)) is True


class TestTruthiness:
    """Only null/false/empty-string/number-zero are falsy (runner IsTruthy)."""

    def test_string_zero_is_truthy(self) -> None:
        # Changed in #562 round 2: the old `raw not in ("", "0")` made the
        # string '0' falsy, but GHA only falsifies the EMPTY string.
        assert bool(GhaScalar("0"))

    def test_string_false_is_truthy(self) -> None:
        assert bool(GhaScalar("false"))

    def test_empty_string_is_falsy(self) -> None:
        assert not bool(GhaScalar(""))

    def test_null_and_boolean_false_are_falsy_true_is_truthy(self) -> None:
        assert not bool(GhaScalar(None))
        assert not bool(GhaScalar(False))
        assert bool(GhaScalar(True))

    def test_number_zero_is_falsy(self) -> None:
        assert not bool(GhaScalar(0))
        assert not bool(GhaScalar(0.0))

    def test_nonzero_numbers_and_nan_number_are_truthy(self) -> None:
        assert bool(GhaScalar(5))
        assert bool(GhaScalar(0.5))
        # Runner IsTruthy: NaN != 0d, so a NaN NUMBER is truthy (distinct
        # from the NaN-equality rule, which forbids == entirely).
        assert bool(GhaScalar(float("nan")))

    def test_non_empty_strings_are_truthy(self) -> None:
        assert bool(GhaScalar("abc"))
        assert bool(GhaScalar(" "))

    def test_string_zero_flips_logical_evaluation_through_gha_eval(self) -> None:
        # End-to-end through the evaluator: with the old falsy-'0' bug the
        # `&&` chain short-circuited onto the falsy scalar; now it yields the
        # right-hand operand, matching runner semantics.
        result = gha_eval("flag && 'taken'", {"flag": GhaScalar("0")})
        assert result == "taken"

    def test_nan_operands_flow_through_gha_eval_unequal(self) -> None:
        ctx: dict[str, object] = {
            "a": GhaScalar("abc"),
            "b": GhaScalar("abc"),
        }
        assert not bool(gha_eval("a == b", ctx))
        assert bool(gha_eval("a != b", ctx))

    def test_string_zero_is_truthy_through_gha_eval_not_operator(self) -> None:
        # The runner falsifies only null/false/''/0(number); `!` over the
        # string '0' must be False now that __bool__ matches IsTruthy.
        assert not bool(gha_eval("!flag", {"flag": GhaScalar("0")}))
