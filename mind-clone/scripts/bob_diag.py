#!/usr/bin/env python3
"""bob-diag: Performance diagnosis and bottleneck detection for Bob.

Usage:
    python bob_diag.py              # One-shot diagnosis
    python bob_diag.py --watch      # Refresh every 10s
    python bob_diag.py --json       # Machine-readable output
"""

import argparse
import json
import sys
import time
import urllib.request


def fetch_runtime(url):
    """Fetch /status/runtime from Bob."""
    try:
        data = json.loads(urllib.request.urlopen(url, timeout=5).read())
        return data, None
    except Exception as e:
        return None, str(e)


def diagnose(data):
    """Return list of issue strings."""
    issues = []
    backlog = max(0, int(data.get("command_queue_enqueued", 0)) - int(data.get("command_queue_processed", 0)))

    if data.get("command_queue_mode") == "on" and int(data.get("command_queue_worker_alive_count", 0)) < 2:
        issues.append("LOW WORKERS: Only {} queue workers alive (target {})".format(
            data.get("command_queue_worker_alive_count"), data.get("command_queue_worker_target")))
    if backlog > 0:
        issues.append(f"QUEUE BACKLOG: {backlog} messages waiting to be processed")
    if int(data.get("budget_runs_degraded", 0)) > 0:
        issues.append(f"BUDGET DEGRADATION: {data.get('budget_runs_degraded')} runs degraded")
    if int(data.get("session_hard_clear_count", 0)) > 2:
        issues.append(f"CONTEXT OVERFLOW: {data.get('session_hard_clear_count')} hard clears")
    for name, cb in (data.get("circuit_breakers") or {}).items():
        if cb.get("state") != "closed":
            issues.append(f"CIRCUIT OPEN: {name} breaker is {cb.get('state')}")
    if data.get("command_queue_mode") == "on":
        issues.append("QUEUE MODE ON: adds latency, try COMMAND_QUEUE_MODE=auto")
    if int(data.get("cl_tools_blocked", 0)) > 0:
        issues.append(f"TOOLS BLOCKED: {data.get('cl_tools_blocked')} tools blocked by closed-loop feedback")
    if int(data.get("task_guard_dead_letters", 0)) > 3:
        issues.append(f"DEAD LETTERS: {data.get('task_guard_dead_letters')} dead letters (failing strategies)")

    return issues


def print_report(data):
    """Print human-readable diagnosis report."""
    print("=" * 60)
    print("  bob-diag: Performance Diagnosis")
    print("=" * 60)

    print("\n--- LLM ---")
    print(f"  Model: {data.get('llm_primary_model')}")
    print(f"  Last used: {data.get('llm_last_model_used')}")
    print(f"  Last error: {data.get('llm_last_error')}")
    print(f"  Failovers: {data.get('llm_failover_count')}")
    print(f"  Primary failures: {data.get('llm_primary_failures')}")

    print("\n--- Queue ---")
    print(f"  Mode: {data.get('command_queue_mode')}")
    print(f"  Current size: {data.get('command_queue_size')}")
    print(f"  Enqueued: {data.get('command_queue_enqueued')}")
    print(f"  Processed: {data.get('command_queue_processed')}")
    print(f"  Dropped: {data.get('command_queue_dropped')}")
    print(f"  Workers alive: {data.get('command_queue_worker_alive_count')}")
    print(f"  Worker target: {data.get('command_queue_worker_target')}")
    backlog = max(0, int(data.get("command_queue_enqueued", 0)) - int(data.get("command_queue_processed", 0)))
    if backlog > 0:
        print(f"  *** BACKLOG: {backlog} messages waiting! ***")

    print("\n--- Budget ---")
    print(f"  Governor: {data.get('budget_governor_enabled')}")
    print(f"  Mode: {data.get('budget_governor_mode')}")
    print(f"  Degraded runs: {data.get('budget_runs_degraded')}")
    bu = data.get("budget_last_usage") or {}
    if bu:
        print(f"  Last run: {bu.get('seconds', 0):.0f}s, {bu.get('llm_calls', 0)} LLM calls, {bu.get('tool_calls', 0)} tool calls")

    print("\n--- Session ---")
    print(f"  Soft trims: {data.get('session_soft_trim_count')}")
    print(f"  Hard clears: {data.get('session_hard_clear_count')}")
    print(f"  Last prune chars: {data.get('session_last_prune_chars')}")

    print("\n--- Circuit Breakers ---")
    for name, cb in (data.get("circuit_breakers") or {}).items():
        state = cb.get("state", "?")
        fails = cb.get("failures", 0)
        err = cb.get("last_error")
        line = f"  {name}: {state} (failures={fails})"
        if err:
            line += f" error={str(err)[:80]}"
        print(line)

    print("\n--- Tasks ---")
    print(f"  Queue size: {data.get('task_queue_size')}")
    print(f"  Tracked: {data.get('tasks_tracked')}")
    print(f"  Dead letters: {data.get('task_guard_dead_letters')}")

    print("\n--- Closed Loops (Section 5B) ---")
    for k in sorted(data):
        if k.startswith("cl_"):
            print(f"  {k}: {data[k]}")

    print("\n--- Self-Tuning (Section 5C) ---")
    print(f"  Total tunes: {data.get('st_tunes_total', 0)}")
    print(f"  Queue mode switches: {data.get('st_queue_mode_switches', 0)}")
    print(f"  Session budget adjustments: {data.get('st_session_budget_adjustments', 0)}")
    print(f"  Worker scale events: {data.get('st_worker_scale_events', 0)}")
    print(f"  Budget mode switches: {data.get('st_budget_mode_switches', 0)}")
    print(f"  Current soft budget: {data.get('st_current_session_soft_budget')}")
    print(f"  Current hard budget: {data.get('st_current_session_hard_budget')}")
    print(f"  Current workers: {data.get('st_current_worker_count')}")
    print(f"  Last tune: {data.get('st_last_tune_at')}")
    print(f"  Last action: {data.get('st_last_action')}")

    print("\n--- Memory ---")
    print(f"  Lessons retrieved: {data.get('memory_last_lessons_retrieved')}")
    print(f"  Summaries retrieved: {data.get('memory_last_summaries_retrieved')}")
    print(f"  Artifacts retrieved: {data.get('memory_last_task_artifacts_retrieved')}")
    print(f"  Lesson quality: {data.get('memory_last_lesson_quality')}")
    print(f"  Continuity score: {data.get('memory_last_continuity_score')}")

    print(f"\n--- Cost ---")
    print(f"  Total: ${data.get('usage_ledger_cost_usd', 0):.2f}")

    # Diagnosis
    issues = diagnose(data)
    print("\n" + "=" * 60)
    print("DIAGNOSIS:")
    if not issues:
        print("  No obvious bottlenecks found.")
    else:
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
    print("=" * 60)

    return len(issues)


def main():
    parser = argparse.ArgumentParser(
        description="bob-diag: Performance diagnosis for Bob",
        epilog="Examples:\n"
               "  python bob_diag.py              # one-shot\n"
               "  python bob_diag.py --watch       # refresh every 10s\n"
               "  python bob_diag.py --json        # JSON output\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", default="http://localhost:8000/status/runtime", help="Runtime status URL")
    parser.add_argument("--watch", action="store_true", help="Refresh every 10 seconds")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.watch:
        try:
            while True:
                data, err = fetch_runtime(args.url)
                if err:
                    print(f"\rBob is DOWN: {err}", end="", flush=True)
                elif args.json:
                    issues = diagnose(data)
                    print(json.dumps({"issues": issues, "issue_count": len(issues)}, indent=2))
                else:
                    # Clear screen
                    print("\033[2J\033[H", end="")
                    print_report(data)
                    print(f"\n  [Refreshing every 10s — Ctrl+C to stop]")
                time.sleep(10)
        except KeyboardInterrupt:
            print("\nStopped.")
            sys.exit(0)
    else:
        data, err = fetch_runtime(args.url)
        if err:
            print(f"Bob is DOWN: {err}")
            sys.exit(1)

        if args.json:
            issues = diagnose(data)
            print(json.dumps({"issues": issues, "issue_count": len(issues)}, indent=2))
            sys.exit(1 if issues else 0)
        else:
            issue_count = print_report(data)
            sys.exit(1 if issue_count > 0 else 0)


if __name__ == "__main__":
    main()
