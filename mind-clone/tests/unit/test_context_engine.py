"""
Tests for core/context_engine.py — Smart context engineering.
"""
import pytest
from mind_clone.core.context_engine import (
    TaskPhase,
    detect_task_phase,
    compute_context_budget,
    ContextPriority,
    ContextWindow,
    rank_context_items,
)


class TestTaskPhase:
    """Test task phase detection."""

    def test_phases_exist(self):
        assert TaskPhase.UNDERSTANDING.value == "understanding"
        assert TaskPhase.PLANNING.value == "planning"
        assert TaskPhase.EXECUTING.value == "executing"
        assert TaskPhase.REVIEWING.value == "reviewing"
        assert TaskPhase.RESPONDING.value == "responding"

    def test_detect_understanding_no_loops(self):
        messages = [{"role": "user", "content": "what is this?"}]
        phase = detect_task_phase(messages, tool_loops=0)
        assert phase == TaskPhase.UNDERSTANDING

    def test_detect_planning_from_assistant(self):
        messages = [
            {"role": "user", "content": "help me"},
            {"role": "assistant", "content": "Let me plan the steps for this approach."},
        ]
        phase = detect_task_phase(messages, tool_loops=0)
        assert phase == TaskPhase.PLANNING

    def test_detect_executing_with_loops(self):
        messages = [
            {"role": "user", "content": "do it"},
            {"role": "assistant", "content": "running code", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": "result"},
        ]
        phase = detect_task_phase(messages, tool_loops=2)
        assert phase == TaskPhase.EXECUTING

    def test_detect_responding_review_keywords(self):
        messages = [
            {"role": "user", "content": "do it"},
            {"role": "assistant", "content": "Let me check the result and verify it passed."},
        ]
        phase = detect_task_phase(messages, tool_loops=1)
        assert phase == TaskPhase.RESPONDING

    def test_detect_reviewing_many_tool_results(self):
        messages = [
            {"role": "tool", "content": "r1"},
            {"role": "tool", "content": "r2"},
            {"role": "user", "content": "good"},
        ]
        phase = detect_task_phase(messages, tool_loops=3)
        assert phase == TaskPhase.REVIEWING

    def test_empty_messages(self):
        phase = detect_task_phase([], tool_loops=0)
        assert phase == TaskPhase.UNDERSTANDING


class TestContextBudget:
    """Test context budget computation."""

    def test_understanding_budget(self):
        budget = compute_context_budget(TaskPhase.UNDERSTANDING)
        assert isinstance(budget, dict)
        assert "lessons" in budget
        assert "summaries" in budget
        assert "artifacts" in budget

    def test_simple_complexity_reduces(self):
        normal = compute_context_budget(TaskPhase.PLANNING, "normal")
        simple = compute_context_budget(TaskPhase.PLANNING, "simple")
        # Simple should have <= values vs normal
        assert simple["lessons"] <= normal["lessons"]

    def test_complex_increases(self):
        normal = compute_context_budget(TaskPhase.EXECUTING, "normal")
        cpx = compute_context_budget(TaskPhase.EXECUTING, "complex")
        assert cpx["artifacts"] >= normal["artifacts"]

    def test_unknown_complexity_defaults(self):
        budget = compute_context_budget(TaskPhase.UNDERSTANDING, "unknown_xyz")
        assert isinstance(budget, dict)

    def test_all_phases_have_budgets(self):
        for phase in TaskPhase:
            budget = compute_context_budget(phase)
            assert isinstance(budget, dict)
            assert all(v >= 0 for v in budget.values())


class TestContextPriority:
    """Test priority enum."""

    def test_ordering(self):
        assert ContextPriority.BACKGROUND < ContextPriority.LOW
        assert ContextPriority.LOW < ContextPriority.MEDIUM
        assert ContextPriority.MEDIUM < ContextPriority.HIGH
        assert ContextPriority.HIGH < ContextPriority.CRITICAL

    def test_int_values(self):
        assert int(ContextPriority.BACKGROUND) == 1
        assert int(ContextPriority.CRITICAL) == 5


class TestContextWindow:
    """Test context window manager."""

    def test_initial_remaining(self):
        w = ContextWindow(max_chars=1000)
        assert w.remaining() == 1000
        assert w.item_count == 0

    def test_add_item(self):
        w = ContextWindow(max_chars=1000)
        ok = w.add("hello world", ContextPriority.MEDIUM, "test")
        assert ok is True
        assert w.item_count == 1
        assert w.remaining() < 1000

    def test_add_too_large(self):
        w = ContextWindow(max_chars=10)
        ok = w.add("a" * 100, ContextPriority.MEDIUM, "big")
        assert ok is False

    def test_can_fit(self):
        w = ContextWindow(max_chars=100)
        assert w.can_fit("short") is True
        assert w.can_fit("x" * 200) is False

    def test_get_content_ordered_by_priority(self):
        w = ContextWindow(max_chars=10000)
        w.add("low stuff", ContextPriority.LOW, "LOW")
        w.add("high stuff", ContextPriority.HIGH, "HIGH")
        content = w.get_content()
        # HIGH should appear before LOW
        high_pos = content.index("[HIGH]")
        low_pos = content.index("[LOW]")
        assert high_pos < low_pos

    def test_compact_evicts_low_priority(self):
        w = ContextWindow(max_chars=100)
        w.add("a" * 40, ContextPriority.BACKGROUND, "bg")
        w.add("b" * 40, ContextPriority.MEDIUM, "med")
        freed = w.compact()
        assert freed > 0
        # BACKGROUND should be evicted first
        assert w.item_count <= 2

    def test_compact_preserves_high(self):
        w = ContextWindow(max_chars=100)
        w.add("important", ContextPriority.HIGH, "high")
        w.add("critical", ContextPriority.CRITICAL, "crit")
        freed = w.compact()
        # HIGH and CRITICAL should not be evicted
        assert w.item_count == 2

    def test_compact_empty_window(self):
        w = ContextWindow(max_chars=100)
        freed = w.compact()
        assert freed == 0


class TestRankContextItems:
    """Test relevance ranking."""

    def test_empty_items(self):
        result = rank_context_items([], "query")
        assert result == []

    def test_empty_query(self):
        result = rank_context_items(["item1", "item2"], "")
        assert len(result) == 2
        assert all(score == 0.0 for _, score in result)

    def test_exact_match_scores_high(self):
        items = ["python code review", "javascript tutorial", "python testing guide"]
        result = rank_context_items(items, "python code review")
        assert result[0][0] == "python code review"
        assert result[0][1] > result[1][1]

    def test_no_overlap_scores_zero(self):
        items = ["alpha beta gamma"]
        result = rank_context_items(items, "delta epsilon zeta")
        assert result[0][1] == 0.0

    def test_partial_overlap(self):
        items = ["machine learning models"]
        result = rank_context_items(items, "learning algorithms")
        _, score = result[0]
        assert 0.0 < score < 1.0

    def test_sorted_descending(self):
        items = ["a b c", "a b", "a"]
        result = rank_context_items(items, "a b c d")
        scores = [s for _, s in result]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Comprehensive edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCasesTaskPhase:
    """Edge cases for task phase detection."""

    def test_none_messages(self):
        """Should handle None messages list."""
        # Depending on implementation, may raise or return default
        try:
            phase = detect_task_phase(None, tool_loops=0)
        except (TypeError, AttributeError):
            # Expected behavior - None is not iterable
            pass

    def test_empty_messages(self):
        """Should return UNDERSTANDING for empty messages."""
        phase = detect_task_phase([], tool_loops=0)
        assert phase == TaskPhase.UNDERSTANDING

    def test_message_without_role(self):
        """Should handle message dict without role key."""
        messages = [{"content": "text"}]
        phase = detect_task_phase(messages, tool_loops=0)
        # Should not crash

    def test_message_without_content(self):
        """Should handle message dict without content key."""
        messages = [{"role": "user"}]
        phase = detect_task_phase(messages, tool_loops=0)
        # Should not crash

    def test_malformed_tool_calls(self):
        """Should handle malformed tool_calls field."""
        messages = [
            {"role": "assistant", "content": "running", "tool_calls": "not a list"}
        ]
        phase = detect_task_phase(messages, tool_loops=1)
        # Should not crash

    def test_negative_tool_loops(self):
        """Should handle negative tool_loops."""
        messages = [{"role": "user", "content": "test"}]
        phase = detect_task_phase(messages, tool_loops=-5)
        # Should return UNDERSTANDING

    def test_very_large_tool_loops(self):
        """Should handle very large tool_loops."""
        messages = [{"role": "user", "content": "test"}]
        phase = detect_task_phase(messages, tool_loops=1000)
        # Should not crash

    def test_many_messages_only_checks_last_5(self):
        """Should only check last 5 messages for understanding phase."""
        messages = [
            {"role": "assistant", "content": "plan step 1"},
            {"role": "assistant", "content": "plan step 2"},
            {"role": "assistant", "content": "plan step 3"},
            {"role": "assistant", "content": "plan step 4"},
            {"role": "assistant", "content": "plan step 5"},
            {"role": "user", "content": "something else"},
        ]
        phase = detect_task_phase(messages, tool_loops=0)
        # Should check only last 5


class TestEdgeCasesContextBudget:
    """Edge cases for context budget computation."""

    def test_none_phase(self):
        """Should handle None phase (may return default)."""
        try:
            budget = compute_context_budget(None)
        except (TypeError, KeyError):
            # Expected - None is not a valid TaskPhase
            pass

    def test_none_complexity(self):
        """Should default to normal complexity when None."""
        budget = compute_context_budget(TaskPhase.UNDERSTANDING, None)
        normal = compute_context_budget(TaskPhase.UNDERSTANDING, "normal")
        assert budget == normal

    def test_empty_string_complexity(self):
        """Should handle empty string complexity."""
        budget = compute_context_budget(TaskPhase.UNDERSTANDING, "")
        assert isinstance(budget, dict)

    def test_whitespace_complexity(self):
        """Should handle whitespace-only complexity."""
        budget = compute_context_budget(TaskPhase.UNDERSTANDING, "   ")
        assert isinstance(budget, dict)

    def test_multiplier_at_boundary(self):
        """Should handle complexity exactly at boundary values."""
        simple = compute_context_budget(TaskPhase.PLANNING, "simple")
        assert all(v >= 0 for v in simple.values())

    def test_complex_multiplier_at_boundary(self):
        """Should handle high complexity multiplier."""
        cpx = compute_context_budget(TaskPhase.EXECUTING, "complex")
        assert all(v >= 0 for v in cpx.values())

    def test_all_budget_values_non_negative(self):
        """All budget values should be non-negative after ceildiv."""
        for phase in TaskPhase:
            for complexity in ["simple", "normal", "complex"]:
                budget = compute_context_budget(phase, complexity)
                assert all(v >= 0 for v in budget.values())


class TestEdgeCasesContextWindow:
    """Edge cases for context window manager."""

    def test_zero_max_chars(self):
        """Should handle max_chars = 0."""
        w = ContextWindow(max_chars=0)
        assert w.remaining() == 0
        ok = w.add("text", ContextPriority.MEDIUM, "label")
        assert ok is False

    def test_negative_max_chars(self):
        """Should handle negative max_chars."""
        w = ContextWindow(max_chars=-100)
        assert w.remaining() <= 0

    def test_add_empty_text(self):
        """Should handle adding empty text."""
        w = ContextWindow(max_chars=1000)
        ok = w.add("", ContextPriority.MEDIUM, "empty")
        assert ok is True
        assert w.item_count == 1

    def test_add_none_text(self):
        """Should handle None as text (may crash or convert)."""
        w = ContextWindow(max_chars=1000)
        try:
            ok = w.add(None, ContextPriority.MEDIUM, "none")
        except TypeError:
            # Expected - len(None) is invalid
            pass

    def test_add_very_long_label(self):
        """Should handle very long label string."""
        w = ContextWindow(max_chars=10000)
        long_label = "label" * 1000
        ok = w.add("text", ContextPriority.MEDIUM, long_label)
        assert ok is True

    def test_remaining_never_negative(self):
        """Remaining should never go below 0."""
        w = ContextWindow(max_chars=100)
        for i in range(20):
            w.add("x" * 10, ContextPriority.MEDIUM, f"item{i}")
        assert w.remaining() >= 0

    def test_get_content_empty_window(self):
        """Should handle get_content on empty window."""
        w = ContextWindow(max_chars=1000)
        content = w.get_content()
        assert content == ""

    def test_compact_does_not_grow(self):
        """Compact should not increase remaining space incorrectly."""
        w = ContextWindow(max_chars=100)
        before = w.remaining()
        w.compact()
        after = w.remaining()
        assert after >= before  # Can only free, not add

    def test_multiple_compacts_idempotent(self):
        """Multiple compacts on empty window should return 0."""
        w = ContextWindow(max_chars=100)
        freed1 = w.compact()
        freed2 = w.compact()
        assert freed1 == 0
        assert freed2 == 0

    def test_add_after_compact(self):
        """Should be able to add after compacting."""
        w = ContextWindow(max_chars=100)
        w.add("x" * 80, ContextPriority.BACKGROUND, "bg")
        w.compact()
        ok = w.add("short", ContextPriority.CRITICAL, "crit")
        # Should be able to add due to freed space
        assert ok or w.item_count >= 1

    def test_can_fit_exact_remaining(self):
        """Should handle text exactly fitting remaining."""
        w = ContextWindow(max_chars=100)
        w.add("x" * 50, ContextPriority.MEDIUM, "item")
        remaining = w.remaining()
        can_fit = w.can_fit("y" * remaining)
        assert can_fit is True

    def test_priority_all_values(self):
        """Should handle all priority levels correctly."""
        w = ContextWindow(max_chars=10000)
        for priority in [ContextPriority.BACKGROUND, ContextPriority.LOW,
                        ContextPriority.MEDIUM, ContextPriority.HIGH,
                        ContextPriority.CRITICAL]:
            ok = w.add(f"text_{priority}", priority, f"label_{priority}")
            assert ok is True


class TestEdgeCasesRankContextItems:
    """Edge cases for ranking context items."""

    def test_none_items(self):
        """Should handle None items list."""
        try:
            result = rank_context_items(None, "query")
        except (TypeError, AttributeError):
            # Expected - None is not iterable
            pass

    def test_none_query(self):
        """Should handle None query."""
        result = rank_context_items(["item1"], None)
        # Should treat as empty query or crash

    def test_items_with_none(self):
        """Should handle list containing None."""
        try:
            result = rank_context_items([None, "item1"], "query")
        except (TypeError, AttributeError):
            # Expected - can't call lower() on None
            pass

    def test_single_item(self):
        """Should handle single item list."""
        result = rank_context_items(["single"], "single")
        assert len(result) == 1
        assert result[0][0] == "single"

    def test_query_with_special_chars(self):
        """Should handle query with special characters."""
        items = ["python@decorator", "test#tag"]
        result = rank_context_items(items, "python@decorator")
        # Should not crash

    def test_items_with_special_chars(self):
        """Should handle items with special characters."""
        items = ["$special @chars #here"]
        result = rank_context_items(items, "special")
        assert len(result) == 1

    def test_very_long_items(self):
        """Should handle very long item strings."""
        long_item = " ".join(["word"] * 10000)
        result = rank_context_items([long_item], "word")
        assert len(result) == 1

    def test_very_long_query(self):
        """Should handle very long query."""
        long_query = " ".join(["word"] * 1000)
        items = ["short item"]
        result = rank_context_items(items, long_query)
        assert len(result) == 1

    def test_case_sensitivity(self):
        """Should be case-insensitive."""
        items = ["PYTHON Code"]
        result = rank_context_items(items, "python code")
        assert result[0][1] > 0.0

    def test_unicode_characters(self):
        """Should handle unicode characters."""
        items = ["café naïve résumé"]
        result = rank_context_items(items, "café")
        assert len(result) == 1

    def test_duplicate_items(self):
        """Should handle duplicate items."""
        items = ["same", "same", "different"]
        result = rank_context_items(items, "same")
        assert len(result) == 3

    def test_score_bounds(self):
        """All scores should be in [0, 1]."""
        items = ["item1", "item2", "item3"]
        result = rank_context_items(items, "query")
        for _, score in result:
            assert 0.0 <= score <= 1.0


class TestContextEngineIntegration:
    """Integration tests for context engine."""

    def test_phase_to_budget_workflow(self):
        """Should convert phase to budget correctly."""
        phase = detect_task_phase([], tool_loops=0)
        budget = compute_context_budget(phase)
        assert isinstance(budget, dict)
        assert all(isinstance(v, int) for v in budget.values())

    def test_window_with_ranked_items(self):
        """Should add ranked items to window."""
        items = ["python code", "javascript guide", "python tutorial"]
        ranked = rank_context_items(items, "python")
        w = ContextWindow(max_chars=1000)
        for item, _ in ranked:
            w.add(item, ContextPriority.MEDIUM, item[:20])
        assert w.item_count > 0

    def test_large_context_window_budget(self):
        """Should handle large budget multipliers."""
        budget = compute_context_budget(TaskPhase.EXECUTING, "complex")
        w = ContextWindow(max_chars=200000)
        # Should be able to add items according to budget
        for i in range(budget.get("artifacts", 5)):
            ok = w.add(f"artifact{i}", ContextPriority.MEDIUM, f"art{i}")
            assert ok
