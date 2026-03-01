"""
Orchestrator — coordinates the agent team pipeline.

Flow:
  1. Create task branch
  2. Planner creates plan
  3. Coder executes plan
  4. Reviewer reviews changes
     - If rejected: Coder fixes (up to max_retries)
  5. Tester runs tests
     - If failed: Coder fixes (up to max_retries)
  6. Commit and merge to original branch
  7. Cleanup

If anything fails fatally, revert everything.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, Any, Optional

from .config import AgentConfig
from .llm_client import LLMClient
from .workspace import Workspace
from .planner import Planner
from .coder import Coder
from .reviewer import Reviewer
from .tester import Tester

logger = logging.getLogger("mind_clone.agents.orchestrator")


class Orchestrator:
    """Coordinates the full agent pipeline."""

    def __init__(self, config: Optional[AgentConfig] = None):
        self.config = config or AgentConfig()
        self.llm = LLMClient(self.config)
        self.workspace = Workspace(self.config)
        self.planner = Planner(self.llm, self.workspace, self.config)
        self.coder = Coder(self.llm, self.workspace, self.config)
        self.reviewer = Reviewer(self.llm, self.workspace, self.config)
        self.tester = Tester(self.workspace, self.config)
        self._log: list[Dict[str, Any]] = []

    def run(self, task: str) -> Dict[str, Any]:
        """
        Execute a full task pipeline.

        Args:
            task: Natural language description of what to do

        Returns:
            {
                "ok": bool,
                "task": str,
                "branch": str,
                "plan": dict,
                "changes": list,
                "review": dict,
                "tests": dict,
                "error": str,
                "duration_s": float,
                "llm_stats": dict,
                "log": list,
            }
        """
        start = time.time()
        result = {
            "ok": False,
            "task": task,
            "branch": "",
            "plan": {},
            "changes": [],
            "review": {},
            "tests": {},
            "error": "",
            "duration_s": 0,
            "llm_stats": {},
            "log": [],
        }

        self._log_event("start", f"Task: {task[:200]}")

        try:
            result = self._execute_pipeline(task, result)
        except Exception as e:
            result["error"] = f"Pipeline crashed: {e}"
            self._log_event("crash", str(e))
            logger.exception("Orchestrator pipeline crashed")
            # Safety: revert everything
            self.workspace.abort_and_revert()

        result["duration_s"] = round(time.time() - start, 1)
        result["llm_stats"] = self.llm.stats
        result["log"] = self._log

        # Save log to disk
        self._save_log(result)

        return result

    def _execute_pipeline(self, task: str, result: Dict) -> Dict:
        """The actual pipeline steps."""

        # ---- Step 1: Create branch ----
        self._log_event("branch", "Creating task branch")
        branch = self.workspace.create_task_branch(task)
        result["branch"] = branch

        # ---- Step 2: Plan ----
        self._log_event("plan", "Planner creating plan")
        plan = self.planner.create_plan(task)
        result["plan"] = plan

        if not plan.get("ok"):
            result["error"] = f"Planning failed: {plan.get('error', 'unknown')}"
            self._log_event("plan_fail", result["error"])
            self.workspace.abort_and_revert()
            return result

        self._log_event("plan_done", f"{len(plan.get('steps', []))} steps planned")

        # ---- Step 3-5: Code → Review → Test loop ----
        retries = 0
        max_retries = self.config.max_coder_retries

        while retries <= max_retries:
            # ---- Step 3: Code ----
            self._log_event("code", f"Coder executing (attempt {retries + 1})")
            coder_result = self.coder.execute_plan(plan)
            result["changes"] = coder_result.get("changes", [])

            if not coder_result.get("ok") and not coder_result.get("changes"):
                result["error"] = f"Coder failed: {coder_result.get('error', 'unknown')}"
                self._log_event("code_fail", result["error"])
                self.workspace.abort_and_revert()
                return result

            # ---- Quick compile check ----
            quick = self.tester.run_quick_check()
            if not quick["passed"]:
                self._log_event("compile_fail", quick["failure_summary"])
                retries += 1
                if retries > max_retries:
                    result["error"] = f"Compile check failed after {max_retries} retries"
                    self.workspace.abort_and_revert()
                    return result
                continue

            # ---- Step 4: Review ----
            self._log_event("review", "Reviewer checking changes")
            review = self.reviewer.review_changes(plan, coder_result)
            result["review"] = review

            if not review.get("approved"):
                feedback = self.reviewer.get_rejection_feedback(review)
                self._log_event("review_reject", feedback[:300])
                retries += 1
                if retries > max_retries:
                    result["error"] = f"Review rejected after {max_retries} retries"
                    self.workspace.abort_and_revert()
                    return result

                # Ask Coder to fix based on feedback
                for step in plan.get("steps", []):
                    self.coder.apply_review_feedback(step, feedback)
                continue

            self._log_event("review_pass", "Changes approved")

            # ---- Step 5: Test ----
            self._log_event("test", "Tester running full suite")
            test_result = self.tester.run_full_check()
            result["tests"] = test_result

            if not test_result["passed"]:
                self._log_event("test_fail", test_result["failure_summary"][:300])
                retries += 1
                if retries > max_retries:
                    result["error"] = f"Tests failed after {max_retries} retries: {test_result['failure_summary'][:200]}"
                    if self.config.auto_revert_on_failure:
                        self.workspace.abort_and_revert()
                        self._log_event("revert", "Auto-reverted due to test failure")
                    return result

                # Feed test failures back to Coder
                test_feedback = f"TESTS FAILED:\n{test_result['failure_summary']}"
                for step in plan.get("steps", []):
                    self.coder.apply_review_feedback(step, test_feedback)
                continue

            # ---- All checks passed! ----
            self._log_event("test_pass",
                            f"{test_result['tests_passed']} passed, "
                            f"{test_result['tests_failed']} failed")
            break

        # ---- Step 6: Commit and merge ----
        commit_msg = (
            f"feat(agents): {plan.get('summary', task[:60])}\n\n"
            f"Automated by agent team.\n"
            f"Plan: {len(plan.get('steps', []))} steps\n"
            f"Tests: {result['tests'].get('tests_passed', 0)} passed"
        )

        self.workspace.commit_changes(commit_msg)
        self._log_event("commit", commit_msg.split("\n")[0])

        if self.workspace.merge_to_original():
            self.workspace.cleanup_branch()
            self._log_event("merge", f"Merged {branch} to original branch")
            result["ok"] = True
        else:
            result["error"] = "Merge failed — branch preserved for manual review"
            self._log_event("merge_fail", result["error"])

        return result

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log_event(self, event: str, detail: str = ""):
        """Record a pipeline event."""
        entry = {
            "time": datetime.utcnow().isoformat(),
            "event": event,
            "detail": detail,
        }
        self._log.append(entry)
        logger.info("ORCHESTRATOR [%s] %s", event, detail[:200])

    def _save_log(self, result: Dict):
        """Save the complete run log to disk."""
        log_dir = self.config.log_dir
        os.makedirs(log_dir, exist_ok=True)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        slug = result.get("branch", "unknown").replace("/", "_")
        log_path = os.path.join(log_dir, f"{timestamp}_{slug}.json")

        try:
            # Make result JSON-serializable
            safe_result = json.loads(json.dumps(result, default=str))
            with open(log_path, "w") as f:
                json.dump(safe_result, f, indent=2)
            logger.info("Run log saved to %s", log_path)
        except Exception as e:
            logger.error("Failed to save run log: %s", e)
