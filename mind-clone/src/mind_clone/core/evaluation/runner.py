"""
Eval suite runner and release gate.

Executes eval cases across all benchmarks and produces aggregated results
with per-benchmark breakdowns and failure details.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ...utils import utc_now_iso
from .scoring import _BENCHMARK_REGISTRY

logger = logging.getLogger("mind_clone.core.evaluation")


def run_continuous_eval_suite(max_cases: int = 50) -> Dict[str, Any]:
    """Run the continuous evaluation suite.

    Executes up to ``max_cases`` eval cases across all 7 benchmarks and returns
    aggregated results with per-benchmark breakdowns and failure details.

    Returns:
        Dict with keys: ok, cases_run, cases_passed, cases_failed, score,
        benchmarks (per-benchmark breakdown), failures, timestamp.
    """
    logger.info("Running continuous eval suite (max_cases=%d)", max_cases)

    total_run = 0
    total_passed = 0
    total_failed = 0
    benchmarks: Dict[str, Dict[str, Any]] = {}
    failures: list[dict] = []
    results: Dict[str, Dict[str, Any]] = {}

    for benchmark_name, case_list in _BENCHMARK_REGISTRY:
        bm_passed = 0
        bm_failed = 0
        bm_cases_run = 0

        for case_name, case_func in case_list:
            if total_run >= max_cases:
                break

            t0 = time.monotonic()
            try:
                passed, detail = case_func()
            except Exception as exc:
                passed = False
                detail = f"EXCEPTION: {type(exc).__name__}: {str(exc)[:200]}"

            duration_ms = int((time.monotonic() - t0) * 1000)

            total_run += 1
            bm_cases_run += 1

            if passed:
                total_passed += 1
                bm_passed += 1
                logger.info("EVAL %s PASS (%dms): %s", case_name, duration_ms, detail)
            else:
                total_failed += 1
                bm_failed += 1
                failures.append({
                    "case": case_name,
                    "benchmark": benchmark_name,
                    "detail": detail,
                    "duration_ms": duration_ms,
                })
                logger.warning("EVAL %s FAIL (%dms): %s", case_name, duration_ms, detail)

            results[case_name] = {
                "passed": passed,
                "detail": detail,
                "benchmark": benchmark_name,
                "duration_ms": duration_ms,
            }

        if bm_cases_run > 0:
            benchmarks[benchmark_name] = {
                "cases_run": bm_cases_run,
                "passed": bm_passed,
                "failed": bm_failed,
                "score": round(bm_passed / bm_cases_run, 3),
            }

        if total_run >= max_cases:
            break

    score = total_passed / total_run if total_run > 0 else 1.0

    return {
        "ok": True,
        "cases_run": total_run,
        "cases_passed": total_passed,
        "cases_failed": total_failed,
        "score": round(score, 3),
        "benchmarks": benchmarks,
        "failures": failures,
        "results": results,
        "timestamp": utc_now_iso(),
    }


def evaluate_release_gate(
    run_eval: bool = False,
    max_cases: Optional[int] = None,
    min_pass_rate: float = 0.8,
) -> Dict[str, Any]:
    """Evaluate whether the current build passes the release gate.

    If ``run_eval`` is True, runs the eval suite first and checks
    that the pass rate meets ``min_pass_rate`` (default 80%).

    Args:
        run_eval: Whether to actually run the eval suite.
        max_cases: Maximum number of cases to run (default 50).
        min_pass_rate: Minimum pass rate to pass the release gate.

    Returns:
        Dict with keys: ok, passed, eval_result, timestamp.
    """
    if run_eval:
        result = run_continuous_eval_suite(max_cases=max_cases or 50)
        passed = result.get("score", 0) >= min_pass_rate
    else:
        passed = True
        result = {}

    return {
        "ok": True,
        "passed": passed,
        "eval_result": result,
        "timestamp": utc_now_iso(),
    }
