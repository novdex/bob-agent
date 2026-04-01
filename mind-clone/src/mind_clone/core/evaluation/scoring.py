"""
Eval case registries and benchmark organization.

Maps case names to their callable functions, grouped by benchmark.
Provides the combined registry and flat ALL_CASES list used by the runner.
"""

from __future__ import annotations

from typing import Callable, List, Tuple

from .cases import (
    # BFCL cases
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
    # GAIA cases
    gaia_01_multi_step_math,
    gaia_02_datetime_calculation,
    gaia_03_text_summarization_quality,
    gaia_04_instruction_following,
    gaia_05_common_sense_reasoning,
    gaia_06_spatial_reasoning,
    gaia_07_causal_reasoning,
    gaia_08_analogical_reasoning,
    gaia_09_multi_constraint_satisfaction,
    # FORTRESS cases
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
    # Vending-Bench cases
    vending_01_budget_governor_stops_at_limits,
    vending_02_circuit_breaker_trips_and_recovers,
    vending_03_tool_timeout_handling,
    vending_04_graceful_degradation_under_load,
    vending_05_retry_logic_with_backoff,
    vending_06_error_recovery_without_data_loss,
    # Context-Bench cases
    context_bench_01_trim_preserves_tool_pairs,
    context_bench_02_long_conversation_compression,
    context_bench_03_memory_relevance_scoring,
    # t2-bench cases
    t2_bench_01_intent_filter,
    t2_bench_02_perf_tracking,
    t2_bench_03_dispatch_routing,
    # Terminal-Bench cases
    terminal_bench_01_run_command_timeout,
    terminal_bench_02_execute_python_sandboxing,
)


# =============================================================================
# Eval Case Registries
# =============================================================================

BFCL_CASES: List[Tuple[str, Callable[[], Tuple[bool, str]]]] = [
    ("bfcl_01_correct_tool_selection", bfcl_01_correct_tool_selection),
    ("bfcl_02_argument_extraction", bfcl_02_argument_extraction),
    ("bfcl_03_multi_tool_chaining", bfcl_03_multi_tool_chaining),
    ("bfcl_04_parallel_tool_calls", bfcl_04_parallel_tool_calls),
    ("bfcl_05_error_recovery", bfcl_05_error_recovery),
    ("bfcl_06_schema_validation", bfcl_06_schema_validation),
    ("bfcl_07_nested_function_calls", bfcl_07_nested_function_calls),
    ("bfcl_08_optional_parameter_handling", bfcl_08_optional_parameter_handling),
    ("bfcl_09_type_coercion", bfcl_09_type_coercion),
    ("bfcl_10_ambiguous_intent_routing", bfcl_10_ambiguous_intent_routing),
    ("bfcl_11_tool_call_id_format", bfcl_11_tool_call_id_format),
    ("bfcl_12_empty_result_handling", bfcl_12_empty_result_handling),
    ("bfcl_13_tool_timeout_behavior", bfcl_13_tool_timeout_behavior),
]

GAIA_CASES: List[Tuple[str, Callable[[], Tuple[bool, str]]]] = [
    ("gaia_01_multi_step_math", gaia_01_multi_step_math),
    ("gaia_02_datetime_calculation", gaia_02_datetime_calculation),
    ("gaia_03_text_summarization_quality", gaia_03_text_summarization_quality),
    ("gaia_04_instruction_following", gaia_04_instruction_following),
    ("gaia_05_common_sense_reasoning", gaia_05_common_sense_reasoning),
    ("gaia_06_spatial_reasoning", gaia_06_spatial_reasoning),
    ("gaia_07_causal_reasoning", gaia_07_causal_reasoning),
    ("gaia_08_analogical_reasoning", gaia_08_analogical_reasoning),
    ("gaia_09_multi_constraint_satisfaction", gaia_09_multi_constraint_satisfaction),
]

FORTRESS_CASES: List[Tuple[str, Callable[[], Tuple[bool, str]]]] = [
    ("fortress_01_prompt_injection_detection", fortress_01_prompt_injection_detection),
    ("fortress_02_secret_redaction", fortress_02_secret_redaction),
    ("fortress_03_sql_injection_prevention", fortress_03_sql_injection_prevention),
    ("fortress_04_path_traversal_blocking", fortress_04_path_traversal_blocking),
    ("fortress_05_command_injection_prevention", fortress_05_command_injection_prevention),
    ("fortress_06_rate_limit_enforcement", fortress_06_rate_limit_enforcement),
    ("fortress_07_approval_gate", fortress_07_approval_gate),
    ("fortress_08_sandbox_escape_prevention", fortress_08_sandbox_escape_prevention),
    ("fortress_09_pii_detection", fortress_09_pii_detection),
    ("fortress_10_token_budget_enforcement", fortress_10_token_budget_enforcement),
    ("fortress_11_cross_owner_isolation", fortress_11_cross_owner_isolation),
]

VENDING_CASES: List[Tuple[str, Callable[[], Tuple[bool, str]]]] = [
    ("vending_01_budget_governor_stops_at_limits", vending_01_budget_governor_stops_at_limits),
    ("vending_02_circuit_breaker_trips_and_recovers", vending_02_circuit_breaker_trips_and_recovers),
    ("vending_03_tool_timeout_handling", vending_03_tool_timeout_handling),
    ("vending_04_graceful_degradation_under_load", vending_04_graceful_degradation_under_load),
    ("vending_05_retry_logic_with_backoff", vending_05_retry_logic_with_backoff),
    ("vending_06_error_recovery_without_data_loss", vending_06_error_recovery_without_data_loss),
]

CONTEXT_BENCH_CASES: List[Tuple[str, Callable[[], Tuple[bool, str]]]] = [
    ("context_bench_01_trim_preserves_tool_pairs", context_bench_01_trim_preserves_tool_pairs),
    ("context_bench_02_long_conversation_compression", context_bench_02_long_conversation_compression),
    ("context_bench_03_memory_relevance_scoring", context_bench_03_memory_relevance_scoring),
]

T2_BENCH_CASES: List[Tuple[str, Callable[[], Tuple[bool, str]]]] = [
    ("t2_bench_01_intent_filter", t2_bench_01_intent_filter),
    ("t2_bench_02_perf_tracking", t2_bench_02_perf_tracking),
    ("t2_bench_03_dispatch_routing", t2_bench_03_dispatch_routing),
]

TERMINAL_BENCH_CASES: List[Tuple[str, Callable[[], Tuple[bool, str]]]] = [
    ("terminal_bench_01_run_command_timeout", terminal_bench_01_run_command_timeout),
    ("terminal_bench_02_execute_python_sandboxing", terminal_bench_02_execute_python_sandboxing),
]

# Combined registry of all benchmarks: (benchmark_name, case_list)
_BENCHMARK_REGISTRY: List[Tuple[str, List[Tuple[str, Callable[[], Tuple[bool, str]]]]]] = [
    ("BFCL", BFCL_CASES),
    ("GAIA", GAIA_CASES),
    ("FORTRESS", FORTRESS_CASES),
    ("Vending-Bench", VENDING_CASES),
    ("Context-Bench", CONTEXT_BENCH_CASES),
    ("t2-bench", T2_BENCH_CASES),
    ("Terminal-Bench", TERMINAL_BENCH_CASES),
]

# Flat list of all eval cases across all benchmarks
ALL_CASES: List[Tuple[str, Callable[[], Tuple[bool, str]]]] = [
    case for _, cases in _BENCHMARK_REGISTRY for case in cases
]
