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
        
        # Checkpoint directory for experiment loops
        self.checkpoint_dir = os.path.join(
            self.config.workspace_root or os.getcwd(),
            ".mind_clone",
            "checkpoints"
        )
        os.makedirs(self.checkpoint_dir, exist_ok=True)
        
        self._checkpoint_file = os.path.join(self.checkpoint_dir, "orchestrator_state.json")

    def has_checkpoint(self) -> bool:
        """
        Check if a checkpoint file exists.
        
        Returns:
            True if checkpoint exists, False otherwise.
        """
        return os.path.exists(self._checkpoint_file)

    def save_checkpoint(self, iteration: int, state: Dict[str, Any]) -> None:
        """
        Save checkpoint with iteration count and experiment state.
        
        Args:
            iteration: Current iteration number
            state: Experiment state to persist
        """
        checkpoint_data = {
            "iteration": iteration,
            "task": state.get("task", ""),
            "branch": state.get("branch", ""),
            "plan": state.get("plan", {}),
            "changes": state.get("changes", []),
            "review": state.get("review", {}),
            "tests": state.get("tests", {}),
            "timestamp": datetime.now().isoformat(),
            "log": self._log,
        }
        
        try:
            with open(self._checkpoint_file, "w") as f:
                json.dump(checkpoint_data, f, indent=2)
            logger.info(f"Checkpoint saved: iteration {iteration}")
        except IOError as e:
            logger.warning(f"Failed to save checkpoint: {e}")

    def load_checkpoint(self) -> Optional[Dict[str, Any]]:
        """
        Load previous checkpoint state if it exists.
        
        Returns:
            Checkpoint data dict or None if no checkpoint exists.
        """
        if not self.has_checkpoint():
            return None
        
        try:
            with open(self._checkpoint_file, "r") as f:
                checkpoint = json.load(f)
            logger.info(f"Loaded checkpoint from iteration {checkpoint.get('iteration', 0)}")
            return checkpoint
        except (IOError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to load checkpoint: {e}")
            return None

    def clear_checkpoint(self) -> None:
        """Remove checkpoint file on successful completion."""
        if self.has_checkpoint():
            try:
                os.remove(self._checkpoint_file)
                logger.info("Checkpoint cleared on successful completion")
            except OSError as e:
                logger.warning(f"Failed to clear checkpoint: {e}")

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
                "resumed": bool,
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
            "resumed": False,
        }

        self._log_event("start", f"Task: {task[:200]}")

        # Check for existing checkpoint and offer resume
        if self.has_checkpoint():
            checkpoint = self.load_checkpoint()
            if checkpoint:
                self._log_event("checkpoint_found", 
                               f"Found checkpoint from iteration {checkpoint.get('iteration', 0)}")
                logger.info(f"Found checkpoint: iteration {checkpoint.get('iteration', 0)}")
                
                # Restore state from checkpoint
                result["resumed"] = True
                self._log = checkpoint.get("log", [])
                result["log"] = self._log
                
                # Return checkpoint info for caller to decide on resume
                result["checkpoint_info"] = {
                    "iteration": checkpoint.get("iteration", 0),
                    "task": checkpoint.get("task", ""),
                    "branch": checkpoint.get("branch", ""),
                    "timestamp": checkpoint.get("timestamp", ""),
                }

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

        # Clean up checkpoint on successful completion
        if result["ok"]:
            self.clear_checkpoint()

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
        iteration = 0

        while retries <= max_retries:
            iteration += 1
            
            # ---- Step 3: Code ----
            self._log_event("code", f"Coder executing (attempt {retries + 1})")
            coder_result = self.coder.execute_plan(plan)
            result["changes"] = coder_result.get("changes", [])
            
            if not coder_result.get("ok"):
                result["error"] = f"Coder failed: {coder_result.get('error', 'unknown')}"
                self._log_event("code_fail", result["error"])
                self.workspace.abort_and_revert()
                return result

            self._log_event("code_done", f"{len(result['changes'])} changes made")

            # ---- Step 4: Review ----
            self._log_event("review", "Reviewer evaluating changes")
            review = self.reviewer.review(task, plan, result["changes"])
            result["review"] = review

            if not review.get("approved"):
                retries += 1
                if retries > max_retries:
                    result["error"] = f"Review rejected after {max_retries} retries: {review.get('reason', 'unknown')}"
                    self._log_event("review_rejected", result["error"])
                    self.workspace.abort_and_revert()
                    return result
                
                self._log_event("review_retry", f"Review rejected, retry {retries}/{max_retries}")
                continue

            self._log_event("review_approved", "Review passed")

            # ---- Step 5: Test ----
            self._log_event("test", "Tester running tests")
            tests = self.tester.run_tests()
            result["tests"] = tests

            if not tests.get("ok"):
                retries += 1
                if retries > max_retries:
                    result["error"] = f"Tests failed after {max_retries} retries: {tests.get('error', 'unknown')}"
                    self._log_event("test_retry_failed", result["error"])
                    self.workspace.abort_and_revert()
                    return result
                
                self._log_event("test_retry", f"Tests failed, retry {retries}/{max_retries}")
                continue

            self._log_event("test_passed", "All tests passed")
            break

        # ---- Step 6: Commit and merge ----
        self._log_event("commit", "Committing changes")
        commit = self.workspace.commit_and_merge()
        
        if not commit.get("ok"):
            result["error"] = f"Commit/merge failed: {commit.get('error', 'unknown')}"
            self._log_event("commit_fail", result["error"])
            self.workspace.abort_and_revert()
            return result

        self._log_event("commit_done", f"Committed: {commit.get('commit_hash', 'unknown')}")
        result["commit"] = commit

        # ---- Success! ----
        result["ok"] = True
        self._log_event("success", "Pipeline completed successfully")

        # ---- Step 7: Cleanup ----
        self.workspace.cleanup()
        self._log_event("cleanup", "Cleanup completed")

        return result

    def _log_event(self, event: str, message: str) -> None:
        """Append an event to the log."""
        entry = {
            "event": event,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        }
        self._log.append(entry)
        logger.debug(f"[{event}] {message}")

    def _save_log(self, result: Dict[str, Any]) -> None:
        """Save execution log to disk."""
        log_dir = os.path.join(self.config.workspace_root or os.getcwd(), ".mind_clone", "logs")
        os.makedirs(log_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(log_dir, f"run_{timestamp}.json")
        
        try:
            with open(log_file, "w") as f:
                json.dump(result, f, indent=2, default=str)
            logger.info(f"Log saved to {log_file}")
        except IOError as e:
            logger.warning(f"Failed to save log: {e}")