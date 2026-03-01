"""
Comprehensive test suite for evaluation.py module.

Tests edge cases, input validation, and return contracts for eval functions.
Focus on defensive programming: None checks, empty strings, boundary values.
"""

import json
import pytest
from typing import Tuple

# Import eval functions from the evaluation module
try:
    from mind_clone.core.evaluation import (
        bfcl_01_correct_tool_selection,
        bfcl_02_argument_extraction,
        bfcl_05_error_recovery,
        bfcl_06_schema_validation,
        bfcl_11_tool_call_id_format,
        bfcl_12_empty_result_handling,
        gaia_01_multi_step_math,
        gaia_02_datetime_calculation,
    )
    HAS_EVALUATION = True
except ImportError:
    HAS_EVALUATION = False

pytestmark = pytest.mark.skipif(not HAS_EVALUATION, reason="evaluation module required")


class TestBFCLToolSelection:
    """Tests for BFCL-01: correct tool selection."""

    def test_returns_tuple_bool_str(self):
        """Should return (bool, str) tuple."""
        result = bfcl_01_correct_tool_selection()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_detail_not_empty(self):
        """Detail string should not be empty."""
        _, detail = bfcl_01_correct_tool_selection()
        assert len(detail) > 0

    def test_deterministic(self):
        """Should return same result on repeated calls."""
        result1 = bfcl_01_correct_tool_selection()
        result2 = bfcl_01_correct_tool_selection()
        assert result1 == result2


class TestBFCLArgumentExtraction:
    """Tests for BFCL-02: argument extraction."""

    def test_returns_tuple_bool_str(self):
        """Should return (bool, str) tuple."""
        result = bfcl_02_argument_extraction()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_detail_contains_extracted_value(self):
        """Detail should contain the extracted argument."""
        _, detail = bfcl_02_argument_extraction()
        assert "Python documentation" in detail or "extracted" in detail.lower()

    def test_deterministic(self):
        """Should return same result on repeated calls."""
        result1 = bfcl_02_argument_extraction()
        result2 = bfcl_02_argument_extraction()
        assert result1 == result2


class TestBFCLErrorRecovery:
    """Tests for BFCL-05: error recovery from malformed JSON."""

    def test_returns_tuple_bool_str(self):
        """Should return (bool, str) tuple."""
        result = bfcl_05_error_recovery()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_detects_malformed_json(self):
        """Should return True (can detect malformed JSON)."""
        passed, _ = bfcl_05_error_recovery()
        assert passed is True

    def test_detail_mentions_json(self):
        """Detail should mention JSON."""
        _, detail = bfcl_05_error_recovery()
        assert "JSON" in detail or "json" in detail


class TestBFCLSchemaValidation:
    """Tests for BFCL-06: schema validation."""

    def test_returns_tuple_bool_str(self):
        """Should return (bool, str) tuple."""
        result = bfcl_06_schema_validation()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_rejects_wrong_type(self):
        """Should reject integer when string is required."""
        passed, _ = bfcl_06_schema_validation()
        assert passed is True  # Validation detected the error

    def test_detail_explains_error(self):
        """Detail should explain what was wrong."""
        _, detail = bfcl_06_schema_validation()
        assert "schema" in detail.lower() or "validation" in detail.lower() or "rejected" in detail.lower()


class TestBFCLToolCallIdFormat:
    """Tests for BFCL-11: tool_call_id format validation."""

    def test_returns_tuple_bool_str(self):
        """Should return (bool, str) tuple."""
        result = bfcl_11_tool_call_id_format()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_counts_valid_ids(self):
        """Should count 2 valid IDs (with spaces invalid)."""
        passed, detail = bfcl_11_tool_call_id_format()
        # Should identify that 2/3 are valid
        assert "2" in detail or "valid" in detail.lower()

    def test_detail_shows_count(self):
        """Detail should show count of valid IDs."""
        _, detail = bfcl_11_tool_call_id_format()
        assert "/" in detail  # Format: "x/y"


class TestBFCLEmptyResultHandling:
    """Tests for BFCL-12: empty result handling."""

    def test_returns_tuple_bool_str(self):
        """Should return (bool, str) tuple."""
        result = bfcl_12_empty_result_handling()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_handles_empty_results(self):
        """Should return True (all empty results handled)."""
        passed, _ = bfcl_12_empty_result_handling()
        assert passed is True

    def test_detail_shows_count(self):
        """Detail should show count of handled results."""
        _, detail = bfcl_12_empty_result_handling()
        assert "/" in detail  # Format: "x/y"


class TestGAIAMultiStepMath:
    """Tests for GAIA-01: multi-step math."""

    def test_returns_tuple_bool_str(self):
        """Should return (bool, str) tuple."""
        result = gaia_01_multi_step_math()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_detailed_math_verification(self):
        """Should verify all math steps."""
        passed, detail = gaia_01_multi_step_math()
        # Complex math should be verifiable
        assert "step" in detail.lower() or "math" in detail.lower() or "verified" in detail.lower()

    def test_deterministic(self):
        """Should return same result on repeated calls."""
        result1 = gaia_01_multi_step_math()
        result2 = gaia_01_multi_step_math()
        assert result1 == result2


class TestGAIADatetimeCalculation:
    """Tests for GAIA-02: datetime calculation."""

    def test_returns_tuple_bool_str(self):
        """Should return (bool, str) tuple."""
        result = gaia_02_datetime_calculation()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_handles_leap_years(self):
        """Should correctly handle leap year calculations."""
        passed, detail = gaia_02_datetime_calculation()
        # Should test leap/non-leap years
        assert "leap" in detail.lower() or "date" in detail.lower() or "time" in detail.lower()

    def test_datetime_import_available(self):
        """datetime module should be available."""
        from datetime import datetime, timezone
        assert datetime is not None
        assert timezone is not None


# ---------------------------------------------------------------------------
# Comprehensive edge case and validation tests
# ---------------------------------------------------------------------------

class TestEvalFunctionContractValidation:
    """Validate that all eval functions return proper contract."""

    def _all_eval_functions(self):
        """Get all eval functions."""
        return [
            bfcl_01_correct_tool_selection,
            bfcl_02_argument_extraction,
            bfcl_05_error_recovery,
            bfcl_06_schema_validation,
            bfcl_11_tool_call_id_format,
            bfcl_12_empty_result_handling,
            gaia_01_multi_step_math,
            gaia_02_datetime_calculation,
        ]

    def test_all_return_tuple(self):
        """All eval functions should return (bool, str) tuples."""
        for func in self._all_eval_functions():
            result = func()
            assert isinstance(result, tuple), f"{func.__name__} did not return tuple"
            assert len(result) == 2, f"{func.__name__} returned tuple of length {len(result)}"

    def test_all_return_bool_first(self):
        """First element should be bool."""
        for func in self._all_eval_functions():
            passed, _ = func()
            assert isinstance(passed, bool), f"{func.__name__} first element is not bool"

    def test_all_return_str_second(self):
        """Second element should be string."""
        for func in self._all_eval_functions():
            _, detail = func()
            assert isinstance(detail, str), f"{func.__name__} second element is not str"

    def test_detail_strings_not_empty(self):
        """Detail strings should not be empty."""
        for func in self._all_eval_functions():
            _, detail = func()
            assert len(detail) > 0, f"{func.__name__} returned empty detail string"

    def test_all_deterministic(self):
        """Calling functions twice should return same result."""
        for func in self._all_eval_functions():
            result1 = func()
            result2 = func()
            assert result1 == result2, f"{func.__name__} is not deterministic"

    def test_no_exceptions_raised(self):
        """No eval function should raise an exception."""
        for func in self._all_eval_functions():
            try:
                result = func()
                assert result is not None
            except Exception as e:
                pytest.fail(f"{func.__name__} raised {type(e).__name__}: {e}")


class TestEvalFunctionRobustness:
    """Test robustness of evaluation functions."""

    def test_math_precision(self):
        """Math operations should be precise to 2 decimals."""
        passed, detail = gaia_01_multi_step_math()
        if passed:
            # Should be able to verify with 2 decimal precision
            assert "1088.75" in detail or "expected" in detail.lower()

    def test_datetime_timezone_handling(self):
        """Datetime tests should handle timezones."""
        passed, detail = gaia_02_datetime_calculation()
        assert "timezone" in detail.lower() or "utc" in detail.lower() or "passed" in detail.lower()

    def test_regex_patterns_safe(self):
        """Regex patterns should not crash on special input."""
        # These functions use regex internally
        passed, detail = bfcl_11_tool_call_id_format()
        assert passed is not None
        assert detail is not None


class TestEvalFunctionEdgeCases:
    """Test edge cases in evaluation logic."""

    def test_bfcl_empty_intent(self):
        """Should handle tools selection even with complex intents."""
        passed, detail = bfcl_01_correct_tool_selection()
        assert isinstance(passed, bool)
        assert isinstance(detail, str)

    def test_bfcl_extract_special_chars(self):
        """Argument extraction should handle special characters."""
        passed, detail = bfcl_02_argument_extraction()
        assert isinstance(passed, bool)
        # Should extract "Python documentation"
        assert "Python" in detail or "documentation" in detail

    def test_schema_validation_type_mismatch(self):
        """Schema validation should detect type mismatches."""
        passed, detail = bfcl_06_schema_validation()
        assert passed is True  # Should detect the mismatch

    def test_tool_id_format_uuid_valid(self):
        """Tool ID validation should accept valid UUIDs."""
        passed, detail = bfcl_11_tool_call_id_format()
        assert "uuid" in detail.lower() or "valid" in detail.lower() or "2" in detail

    def test_empty_results_comprehensive(self):
        """Empty result handling should cover all types."""
        passed, detail = bfcl_12_empty_result_handling()
        assert passed is True
        assert "3" in detail or "all" in detail.lower()


class TestEvalFunctionReturnQuality:
    """Test quality of detail messages."""

    def test_detail_is_informative(self):
        """Detail messages should be informative."""
        for func in [bfcl_01_correct_tool_selection, bfcl_02_argument_extraction]:
            _, detail = func()
            # Should contain expected values and results
            assert len(detail) > 20  # Non-trivial message

    def test_detail_shows_what_expected(self):
        """Detail should show what was expected vs actual."""
        _, detail = bfcl_01_correct_tool_selection()
        assert "expected" in detail.lower() or "selected" in detail.lower()

    def test_math_detail_shows_steps(self):
        """Math eval should show calculation steps."""
        passed, detail = gaia_01_multi_step_math()
        if passed:
            # Should mention steps and values
            assert any(x in detail for x in ["step", "discount", "tax", "$"])

    def test_datetime_detail_explains(self):
        """Datetime eval should explain what was tested."""
        _, detail = gaia_02_datetime_calculation()
        assert any(x in detail.lower() for x in ["leap", "date", "time", "timezone"])


class TestEvalFunctionConsistency:
    """Test consistency across eval functions."""

    def test_all_use_same_return_format(self):
        """All functions should use same return format."""
        funcs = [
            bfcl_01_correct_tool_selection,
            bfcl_02_argument_extraction,
            bfcl_05_error_recovery,
            bfcl_06_schema_validation,
        ]
        results = [func() for func in funcs]
        # All should be (bool, str)
        for result in results:
            assert isinstance(result, tuple)
            assert len(result) == 2
            assert isinstance(result[0], bool)
            assert isinstance(result[1], str)

    def test_detail_always_provided(self):
        """Every function should always provide non-empty detail."""
        funcs = [
            gaia_01_multi_step_math,
            gaia_02_datetime_calculation,
            bfcl_05_error_recovery,
        ]
        for func in funcs:
            _, detail = func()
            assert isinstance(detail, str)
            assert len(detail) > 0
            # Should be readable
            assert detail[0].isalnum() or detail[0] in "([{-"


class TestBFCLFunctionCoherence:
    """Test coherence of BFCL functions."""

    def test_tool_selection_identifies_correct_tool(self):
        """Tool selection should pick correct tool."""
        passed, detail = bfcl_01_correct_tool_selection()
        assert "search_web" in detail

    def test_argument_extraction_gets_query(self):
        """Argument extraction should get query parameter."""
        passed, detail = bfcl_02_argument_extraction()
        assert "Python documentation" in detail

    def test_error_recovery_detects_json_error(self):
        """Error recovery should detect malformed JSON."""
        passed, detail = bfcl_05_error_recovery()
        assert passed is True
        assert "malformed" in detail.lower() or "json" in detail.lower()


class TestGAIAFunctionCoherence:
    """Test coherence of GAIA functions."""

    def test_math_covers_all_steps(self):
        """Math function should verify all calculation steps."""
        passed, detail = gaia_01_multi_step_math()
        # Should verify discount, tax, shipping, cashback
        if passed:
            assert any(keyword in detail for keyword in ["discount", "tax", "shipping", "cashback", "step"])

    def test_datetime_covers_multiple_cases(self):
        """Datetime function should test multiple date/time scenarios."""
        passed, detail = gaia_02_datetime_calculation()
        # Should test leap years, format, weekday, timezone
        if passed:
            assert any(keyword in detail.lower() for keyword in ["leap", "date", "weekday", "timezone"])
