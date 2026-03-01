"""
CI benchmark baseline tests (maps to all benchmarks — regression detection).

Covers: test count regression, module import health, eval framework readiness,
        tool registry size regression, closed-loop function availability,
        self-tune function availability, security function availability.

These tests verify structural invariants that should never regress.
Run in CI to catch accidental removals or import breakage.
"""

import pytest
import importlib


# ---------------------------------------------------------------------------
# Module import health (catches DLL/import errors early)
# ---------------------------------------------------------------------------

class TestModuleImportHealth:
    """All critical modules must import without error."""

    @pytest.mark.parametrize("module_path", [
        "mind_clone.config",
        "mind_clone.agent.loop",
        "mind_clone.agent.memory",
        "mind_clone.agent.identity",
        "mind_clone.agent.llm",
        "mind_clone.core.state",
        "mind_clone.core.security",
        "mind_clone.core.budget",
        "mind_clone.core.closed_loop",
        "mind_clone.core.self_tune",
        "mind_clone.core.evaluation",
        "mind_clone.core.queue",
        "mind_clone.core.approvals",
        "mind_clone.tools.registry",
        "mind_clone.tools.schemas",
        "mind_clone.database.models",
        "mind_clone.database.session",
        "mind_clone.api.factory",
    ])
    def test_module_imports(self, module_path):
        mod = importlib.import_module(module_path)
        assert mod is not None


# ---------------------------------------------------------------------------
# Tool registry size (maps to BFCL — must never shrink)
# ---------------------------------------------------------------------------

class TestToolRegistryBaseline:

    def test_minimum_45_tools(self):
        from mind_clone.tools.registry import TOOL_DISPATCH
        assert len(TOOL_DISPATCH) >= 45, (
            f"Tool registry shrank to {len(TOOL_DISPATCH)} — expected >= 45"
        )

    def test_core_tools_present(self):
        from mind_clone.tools.registry import TOOL_DISPATCH
        core = ["search_web", "read_webpage", "read_file", "write_file",
                "execute_python", "run_command", "deep_research"]
        for tool in core:
            assert tool in TOOL_DISPATCH, f"Core tool '{tool}' missing"

    def test_codebase_tools_present(self):
        from mind_clone.tools.registry import TOOL_DISPATCH
        codebase = ["codebase_read", "codebase_search", "codebase_structure",
                     "codebase_edit", "codebase_write"]
        for tool in codebase:
            assert tool in TOOL_DISPATCH, f"Codebase tool '{tool}' missing"

    def test_all_tools_callable(self):
        from mind_clone.tools.registry import TOOL_DISPATCH
        for name, func in TOOL_DISPATCH.items():
            assert callable(func), f"Tool '{name}' is not callable"


# ---------------------------------------------------------------------------
# Closed-loop functions (maps to Vending-Bench — must exist)
# ---------------------------------------------------------------------------

class TestClosedLoopBaseline:

    def test_all_6_loops_importable(self):
        from mind_clone.core.closed_loop import (
            cl_filter_tools_by_performance,
            cl_track_lesson_usage,
            cl_close_improvement_notes,
            cl_adjust_for_forecast_confidence,
            cl_check_dead_letter_pattern,
        )
        assert callable(cl_filter_tools_by_performance)
        assert callable(cl_track_lesson_usage)
        assert callable(cl_close_improvement_notes)
        assert callable(cl_adjust_for_forecast_confidence)
        assert callable(cl_check_dead_letter_pattern)

    def test_closed_loop_enabled_flag_exists(self):
        from mind_clone.core.closed_loop import CLOSED_LOOP_ENABLED
        assert isinstance(CLOSED_LOOP_ENABLED, bool)


# ---------------------------------------------------------------------------
# Self-tune functions (maps to Vending-Bench — must exist)
# ---------------------------------------------------------------------------

class TestSelfTuneBaseline:

    def test_all_4_tuners_importable(self):
        from mind_clone.core.self_tune import (
            st_tune_queue_mode,
            st_tune_session_budget,
            st_tune_workers,
            st_tune_budget_mode,
            st_self_tune,
        )
        assert callable(st_tune_queue_mode)
        assert callable(st_tune_session_budget)
        assert callable(st_tune_workers)
        assert callable(st_tune_budget_mode)
        assert callable(st_self_tune)

    def test_self_tune_enabled_flag_exists(self):
        from mind_clone.core.self_tune import SELF_TUNE_ENABLED
        assert isinstance(SELF_TUNE_ENABLED, bool)


# ---------------------------------------------------------------------------
# Security functions (maps to FORTRESS — must exist)
# ---------------------------------------------------------------------------

class TestSecurityBaseline:

    def test_security_functions_importable(self):
        from mind_clone.core.security import (
            check_tool_allowed,
            requires_approval,
            redact_secrets,
            evaluate_workspace_diff_gate,
            enforce_host_exec_interlock,
            validate_outbound_url,
            circuit_allow_call,
            circuit_record_success,
            circuit_record_failure,
            guarded_tool_result_payload,
        )
        for func in [check_tool_allowed, requires_approval, redact_secrets,
                      evaluate_workspace_diff_gate, enforce_host_exec_interlock,
                      validate_outbound_url, circuit_allow_call,
                      circuit_record_success, circuit_record_failure,
                      guarded_tool_result_payload]:
            assert callable(func)

    def test_safe_tool_names_not_empty(self):
        from mind_clone.core.security import SAFE_TOOL_NAMES
        assert len(SAFE_TOOL_NAMES) >= 5

    def test_policy_profiles_exist(self):
        from mind_clone.core.security import TOOL_POLICY_PROFILES
        assert "safe" in TOOL_POLICY_PROFILES
        assert "balanced" in TOOL_POLICY_PROFILES
        assert "power" in TOOL_POLICY_PROFILES


# ---------------------------------------------------------------------------
# Evaluation framework (maps to all — scaffold must exist)
# ---------------------------------------------------------------------------

class TestEvalBaseline:

    def test_eval_functions_importable(self):
        from mind_clone.core.evaluation import (
            run_continuous_eval_suite,
            evaluate_release_gate,
        )
        assert callable(run_continuous_eval_suite)
        assert callable(evaluate_release_gate)

    def test_eval_returns_required_keys(self):
        from mind_clone.core.evaluation import run_continuous_eval_suite
        result = run_continuous_eval_suite()
        for key in ("ok", "cases_run", "cases_passed", "cases_failed", "score"):
            assert key in result, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Budget governor (maps to Vending-Bench — must exist)
# ---------------------------------------------------------------------------

class TestBudgetBaseline:

    def test_budget_functions_importable(self):
        from mind_clone.core.budget import (
            RunBudget,
            create_run_budget,
            budget_should_stop,
            budget_should_degrade,
        )
        assert callable(create_run_budget)
        assert callable(budget_should_stop)
        assert callable(budget_should_degrade)


# ---------------------------------------------------------------------------
# Memory system (maps to Context-Bench — must exist)
# ---------------------------------------------------------------------------

class TestMemoryBaseline:

    def test_memory_functions_importable(self):
        from mind_clone.agent.memory import (
            save_user_message,
            save_assistant_message,
            save_tool_result,
            get_conversation_history,
            trim_context_window,
            store_lesson,
            search_memory_vectors,
            retrieve_relevant_artifacts,
        )
        for func in [save_user_message, save_assistant_message, save_tool_result,
                      get_conversation_history, trim_context_window, store_lesson,
                      search_memory_vectors, retrieve_relevant_artifacts]:
            assert callable(func)


# ---------------------------------------------------------------------------
# Agent loop (maps to GAIA — must exist)
# ---------------------------------------------------------------------------

class TestAgentLoopBaseline:

    def test_loop_functions_importable(self):
        from mind_clone.agent.loop import (
            _sanitize_tool_pairs,
            _classify_message_complexity,
            _context_top_k,
            build_system_prompt,
            MAX_TOOL_LOOPS,
        )
        assert callable(_sanitize_tool_pairs)
        assert callable(_classify_message_complexity)
        assert callable(_context_top_k)
        assert callable(build_system_prompt)
        assert MAX_TOOL_LOOPS >= 20

    def test_max_tool_loops_value(self):
        from mind_clone.agent.loop import MAX_TOOL_LOOPS
        assert MAX_TOOL_LOOPS == 50


# ---------------------------------------------------------------------------
# Approval system (maps to FORTRESS — must exist)
# ---------------------------------------------------------------------------

class TestApprovalBaseline:

    def test_approval_functions_importable(self):
        from mind_clone.core.approvals import (
            generate_approval_token,
            validate_approval_token,
            create_approval_request,
            decide_approval_token,
            list_pending_approvals,
        )
        for func in [generate_approval_token, validate_approval_token,
                      create_approval_request, decide_approval_token,
                      list_pending_approvals]:
            assert callable(func)
