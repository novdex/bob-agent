from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import traceback
import uuid
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT_DIR / "mind_clone_agent.py"


class CheckError(RuntimeError):
    pass


def _load_module():
    spec = importlib.util.spec_from_file_location("mind_clone_agent_hardening", str(MODULE_PATH))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _assert(condition: bool, message: str):
    if not condition:
        raise CheckError(message)


def _cleanup_owner(module, owner_id: int):
    db = module.SessionLocal()
    try:
        tables = [
            (module.IdentityKernel, "owner_id"),
            (module.ConversationMessage, "owner_id"),
            (module.ConversationSummary, "owner_id"),
            (module.Task, "owner_id"),
            (module.TaskDeadLetter, "owner_id"),
            (module.TaskArtifact, "owner_id"),
            (module.ResearchNote, "owner_id"),
            (module.MemoryVector, "owner_id"),
            (module.ApprovalRequest, "owner_id"),
            (module.ScheduledJob, "owner_id"),
        ]
        for model, key in tables:
            db.query(model).filter(getattr(model, key) == int(owner_id)).delete(synchronize_session=False)
        db.query(module.User).filter(module.User.id == int(owner_id)).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _run_checks():
    module = _load_module()
    module.init_db()
    module.load_remote_node_registry()
    module.load_plugin_tools_registry()

    suffix = uuid.uuid4().hex[:10]
    chat_id = f"hardening_chat_{suffix}"
    username = f"hardening_user_{suffix}"
    owner_id = module.resolve_owner_id(chat_id, username)

    plugin_file = ROOT_DIR / "plugins" / f"hardening_demo_{suffix}.json"
    original_allowlist = set(module.PLUGIN_ALLOWLIST)
    original_registry = dict(module.REMOTE_NODE_REGISTRY)
    old_post = module.REQUESTS_SESSION.post

    try:
        # 1) Approval gating + resume token flow
        approval_probe_path = str((ROOT_DIR / f"tmp_hardening_approval_{suffix}.txt").resolve())
        approval_call = module.execute_tool_with_context(
            identity=None,
            tool_name="write_file",
            args={"file_path": approval_probe_path, "content": "hardening approval probe"},
            owner_id=owner_id,
            source_type="chat",
            source_ref=str(owner_id),
            step_id=None,
            resume_payload={"kind": "chat_message", "owner_id": owner_id, "user_message": "hello"},
        )
        _assert(bool(approval_call.get("approval_required")), "Approval gate did not trigger for write_file.")
        token = str(approval_call.get("resume_token") or "").strip()
        _assert(bool(token), "Approval token missing from approval-required response.")

        approved = module.decide_approval_token(owner_id, token, True)
        _assert(bool(approved.get("ok")), f"Approving token failed: {approved}")
        _assert(str(approved.get("status")) == "approved", f"Unexpected approval status: {approved}")

        resumed = module.execute_tool_with_context(
            identity=None,
            tool_name="write_file",
            args={"file_path": approval_probe_path, "content": "hardening approval probe"},
            owner_id=owner_id,
        )
        _assert(bool(resumed.get("ok")), f"Approved write_file did not execute: {resumed}")
        Path(approval_probe_path).unlink(missing_ok=True)

        # 2) Queue lane semaphore setup
        for lane in ("default", "research", "api", "telegram", "cron"):
            sem = module.get_lane_semaphore(lane)
            expected = int(module.lane_limit(lane))
            actual = int(getattr(sem, "_mind_clone_limit", 0))
            _assert(actual == expected, f"Lane semaphore mismatch for '{lane}': expected {expected}, got {actual}")

        # 3) Plugin load + execution + allowlist block
        plugin_file.parent.mkdir(parents=True, exist_ok=True)
        plugin_tool_name = f"plugin__hardening_demo_{suffix}"
        plugin_manifest = {
            "id": f"hardening_demo_{suffix}",
            "name": "Hardening Demo",
            "version": "1.0.0",
            "tool_name": plugin_tool_name,
            "description": "Hardening test plugin",
            "type": "http_request",
            "method": "POST",
            "url": "https://example.invalid/plugin",
            "safe_mode": True,
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        }
        plugin_file.write_text(json.dumps(plugin_manifest), encoding="utf-8")

        module.PLUGIN_ALLOWLIST = set()
        module.load_plugin_tools_registry()
        plugin_list = module.tool_list_plugin_tools()
        _assert(bool(plugin_list.get("ok")), "list_plugin_tools failed.")
        _assert(
            any(item.get("tool_name") == plugin_tool_name for item in plugin_list.get("tools", [])),
            "Plugin tool did not load.",
        )

        class _Response:
            def __init__(self, payload: dict):
                self.status_code = 200
                self._payload = payload
                self.text = json.dumps(payload)

            def json(self):
                return self._payload

        module.REQUESTS_SESSION.post = lambda *a, **k: _Response({"ok": True, "echo": k.get("json", {})})
        plugin_exec = module.execute_tool_with_context(
            identity=None,
            tool_name=plugin_tool_name,
            args={"value": "x"},
            owner_id=owner_id,
        )
        _assert(bool(plugin_exec.get("ok")), f"Plugin tool execution failed: {plugin_exec}")

        module.PLUGIN_ALLOWLIST = {"non_matching_plugin"}
        module.load_plugin_tools_registry()
        blocked_list = module.tool_list_plugin_tools()
        _assert(
            not any(item.get("tool_name") == plugin_tool_name for item in blocked_list.get("tools", [])),
            "Plugin allowlist did not block non-allowed plugin.",
        )

        # 4) Remote node failure handling
        module.REMOTE_NODE_REGISTRY = {
            "demo_node": {
                "name": "demo_node",
                "base_url": "https://demo-node.invalid",
                "command_path": "/run_command",
                "token": "",
                "enabled": True,
            }
        }

        def _raise_conn(*_args, **_kwargs):
            raise module.requests.exceptions.ConnectionError("simulated remote connection failure")

        module.REQUESTS_SESSION.post = _raise_conn
        remote_result = module.tool_run_command_node("demo_node", "echo x", timeout=5)
        _assert(remote_result.get("ok") is False, f"Remote node failure path did not fail: {remote_result}")
        _assert(str(remote_result.get("node")) == "demo_node", "Remote node failure did not preserve node name.")

        # 5) Cron create/list/disable + due-run path
        cron_create = module.tool_schedule_job(
            owner_id=owner_id,
            name="hardening cron job",
            message="cron ping",
            interval_seconds=max(module.CRON_MIN_INTERVAL_SECONDS, 60),
            lane="cron",
        )
        _assert(bool(cron_create.get("ok")), f"Cron job creation failed: {cron_create}")
        job_id = int(cron_create.get("job_id"))

        cron_list = module.tool_list_scheduled_jobs(owner_id=owner_id, include_disabled=True, limit=20)
        _assert(bool(cron_list.get("ok")), f"Cron list failed: {cron_list}")
        _assert(any(int(item.get("job_id")) == job_id for item in cron_list.get("jobs", [])), "Cron job missing in list.")

        cron_disable = module.tool_disable_scheduled_job(owner_id=owner_id, job_id=job_id)
        _assert(bool(cron_disable.get("ok")), f"Cron disable failed: {cron_disable}")

        due_runs = asyncio.run(module.run_due_cron_jobs_once())
        _assert(isinstance(due_runs, int), "run_due_cron_jobs_once did not return int.")

        # 6) Runtime alert synthesis checks
        metrics = module.runtime_metrics()
        _assert("runtime_alerts" in metrics, "runtime_alerts missing from runtime metrics.")
        _assert("runtime_alert_count" in metrics, "runtime_alert_count missing from runtime metrics.")
        synthetic = dict(metrics)
        synthetic["command_queue_size"] = synthetic.get("command_queue_max_size", 200)
        alerts = module.compute_runtime_alerts(synthetic)
        _assert(
            any(a.get("code") == "command_queue_near_capacity" for a in alerts),
            "Queue capacity alert was not generated under synthetic full queue.",
        )

        print("HARDENING_S1_CHECKS: PASS")
        print("Checks: approval, queue lanes, plugins, remote nodes, cron, runtime alerts")
        return 0
    finally:
        module.REQUESTS_SESSION.post = old_post
        module.PLUGIN_ALLOWLIST = original_allowlist
        module.REMOTE_NODE_REGISTRY = original_registry
        try:
            plugin_file.unlink(missing_ok=True)
        except Exception:
            pass
        module.load_plugin_tools_registry()
        _cleanup_owner(module, owner_id)


def main() -> int:
    try:
        return _run_checks()
    except Exception as exc:
        print("HARDENING_S1_CHECKS: FAIL")
        print(f"Reason: {exc}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
