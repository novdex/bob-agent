"""
Report generation and formatting for eval results.

Provides utilities to format eval suite results into human-readable
reports and structured summaries.
"""

from __future__ import annotations

from typing import Any, Dict, List


def format_eval_summary(result: Dict[str, Any]) -> str:
    """Format an eval suite result dict into a human-readable summary string.

    Args:
        result: Dict returned by run_continuous_eval_suite().

    Returns:
        Multi-line string with score, per-benchmark breakdown, and failures.
    """
    lines: list[str] = []

    score = result.get("score", 0)
    cases_run = result.get("cases_run", 0)
    cases_passed = result.get("cases_passed", 0)
    cases_failed = result.get("cases_failed", 0)

    lines.append(f"Eval Score: {score:.1%} ({cases_passed}/{cases_run} passed, {cases_failed} failed)")
    lines.append("")

    # Per-benchmark breakdown
    benchmarks = result.get("benchmarks", {})
    if benchmarks:
        lines.append("Benchmarks:")
        for bm_name, bm_data in benchmarks.items():
            bm_score = bm_data.get("score", 0)
            bm_run = bm_data.get("cases_run", 0)
            bm_passed = bm_data.get("passed", 0)
            bm_failed = bm_data.get("failed", 0)
            status = "PASS" if bm_failed == 0 else "PARTIAL"
            lines.append(
                f"  {bm_name}: {bm_score:.0%} ({bm_passed}/{bm_run}) [{status}]"
            )
        lines.append("")

    # Failures
    failures = result.get("failures", [])
    if failures:
        lines.append(f"Failures ({len(failures)}):")
        for f in failures:
            lines.append(f"  - {f.get('case', '?')}: {f.get('detail', '?')}")

    return "\n".join(lines)


def build_benchmark_report(result: Dict[str, Any]) -> Dict[str, Any]:
    """Build a structured benchmark report from eval results.

    Args:
        result: Dict returned by run_continuous_eval_suite().

    Returns:
        Dict with summary, per-benchmark details, and failure list.
    """
    benchmarks = result.get("benchmarks", {})
    failures = result.get("failures", [])

    benchmark_details: List[Dict[str, Any]] = []
    for bm_name, bm_data in benchmarks.items():
        benchmark_details.append({
            "name": bm_name,
            "score": bm_data.get("score", 0),
            "cases_run": bm_data.get("cases_run", 0),
            "passed": bm_data.get("passed", 0),
            "failed": bm_data.get("failed", 0),
            "all_passed": bm_data.get("failed", 0) == 0,
        })

    return {
        "overall_score": result.get("score", 0),
        "total_cases": result.get("cases_run", 0),
        "total_passed": result.get("cases_passed", 0),
        "total_failed": result.get("cases_failed", 0),
        "benchmarks": benchmark_details,
        "failures": [
            {
                "case": f.get("case", ""),
                "benchmark": f.get("benchmark", ""),
                "detail": f.get("detail", ""),
                "duration_ms": f.get("duration_ms", 0),
            }
            for f in failures
        ],
        "timestamp": result.get("timestamp", ""),
    }
