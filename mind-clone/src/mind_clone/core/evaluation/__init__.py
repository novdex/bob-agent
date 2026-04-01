"""
Evaluation package -- continuous eval suite and release gate.

Re-exports everything for backward compatibility so that existing
``from ..core.evaluation import X`` imports continue to work.
"""

from .cases import (
    bfcl_01_correct_tool_selection,
    bfcl_02_argument_extraction,
    bfcl_03_multi_tool_chaining,
    bfcl_04_parallel_tool_calls,
    bfcl_05_error_recovery,
    bfcl_06_schema_validation,
    bfcl_07_nested_function_calls,
    bfcl_08_optional_parameter_handling,
    bfcl_09_type_coercion,
    bfcl_10_ambiguous_intent_routing,
    bfcl_11_tool_call_id_format,
    bfcl_12_empty_result_handling,
    bfcl_13_tool_timeout_behavior,
    gaia_01_multi_step_math,
    gaia_02_datetime_calculation,
    gaia_03_text_summarization_quality,
    gaia_04_instruction_following,
    gaia_05_common_sense_reasoning,
    gaia_06_spatial_reasoning,
    gaia_07_causal_reasoning,
    gaia_08_analogical_reasoning,
    gaia_09_multi_constraint_satisfaction,
    fortress_01_prompt_injection_detection,
    fortress_02_secret_redaction,
    fortress_03_sql_injection_prevention,
    fortress_04_path_traversal_blocking,
    fortress_05_command_injection_prevention,
    fortress_06_rate_limit_enforcement,
    fortress_07_approval_gate,
    fortress_08_sandbox_escape_prevention,
    fortress_09_pii_detection,
    fortress_10_token_budget_enforcement,
    fortress_11_cross_owner_isolation,
    vending_01_budget_governor_stops_at_limits,
    vending_02_circuit_breaker_trips_and_recovers,
    vending_03_tool_timeout_handling,
    vending_04_graceful_degradation_under_load,
    vending_05_retry_logic_with_backoff,
    vending_06_error_recovery_without_data_loss,
    context_bench_01_trim_preserves_tool_pairs,
    context_bench_02_long_conversation_compression,
    context_bench_03_memory_relevance_scoring,
    t2_bench_01_intent_filter,
    t2_bench_02_perf_tracking,
    t2_bench_03_dispatch_routing,
    terminal_bench_01_run_command_timeout,
    terminal_bench_02_execute_python_sandboxing,
)

from .scoring import (
    BFCL_CASES,
    GAIA_CASES,
    FORTRESS_CASES,
    VENDING_CASES,
    CONTEXT_BENCH_CASES,
    T2_BENCH_CASES,
    TERMINAL_BENCH_CASES,
    ALL_CASES,
    _BENCHMARK_REGISTRY,
)

from .runner import (
    run_continuous_eval_suite,
    evaluate_release_gate,
)

from .reporting import (
    format_eval_summary,
    build_benchmark_report,
)

__all__ = [
    "run_continuous_eval_suite",
    "evaluate_release_gate",
    "format_eval_summary",
    "build_benchmark_report",
    "BFCL_CASES",
    "GAIA_CASES",
    "FORTRESS_CASES",
    "VENDING_CASES",
    "CONTEXT_BENCH_CASES",
    "T2_BENCH_CASES",
    "TERMINAL_BENCH_CASES",
    "ALL_CASES",
]
