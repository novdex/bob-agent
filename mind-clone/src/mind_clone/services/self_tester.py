"""
Self-Testing Loop — Bob writes and runs tests for his own features.

After building anything new, Bob auto-generates unit tests,
runs them, and flags failures. Catches regressions before they matter.
"""
from __future__ import annotations
import json
import logging
import subprocess
from pathlib import Path
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.self_tester")
_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
_TEST_DIR = Path(_REPO_ROOT) / "tests" / "unit"


def generate_tests_for_service(service_name: str, service_code: str) -> Optional[str]:
    """Use LLM to generate pytest tests for a service."""
    from ..agent.llm import call_llm
    prompt = [{
        "role": "user",
        "content": (
            f"Write 3-5 pytest unit tests for this Python service.\n"
            f"Service name: {service_name}\n\n"
            f"Code (excerpt):\n```python\n{service_code[:2000]}\n```\n\n"
            f"Write tests that:\n"
            f"- Import the module correctly\n"
            f"- Test key functions with mock DB/LLM calls\n"
            f"- Use pytest fixtures and mocking\n"
            f"- Are runnable without network/DB\n\n"
            f"Return ONLY pytest code, no explanations."
        ),
    }]
    try:
        result = call_llm(prompt, temperature=0.2)
        code = ""
        if isinstance(result, dict) and result.get("ok"):
            code = result.get("content", "")
            choices = result.get("choices", [])
            if choices:
                code = choices[0].get("message", {}).get("content", code)
        elif isinstance(result, str):
            code = result
        code = code.strip()
        if code.startswith("```"):
            lines = code.split("\n")
            code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        if "def test_" in code:
            return code.strip()
    except Exception as e:
        logger.debug("TEST_GEN_FAIL: %s", str(e)[:80])
    return None


def run_tests(test_file: str = None) -> dict:
    """Run pytest and return results."""
    cmd = ["python", "-m", "pytest"]
    if test_file:
        cmd.append(test_file)
    else:
        cmd.extend(["tests/unit/", "-q", "--tb=short",
                    "--ignore=tests/unit/test_agents.py",
                    "--ignore=tests/unit/test_knowledge.py"])
    try:
        result = subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True, timeout=90)
        passed = result.returncode == 0
        output = (result.stdout + result.stderr)[-2000:]
        return {"ok": True, "passed": passed, "output": output}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Tests timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_run_self_tests(args: dict) -> dict:
    """Tool: Run Bob's full test suite and return results."""
    test_file = args.get("test_file")
    return run_tests(test_file)


def tool_generate_tests(args: dict) -> dict:
    """Tool: Generate pytest tests for a service file."""
    service_name = str(args.get("service_name", "")).strip()
    service_file = str(args.get("service_file", "")).strip()
    if not service_name or not service_file:
        return {"ok": False, "error": "service_name and service_file required"}
    try:
        code = Path(_REPO_ROOT, service_file).read_text(encoding="utf-8")[:3000]
    except Exception as e:
        return {"ok": False, "error": f"Cannot read file: {e}"}
    tests = generate_tests_for_service(service_name, code)
    if not tests:
        return {"ok": False, "error": "LLM did not generate valid tests"}
    # Save the test file
    test_path = _TEST_DIR / f"test_{service_name}.py"
    try:
        test_path.write_text(tests, encoding="utf-8")
        return {"ok": True, "test_file": str(test_path), "tests_preview": tests[:300]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


from typing import Optional
