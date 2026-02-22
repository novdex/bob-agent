#!/usr/bin/env python3
"""Quick diagnostic: why is Bob slow?"""
import json, urllib.request, sys

try:
    data = json.loads(urllib.request.urlopen("http://localhost:8000/status/runtime", timeout=5).read())
except Exception as e:
    print(f"Bob is DOWN: {e}")
    sys.exit(1)

print("=== BOB PERFORMANCE DIAGNOSIS ===\n")

print("--- LLM ---")
print(f"  Model: {data.get('llm_primary_model')}")
print(f"  Last used: {data.get('llm_last_model_used')}")
print(f"  Last error: {data.get('llm_last_error')}")
print(f"  Failovers: {data.get('llm_failover_count')}")
print(f"  Primary failures: {data.get('llm_primary_failures')}")

print("\n--- Queue (MAIN BOTTLENECK?) ---")
print(f"  Mode: {data.get('command_queue_mode')}")
print(f"  Current size: {data.get('command_queue_size')}")
print(f"  Enqueued: {data.get('command_queue_enqueued')}")
print(f"  Processed: {data.get('command_queue_processed')}")
print(f"  Dropped: {data.get('command_queue_dropped')}")
print(f"  Workers alive: {data.get('command_queue_worker_alive_count')}")
print(f"  Worker target: {data.get('command_queue_worker_target')}")
backlog = int(data.get('command_queue_enqueued', 0)) - int(data.get('command_queue_processed', 0))
if backlog > 0:
    print(f"  *** BACKLOG: {backlog} messages waiting! ***")

print("\n--- Budget ---")
print(f"  Governor: {data.get('budget_governor_enabled')}")
print(f"  Mode: {data.get('budget_governor_mode')}")
print(f"  Degraded runs: {data.get('budget_runs_degraded')}")
bu = data.get('budget_last_usage') or {}
if bu:
    print(f"  Last run: {bu.get('seconds', 0):.0f}s, {bu.get('llm_calls', 0)} LLM calls, {bu.get('tool_calls', 0)} tool calls")

print("\n--- Session ---")
print(f"  Soft trims: {data.get('session_soft_trim_count')}")
print(f"  Hard clears: {data.get('session_hard_clear_count')}")
print(f"  Last prune chars: {data.get('session_last_prune_chars')}")

print("\n--- Circuit Breakers ---")
for name, cb in (data.get('circuit_breakers') or {}).items():
    state = cb.get('state', '?')
    fails = cb.get('failures', 0)
    err = cb.get('last_error')
    line = f"  {name}: {state} (failures={fails})"
    if err:
        line += f" error={str(err)[:80]}"
    print(line)

print("\n--- Tasks ---")
print(f"  Queue size: {data.get('task_queue_size')}")
print(f"  Tracked: {data.get('tasks_tracked')}")
print(f"  Dead letters: {data.get('task_guard_dead_letters')}")

print("\n--- Closed Loops ---")
for k in sorted(data):
    if k.startswith('cl_'):
        print(f"  {k}: {data[k]}")

print("\n--- Self-Tuning (Section 5C) ---")
print(f"  Enabled: {data.get('st_tunes_total') is not None}")
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

print(f"\n--- Cost ---")
print(f"  Total: ${data.get('usage_ledger_cost_usd', 0):.2f}")

# Diagnosis
print("\n" + "=" * 50)
print("DIAGNOSIS:")
issues = []
if data.get('command_queue_mode') == 'on' and int(data.get('command_queue_worker_alive_count', 0)) < 2:
    issues.append("LOW WORKERS: Only {0} queue workers alive (target {1})".format(
        data.get('command_queue_worker_alive_count'), data.get('command_queue_worker_target')))
if backlog > 0:
    issues.append(f"QUEUE BACKLOG: {backlog} messages waiting to be processed")
if int(data.get('budget_runs_degraded', 0)) > 0:
    issues.append(f"BUDGET DEGRADATION: {data.get('budget_runs_degraded')} runs degraded (limits tool calls)")
if int(data.get('session_hard_clear_count', 0)) > 2:
    issues.append(f"CONTEXT OVERFLOW: {data.get('session_hard_clear_count')} hard clears (conversation too long)")
for name, cb in (data.get('circuit_breakers') or {}).items():
    if cb.get('state') != 'closed':
        issues.append(f"CIRCUIT OPEN: {name} breaker is {cb.get('state')}")
if data.get('command_queue_mode') == 'on':
    issues.append("QUEUE MODE ON: All chat messages go through queue (adds latency). Try COMMAND_QUEUE_MODE=off for direct routing.")

if not issues:
    print("  No obvious bottlenecks found.")
else:
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")
print("=" * 50)
