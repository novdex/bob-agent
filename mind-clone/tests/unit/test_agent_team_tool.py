"""
Tests for the agent team tool and API route.
"""

from __future__ import annotations

import threading
from unittest.mock import patch, MagicMock

import pytest

from mind_clone.tools.agent_team import tool_agent_team_run, tool_agent_team_status


class TestAgentTeamRunValidation:

    def test_args_not_dict(self):
        result = tool_agent_team_run("not a dict")
        assert result["ok"] is False
        assert "dict" in result["error"]

    def test_empty_task(self):
        result = tool_agent_team_run({"task": ""})
        assert result["ok"] is False
        assert "required" in result["error"]

    def test_missing_task(self):
        result = tool_agent_team_run({})
        assert result["ok"] is False
        assert "required" in result["error"]

    def test_task_too_long(self):
        result = tool_agent_team_run({"task": "x" * 2001})
        assert result["ok"] is False
        assert "2000" in result["error"]

    def test_whitespace_only_task(self):
        result = tool_agent_team_run({"task": "   "})
        assert result["ok"] is False
        assert "required" in result["error"]


class TestAgentTeamRunExecution:

    def _run(self, task, api_key="key", repo_root="/tmp", orch_return=None, orch_side_effect=None):
        mock_cfg = MagicMock()
        mock_cfg.api_key = api_key
        mock_cfg.repo_root = repo_root
        mock_config_cls = MagicMock(return_value=mock_cfg)

        mock_orch = MagicMock()
        if orch_return:
            mock_orch.run.return_value = orch_return
        if orch_side_effect:
            mock_orch.run.side_effect = orch_side_effect
        mock_orch_cls = MagicMock(return_value=mock_orch)

        with patch("mind_clone.agents.config.AgentConfig", mock_config_cls), \
             patch("mind_clone.agents.orchestrator.Orchestrator", mock_orch_cls):
            return tool_agent_team_run({"task": task})

    def test_success(self):
        result = self._run("Add logging", api_key="test-key", repo_root="/tmp/repo",
                          orch_return={
                              "ok": True, "branch": "agent/add-logging", "duration_s": 12.5,
                              "tests": {"tests_passed": 50, "tests_failed": 0},
                              "review": {"summary": "LGTM"},
                              "changes": {"files_modified": ["src/main.py"]},
                              "llm_stats": {"calls": 5, "total_tokens": 1000},
                          })
        assert result["ok"] is True
        assert "agent/add-logging" in result["branch"]
        assert result["duration_s"] >= 0
        assert "50 passed" in result["summary"]

    def test_failure(self):
        result = self._run("Break it", orch_return={
            "ok": False, "error": "Tests failed after 3 retries",
            "branch": "agent/broken", "duration_s": 30.0,
        })
        assert result["ok"] is False
        assert "Tests failed" in result["error"]

    def test_no_api_key(self):
        result = self._run("Do something", api_key="")
        assert result["ok"] is False
        assert "API key" in result["error"]

    def test_no_repo_root(self):
        result = self._run("Do something", repo_root="")
        assert result["ok"] is False
        assert "repository root" in result["error"]

    def test_orchestrator_crash(self):
        result = self._run("crash test", orch_side_effect=RuntimeError("kaboom"))
        assert result["ok"] is False
        assert "crashed" in result["error"]

    def test_concurrent_run_blocked(self):
        import time

        mock_cfg = MagicMock()
        mock_cfg.api_key = "key"
        mock_cfg.repo_root = "/tmp"
        mock_config_cls = MagicMock(return_value=mock_cfg)

        def slow_run(task):
            time.sleep(0.5)
            return {"ok": True, "branch": "agent/slow", "duration_s": 0.5,
                    "tests": {}, "review": {}, "changes": {}, "llm_stats": {}}

        mock_orch = MagicMock()
        mock_orch.run.side_effect = slow_run
        mock_orch_cls = MagicMock(return_value=mock_orch)

        results = [None, None]

        def run_first():
            with patch("mind_clone.agents.config.AgentConfig", mock_config_cls), \
                 patch("mind_clone.agents.orchestrator.Orchestrator", mock_orch_cls):
                results[0] = tool_agent_team_run({"task": "first task"})

        def run_second():
            time.sleep(0.1)
            with patch("mind_clone.agents.config.AgentConfig", mock_config_cls), \
                 patch("mind_clone.agents.orchestrator.Orchestrator", mock_orch_cls):
                results[1] = tool_agent_team_run({"task": "second task"})

        t1 = threading.Thread(target=run_first)
        t2 = threading.Thread(target=run_second)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert results[0]["ok"] is True
        assert results[1]["ok"] is False
        assert "already running" in results[1]["error"]


class TestAgentTeamStatus:

    def test_default_idle(self):
        from mind_clone.core.state import RUNTIME_STATE
        RUNTIME_STATE.pop("agent_team_status", None)
        RUNTIME_STATE.pop("agent_team_task", None)
        RUNTIME_STATE.pop("agent_team_last_result", None)

        result = tool_agent_team_status({})
        assert result["ok"] is True
        assert result["status"] == "idle"
        assert result["current_task"] == ""

    def test_shows_running_state(self):
        from mind_clone.core.state import RUNTIME_STATE
        RUNTIME_STATE["agent_team_status"] = "running"
        RUNTIME_STATE["agent_team_task"] = "Add auth module"
        try:
            result = tool_agent_team_status({})
            assert result["status"] == "running"
            assert result["current_task"] == "Add auth module"
        finally:
            RUNTIME_STATE.pop("agent_team_status", None)
            RUNTIME_STATE.pop("agent_team_task", None)

    def test_shows_last_result(self):
        from mind_clone.core.state import RUNTIME_STATE
        RUNTIME_STATE["agent_team_status"] = "idle"
        RUNTIME_STATE["agent_team_last_result"] = {"ok": True, "branch": "agent/done"}
        try:
            result = tool_agent_team_status({})
            assert result["last_result"]["ok"] is True
        finally:
            RUNTIME_STATE.pop("agent_team_status", None)
            RUNTIME_STATE.pop("agent_team_last_result", None)


class TestAgentTeamRegistration:

    def test_in_tool_dispatch(self):
        from mind_clone.tools.registry import TOOL_DISPATCH
        assert "agent_team_run" in TOOL_DISPATCH
        assert "agent_team_status" in TOOL_DISPATCH

    def test_in_tool_categories(self):
        from mind_clone.tools.registry import TOOL_CATEGORIES
        assert "agent_team" in TOOL_CATEGORIES
        assert "agent_team_run" in TOOL_CATEGORIES["agent_team"]

    def test_schema_exists(self):
        from mind_clone.tools.schemas import ALL_TOOL_SCHEMAS
        names = [s["function"]["name"] for s in ALL_TOOL_SCHEMAS]
        assert "agent_team_run" in names
        assert "agent_team_status" in names

    def test_schema_has_required_task(self):
        from mind_clone.tools.schemas import get_tool_schema_by_name
        schema = get_tool_schema_by_name("agent_team_run")
        assert schema is not None
        assert "task" in schema["function"]["parameters"]["required"]

    def test_intent_keywords(self):
        from mind_clone.tools.registry import classify_tool_intent
        cats = classify_tool_intent("use the agent team to refactor auth")
        assert "agent_team" in cats


class TestAgentTeamAPI:

    @pytest.fixture
    def client(self):
        from mind_clone.api.factory import create_app
        from fastapi.testclient import TestClient
        return TestClient(create_app())

    def test_run_endpoint_exists(self, client):
        response = client.post("/agent/run", json={"task": "test"})
        assert response.status_code != 404

    def test_status_endpoint_exists(self, client):
        response = client.get("/agent/status")
        assert response.status_code != 404

    def test_run_validation_empty_task(self, client):
        response = client.post("/agent/run", json={"task": ""})
        assert response.status_code == 422

    def test_run_validation_missing_task(self, client):
        response = client.post("/agent/run", json={})
        assert response.status_code == 422

    def test_run_success_via_api(self, client):
        mock_cfg = MagicMock()
        mock_cfg.api_key = "key"
        mock_cfg.repo_root = "/tmp"
        mock_config_cls = MagicMock(return_value=mock_cfg)

        mock_orch = MagicMock()
        mock_orch.run.return_value = {
            "ok": True, "branch": "agent/api-test", "duration_s": 5.0,
            "tests": {"tests_passed": 50, "tests_failed": 0},
            "review": {"summary": "good"}, "changes": {"files_modified": []},
            "llm_stats": {"calls": 3, "total_tokens": 500},
        }
        mock_orch_cls = MagicMock(return_value=mock_orch)

        with patch("mind_clone.agents.config.AgentConfig", mock_config_cls), \
             patch("mind_clone.agents.orchestrator.Orchestrator", mock_orch_cls):
            response = client.post("/agent/run", json={"task": "add tests"})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["branch"] == "agent/api-test"

    def test_status_returns_json(self, client):
        response = client.get("/agent/status")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "ok" in data
