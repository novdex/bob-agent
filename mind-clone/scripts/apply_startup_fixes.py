"""Apply startup fixes for Python 3.14 + Windows compatibility. Run before tests/server."""
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

def patch(path, old, new, label):
    with open(path, "r") as f: c = f.read()
    if old not in c: return False
    with open(path, "w") as f: f.write(c.replace(old, new))
    print(f"  [OK] {label}")
    return True

def main():
    print("Applying startup fixes...")
    n = 0
    n += patch("src/mind_clone/core/knowledge.py",
        "            and isinstance(tree.body[0].value, (ast.Str, ast.Constant))):",
        "            and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str)):",
        "knowledge.py: ast.Str -> ast.Constant")
    n += patch("src/mind_clone/core/knowledge.py",
        '        result["docstring"] = getattr(val, "s", str(getattr(val, "value", "")))[:200]',
        '        result["docstring"] = str(val.value)[:200]',
        "knowledge.py: docstring extraction")
    n += patch("src/mind_clone/core/state.py",
        '    "stt_transcriptions": 0,\n    "stt_failures": 0,\n}',
        '    "stt_transcriptions": 0,\n    "stt_failures": 0,\n'
        '    "autonomy_engine_alive": False, "autonomy_actions_total": 0,\n'
        '    "autonomy_goals_executed": 0, "autonomy_goals_failed": 0,\n'
        '    "autonomy_reports_sent": 0, "autonomy_last_goal": None,\n'
        '    "autonomy_last_error": None, "autonomy_last_run_at": None,\n'
        '    "world_model_updates_total": 0, "world_model_entities_tracked": 0,\n'
        '    "world_model_last_update_at": None,\n'
        '    "reasoning_chains_total": 0, "reasoning_avg_depth": 0.0,\n'
        '    "reasoning_last_strategy": None,\n'
        '    "learning_reflections_total": 0, "learning_lessons_extracted": 0,\n'
        '    "learning_last_reflection_at": None,\n'
        '    "memory_consolidations_total": 0, "memory_consolidation_last_at": None,\n'
        '    "webhook_health_probes_total": 0, "webhook_health_probe_failures": 0,\n'
        '    "webhook_health_last_probe_at": None, "webhook_supervisor_restarts": 0,\n}',
        "state.py: RUNTIME_STATE keys")
    n += patch("tests/unit/test_agents.py",
        'assert cfg.log_dir == "/tmp/repo/persist/agent_logs"',
        'expected = os.path.join("/tmp/repo", "persist/agent_logs")\n        assert cfg.log_dir == expected',
        "test_agents.py: Windows path fix")
    print(f"Applied {n} patches.")

if __name__ == "__main__":
    main()
