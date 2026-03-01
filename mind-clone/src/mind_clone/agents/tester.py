"""
Tester agent — runs pytest, checks coverage, reports results.

The final gate before changes are committed. If tests fail,
changes go back to the Coder for fixing.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, Any, Tuple

from .workspace import Workspace
from .config import AgentConfig

logger = logging.getLogger("mind_clone.agents.tester")


class Tester:
    """Runs tests and reports results."""

    def __init__(self, workspace: Workspace, config: AgentConfig):
        self.workspace = workspace
        self.config = config

    def run_full_check(self) -> Dict[str, Any]:
        """
        Run compile check + full test suite.

        Returns:
            {
                "passed": bool,
                "compile_ok": bool,
                "tests_passed": int,
                "tests_failed": int,
                "tests_skipped": int,
                "output": str (last N lines),
                "failure_summary": str
            }
        """
        # Phase 1: Compile check
        compile_ok, compile_err = self.workspace.run_compile_check()
        if not compile_ok:
            logger.error("Compile check failed: %s", compile_err)
            return {
                "passed": False,
                "compile_ok": False,
                "tests_passed": 0,
                "tests_failed": 0,
                "tests_skipped": 0,
                "output": compile_err,
                "failure_summary": f"Compile error: {compile_err}",
            }

        # Phase 2: Run tests
        tests_ok, output = self.workspace.run_tests()
        passed, failed, skipped = self._parse_test_counts(output)

        result = {
            "passed": tests_ok and failed == 0,
            "compile_ok": True,
            "tests_passed": passed,
            "tests_failed": failed,
            "tests_skipped": skipped,
            "output": output[-2000:],
            "failure_summary": "",
        }

        if not result["passed"]:
            result["failure_summary"] = self._extract_failure_summary(output)
            logger.warning(
                "Tests FAILED: %d passed, %d failed, %d skipped",
                passed, failed, skipped,
            )
        else:
            logger.info(
                "Tests PASSED: %d passed, %d failed, %d skipped",
                passed, failed, skipped,
            )

        return result

    def run_quick_check(self) -> Dict[str, Any]:
        """
        Run only compile check (fast gate).
        Use this during Coder iterations to catch syntax errors early.
        """
        compile_ok, compile_err = self.workspace.run_compile_check()
        return {
            "passed": compile_ok,
            "compile_ok": compile_ok,
            "output": compile_err if not compile_ok else "OK",
            "failure_summary": compile_err if not compile_ok else "",
        }

    def _parse_test_counts(self, output: str) -> Tuple[int, int, int]:
        """Parse pytest output for pass/fail/skip counts."""
        passed = failed = skipped = 0

        # Match patterns like "1547 passed", "3 failed", "7 skipped"
        m = re.search(r"(\d+)\s+passed", output)
        if m:
            passed = int(m.group(1))

        m = re.search(r"(\d+)\s+failed", output)
        if m:
            failed = int(m.group(1))

        m = re.search(r"(\d+)\s+skipped", output)
        if m:
            skipped = int(m.group(1))

        return passed, failed, skipped

    def _extract_failure_summary(self, output: str) -> str:
        """Extract the most useful failure info from pytest output."""
        lines = output.split("\n")
        summary_lines = []

        # Look for FAILED lines
        for line in lines:
            if "FAILED" in line or "ERROR" in line:
                summary_lines.append(line.strip())
            if len(summary_lines) >= 10:
                break

        # Also grab the short test summary info section
        in_summary = False
        for line in lines:
            if "short test summary" in line.lower():
                in_summary = True
                continue
            if in_summary:
                stripped = line.strip()
                if stripped and not stripped.startswith("="):
                    summary_lines.append(stripped)
                if stripped.startswith("="):
                    break

        return "\n".join(summary_lines[:15]) if summary_lines else "Tests failed (no details captured)"
