"""SSE event streaming, continuous evaluation, and release gate."""
from __future__ import annotations

from ._imports import (
    asyncio,
    json,
    log,
    EVAL_HARNESS_ENABLED,
    EVAL_MAX_CASES,
    RELEASE_GATE_MIN_PASS_RATE,
    RELEASE_GATE_REQUIRE_ZERO_FAILS,
    BLACKBOX_READ_MAX_LIMIT,
    POLICY_PACK,
    POLICY_PACK_PRESETS,
    SECRET_GUARDRAIL_ENABLED,
    SECRET_REDACTION_TOKEN,
    WORKSPACE_DIFF_GATE_ENABLED,
    WORKSPACE_DIFF_GATE_MODE,
    WORKSPACE_DIFF_MAX_CHANGED_LINES,
    BUDGET_GOVERNOR_MODE,
    RUNTIME_STATE,
    truncate_text,
    redact_secret_data,
    evaluate_workspace_diff_gate,
    fetch_blackbox_events_after,
    create_run_budget,
    budget_should_stop,
    budget_should_degrade,
)
from .utils import utc_now_iso
from .runtime import runtime_metrics


# ============================================================================
# SSE and Blackbox Event Streaming
# ============================================================================


def sse_frame(event: str, data: dict, event_id: int | None = None) -> str:
    """Create an SSE frame."""
    payload = data
    try:
        payload, _ = redact_secret_data(data)
    except Exception:
        payload = data
    lines = []
    if event_id is not None:
        lines.append(f"id: {int(event_id)}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(payload, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


async def blackbox_event_stream_generator(
    owner_id: int,
    session_id: str | None = None,
    source_type: str | None = None,
    after_event_id: int = 0,
    poll_seconds: float = 1.0,
    batch_size: int = 120,
):
    """Generate SSE stream for blackbox events."""
    cursor = max(0, int(after_event_id))
    wait_seconds = max(0.2, min(10.0, float(poll_seconds)))
    batch_limit = max(10, min(BLACKBOX_READ_MAX_LIMIT, int(batch_size)))
    keepalive_tick = 0
    while True:
        events = fetch_blackbox_events_after(
            owner_id=int(owner_id),
            after_event_id=cursor,
            session_id=session_id,
            source_type=source_type,
            limit=batch_limit,
        )
        if events:
            for event in events:
                try:
                    event_id = int(event.get("id") or 0)
                except Exception:
                    event_id = cursor
                if event_id > cursor:
                    cursor = event_id
                event_name = str(event.get("event_type") or "blackbox_event")
                yield sse_frame(event=event_name, data=event, event_id=event_id)
            keepalive_tick = 0
            continue

        keepalive_tick += 1
        if keepalive_tick >= int(max(5, round(15.0 / wait_seconds))):
            yield ": keepalive\n\n"
            keepalive_tick = 0
        await asyncio.sleep(wait_seconds)



# ============================================================================
# Continuous Evaluation
# ============================================================================


def run_continuous_eval_suite(max_cases: int = 12) -> dict:
    """Run continuous evaluation suite."""
    if not EVAL_HARNESS_ENABLED:
        return {"ok": False, "error": "Eval harness disabled."}

    case_limit = max(1, min(EVAL_MAX_CASES, int(max_cases or EVAL_MAX_CASES)))
    cases: list[dict] = []

    metrics = runtime_metrics()
    must_have_runtime = {
        "worker_alive",
        "spine_supervisor_alive",
        "db_healthy",
        "webhook_registered",
        "command_queue_mode",
        "tool_policy_profile",
        "execution_sandbox_profile",
        "approval_gate_mode",
        "budget_governor_mode",
    }
    missing_runtime = sorted(k for k in must_have_runtime if k not in metrics)
    cases.append(
        {
            "name": "runtime_contract",
            "ok": len(missing_runtime) == 0,
            "detail": "runtime keys present"
            if not missing_runtime
            else f"missing keys: {', '.join(missing_runtime)}",
        }
    )

    cases.append(
        {
            "name": "policy_pack_valid",
            "ok": POLICY_PACK in POLICY_PACK_PRESETS,
            "detail": f"policy_pack={POLICY_PACK}",
        }
    )

    redacted, hits = redact_secret_data("Authorization: Bearer sk-live-super-secret-token-123456")
    redaction_ok = (
        SECRET_GUARDRAIL_ENABLED and (hits > 0) and (SECRET_REDACTION_TOKEN in str(redacted))
    )
    cases.append(
        {
            "name": "secret_redaction",
            "ok": redaction_ok,
            "detail": f"hits={hits}",
        }
    )

    diff_probe = evaluate_workspace_diff_gate(
        "write_file",
        {
            "file_path": "mind-clone/.diff_gate_probe.txt",
            "content": "\n".join(
                f"line {i}" for i in range(int(WORKSPACE_DIFF_MAX_CHANGED_LINES) + 30)
            ),
        },
    )
    diff_ok = True
    if WORKSPACE_DIFF_GATE_ENABLED:
        if WORKSPACE_DIFF_GATE_MODE == "block":
            diff_ok = bool(diff_probe.get("blocked"))
        elif WORKSPACE_DIFF_GATE_MODE == "approval":
            diff_ok = bool(diff_probe.get("require_approval"))
        else:
            diff_ok = bool(diff_probe.get("warned"))
    cases.append(
        {
            "name": "workspace_diff_gate",
            "ok": diff_ok,
            "detail": f"mode={WORKSPACE_DIFF_GATE_MODE} changed_lines={diff_probe.get('changed_lines')}",
        }
    )

    budget_probe = create_run_budget("eval_probe", owner_id=0, source_ref="eval")
    if budget_probe is not None:
        from mind_clone.config import BUDGET_MAX_LLM_CALLS

        budget_probe["llm_calls"] = int(BUDGET_MAX_LLM_CALLS) + 1
        stop_hit, _ = budget_should_stop(budget_probe)
        if BUDGET_GOVERNOR_MODE == "stop":
            budget_ok = bool(stop_hit)
        elif BUDGET_GOVERNOR_MODE == "degrade":
            budget_ok = bool(budget_should_degrade(budget_probe))
        else:
            budget_ok = True
    else:
        budget_ok = True
    cases.append(
        {
            "name": "budget_governor_mode",
            "ok": budget_ok,
            "detail": f"mode={BUDGET_GOVERNOR_MODE}",
        }
    )

    case_results = cases[:case_limit]
    passed = sum(1 for row in case_results if bool(row.get("ok")))
    failed = max(0, len(case_results) - passed)
    pass_rate = round((passed / max(1, len(case_results))), 4)
    report = {
        "ok": failed == 0,
        "total_cases": len(case_results),
        "passed_cases": passed,
        "failed_cases": failed,
        "pass_rate": pass_rate,
        "cases": case_results,
        "timestamp": utc_now_iso(),
    }
    RUNTIME_STATE["eval_runs_total"] = int(RUNTIME_STATE.get("eval_runs_total", 0)) + 1
    RUNTIME_STATE["eval_last_run_at"] = report["timestamp"]
    RUNTIME_STATE["eval_last_pass_rate"] = pass_rate
    RUNTIME_STATE["eval_last_fail_count"] = int(failed)
    RUNTIME_STATE["eval_last_report"] = report
    return report



def evaluate_release_gate(run_eval: bool = False, max_cases: int | None = None) -> dict:
    """Evaluate release gate status."""
    report = dict(RUNTIME_STATE.get("eval_last_report") or {})
    if run_eval or not report:
        report = run_continuous_eval_suite(max_cases=max_cases or EVAL_MAX_CASES)
        if not bool(report.get("ok", False)) and "cases" not in report:
            status = {
                "state": "fail",
                "reason": str(report.get("error") or "eval_failed"),
                "pass_rate": 0.0,
                "failed_cases": int(report.get("failed_cases", 1) or 1),
                "min_pass_rate": float(RELEASE_GATE_MIN_PASS_RATE),
                "require_zero_fails": bool(RELEASE_GATE_REQUIRE_ZERO_FAILS),
                "checked_at": utc_now_iso(),
            }
            RUNTIME_STATE["release_gate_last_status"] = status
            return {"ok": False, "state": "fail", "status": status, "eval_report": report}

    pass_rate = float(report.get("pass_rate", 0.0) or 0.0)
    failed_cases = int(report.get("failed_cases", 0) or 0)
    has_min_rate = pass_rate >= float(RELEASE_GATE_MIN_PASS_RATE)
    has_zero_fails = (failed_cases == 0) if RELEASE_GATE_REQUIRE_ZERO_FAILS else True
    gate_ok = bool(has_min_rate and has_zero_fails)
    reason_parts = []
    if not has_min_rate:
        reason_parts.append(f"pass_rate<{RELEASE_GATE_MIN_PASS_RATE:.2f}")
    if not has_zero_fails:
        reason_parts.append("failing_cases_present")
    status = {
        "state": "pass" if gate_ok else "fail",
        "reason": ", ".join(reason_parts) if reason_parts else "ok",
        "pass_rate": round(pass_rate, 4),
        "failed_cases": int(failed_cases),
        "min_pass_rate": float(RELEASE_GATE_MIN_PASS_RATE),
        "require_zero_fails": bool(RELEASE_GATE_REQUIRE_ZERO_FAILS),
        "checked_at": utc_now_iso(),
    }
    RUNTIME_STATE["release_gate_last_status"] = status
    return {"ok": gate_ok, "state": status["state"], "status": status, "eval_report": report}
