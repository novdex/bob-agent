"""
Tests for core/subagents.py — Sub-agent spawning system.
"""
import pytest
from mind_clone.core.subagents import (
    ROLE_PROMPTS,
    ROLE_TOOLS,
    SubAgent,
    SubAgentResult,
    decompose_task,
    _detect_role,
    spawn_subagents,
    _run_worker,
    SUBAGENT_MAX_PARALLEL,
    SUBAGENT_TIMEOUT_SECONDS,
    SUBAGENT_MAX_TOOL_LOOPS,
)


class TestRoleDefinitions:
    """Test role prompts and tools."""

    def test_all_roles_have_prompts(self):
        expected = {"researcher", "coder", "analyst", "reviewer", "planner"}
        assert set(ROLE_PROMPTS.keys()) == expected

    def test_all_roles_have_tools(self):
        expected = {"researcher", "coder", "analyst", "reviewer", "planner"}
        assert set(ROLE_TOOLS.keys()) == expected

    def test_each_role_has_nonempty_prompt(self):
        for role, prompt in ROLE_PROMPTS.items():
            assert len(prompt) > 10, f"Role {role} has empty/short prompt"

    def test_each_role_has_tools_list(self):
        for role, tools in ROLE_TOOLS.items():
            assert isinstance(tools, list)
            assert len(tools) > 0, f"Role {role} has no tools"


class TestSubAgentDataclasses:
    """Test SubAgent and SubAgentResult dataclasses."""

    def test_subagent_defaults(self):
        agent = SubAgent(name="test", role="researcher")
        assert agent.system_prompt == ROLE_PROMPTS["researcher"]
        assert agent.tools == ROLE_TOOLS["researcher"]

    def test_subagent_custom_prompt(self):
        agent = SubAgent(name="test", role="coder", system_prompt="Custom prompt")
        assert agent.system_prompt == "Custom prompt"

    def test_subagent_custom_tools(self):
        agent = SubAgent(name="test", role="coder", tools=["read_file"])
        assert agent.tools == ["read_file"]

    def test_subagent_unknown_role_falls_back(self):
        agent = SubAgent(name="test", role="unknown_role_xyz")
        assert agent.system_prompt == ROLE_PROMPTS["researcher"]
        assert agent.tools == ROLE_TOOLS["researcher"]

    def test_result_fields(self):
        r = SubAgentResult(
            agent_name="w1", task="do stuff", result="done",
            success=True, duration_ms=100, tool_calls_made=2, role="coder",
        )
        assert r.success is True
        assert r.duration_ms == 100
        assert r.error == ""


class TestDetectRole:
    """Test role detection from task text."""

    def test_research_keywords(self):
        assert _detect_role("research the topic") == "researcher"
        assert _detect_role("find information about X") == "researcher"

    def test_coder_keywords(self):
        assert _detect_role("implement the feature") == "coder"
        assert _detect_role("write the code for login") == "coder"
        assert _detect_role("fix the bug in parser") == "coder"

    def test_analyst_keywords(self):
        assert _detect_role("analyze the data") == "analyst"
        assert _detect_role("compare options and evaluate") == "analyst"

    def test_reviewer_keywords(self):
        assert _detect_role("please review this output") == "reviewer"
        assert _detect_role("test and verify results") == "reviewer"

    def test_planner_keywords(self):
        assert _detect_role("plan the architecture") == "planner"
        assert _detect_role("design the system structure") == "planner"

    def test_default_is_researcher(self):
        assert _detect_role("do something vague") == "researcher"

    def test_empty_string(self):
        assert _detect_role("") == "researcher"


class TestDecomposeTask:
    """Test task decomposition."""

    def test_empty_task(self):
        assert decompose_task("") == []

    def test_single_task(self):
        result = decompose_task("research the best database options")
        assert len(result) == 1
        assert result[0]["role"] == "researcher"

    def test_split_on_and(self):
        result = decompose_task("research databases and implement the solution")
        assert len(result) >= 2

    def test_split_on_semicolon(self):
        result = decompose_task("analyze the data; write the report")
        assert len(result) >= 2

    def test_split_on_then(self):
        result = decompose_task("plan the approach then implement it")
        assert len(result) >= 2

    def test_subtask_has_required_keys(self):
        result = decompose_task("research X and implement Y")
        for subtask in result:
            assert "task" in subtask
            assert "role" in subtask
            assert "name" in subtask

    def test_short_parts_filtered(self):
        # Parts <= 5 chars should be filtered out
        result = decompose_task("do X and implement the full solution")
        # "do X" is 4 chars, should be filtered
        for subtask in result:
            assert len(subtask["task"]) > 5


class TestRunWorker:
    """Test _run_worker with empty/invalid tasks."""

    def test_empty_task_returns_failure(self):
        result = _run_worker({"task": "", "role": "researcher"})
        assert result.success is False
        assert result.error == "Empty task"

    def test_missing_task_key(self):
        result = _run_worker({"role": "coder"})
        assert result.success is False


class TestSpawnSubagents:
    """Test spawn_subagents."""

    def test_empty_tasks_returns_empty(self):
        result = spawn_subagents([])
        assert result == []

    def test_constants(self):
        assert SUBAGENT_MAX_PARALLEL == 4
        assert SUBAGENT_TIMEOUT_SECONDS == 120
        assert SUBAGENT_MAX_TOOL_LOOPS == 5
