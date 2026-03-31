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
            with open(self._checkpoint_file, "w", encoding="utf-8") as f:
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
            with open(self._checkpoint_file, "r", encoding="utf-8") as f:
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

    def _log_event(self, event: str, message: str) -> None:
        """Append a timestamped log entry."""
        self._log.append({
            "event": event,
            "message": message,
            "ts": datetime.now().isoformat(),
        })

    def _save_log(self, result: Dict[str, Any]) -> None:
        """Persist run log to disk."""
        log_path = os.path.join(self.checkpoint_dir, "run_log.json")
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result) + "\n")
        except IOError as e:
            logger.warning(f"Failed to save log: {e}")

    def _resume_from_checkpoint(
        self, 
        task: str, 
        result: Dict[str, Any], 
        checkpoint: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Resume execution from a checkpoint.
        
        Args:
            task: Current task (may differ from checkpoint task)
            result: Current result dict to populate
            checkpoint: Loaded checkpoint data
            
        Returns:
            Populated result dict after resume attempt
        """
        self._log_event("resume_start", "Starting resume from checkpoint")
        
        iteration = checkpoint.get("iteration", 0)
        current_state = {
            "task": task,
            "branch": checkpoint.get("branch", ""),
            "plan": checkpoint.get("plan", {}),
            "changes": checkpoint.get("changes", []),
            "review": checkpoint.get("review", {}),
            "tests": checkpoint.get("tests", {}),
            "iteration": iteration,
        }
        
        # Restore workspace to checkpoint state if possible
        branch = checkpoint.get("branch", "")
        if branch:
            try:
                self.workspace.checkout_branch(branch)
                self._log_event("resume_branch", f"Checked out branch: {branch}")
            except Exception as e:
                logger.warning(f"Failed to restore branch: {e}")
                self._log_event("resume_branch_failed", str(e))
        
        # Continue from where we left off
        # The checkpoint contains the full state, so we can continue
        # the pipeline from the appropriate stage
        result["branch"] = current_state["branch"]
        result["plan"] = current_state["plan"]
        result["changes"] = current_state["changes"]
        result["review"] = current_state["review"]
        result["tests"] = current_state["tests"]
        result["resumed"] = True
        result["checkpoint_info"] = {
            "iteration": iteration,
            "task": checkpoint.get("task", ""),
            "branch": current_state["branch"],
            "timestamp": checkpoint.get("timestamp", ""),
            "resumed_from": "checkpoint",
        }
        
        self._log_event("resume_complete", f"Resuming at iteration {iteration}")
        
        return result

    def _execute_pipeline(
        self, 
        task: str, 
        result: Dict[str, Any],
        start_iteration: int = 0
    ) -> Dict[str, Any]:
        """
        Execute the main agent pipeline.
        
        Args:
            task: Natural language description of what to do
            result: Result dict to populate
            start_iteration: Starting iteration number (for resume)
            
        Returns:
            Populated result dict
        """
        iteration = start_iteration
        max_iterations = self.config.max_retries + 1
        
        while iteration < max_iterations:
            self._log_event("iteration_start", f"Iteration {iteration + 1}/{max_iterations}")
            
            try:
                # 1. Create task branch
                branch = self.workspace.create_task_branch(task)
                result["branch"] = branch
                self._log_event("branch_created", branch)

                # 2. Planner creates plan
                self._log_event("phase", "planning")
                plan = self.planner.create_plan(task)
                result["plan"] = plan
                self._log_event("plan_created", str(plan.get("summary", "")))
                
                # Save checkpoint after planning phase
                self.save_checkpoint(iteration, {
                    "task": task,
                    "branch": branch,
                    "plan": plan,
                    "changes": result.get("changes", []),
                    "review": result.get("review", {}),
                    "tests": result.get("tests", {}),
                })

                # 3. Coder executes plan
                self._log_event("phase", "coding")
                changes = self.coder.execute_plan(plan)
                result["changes"] = changes
                self._log_event("changes_made", f"{len(changes)} changes")
                
                # Save checkpoint after coding phase
                self.save_checkpoint(iteration, {
                    "task": task,
                    "branch": branch,
                    "plan": plan,
                    "changes": changes,
                    "review": result.get("review", {}),
                    "tests": result.get("tests", {}),
                })

                # 4. Reviewer reviews changes
                self._log_event("phase", "review")
                review = self.reviewer.review_changes(changes)
                result["review"] = review
                self._log_event("review_complete", f"approved={review.get('approved', False)}")
                
                # Save checkpoint after review phase
                self.save_checkpoint(iteration, {
                    "task": task,
                    "branch": branch,
                    "plan": plan,
                    "changes": changes,
                    "review": review,
                    "tests": result.get("tests", {}),
                })

                if not review.get("approved", False):
                    # If rejected, Coder fixes (up to max_retries)
                    self._log_event("review_rejected", review.get("reason", "No reason provided"))
                    iteration += 1
                    if iteration < max_iterations:
                        self._log_event("retry", f"Attempting fix, iteration {iteration + 1}")
                        # Save checkpoint before retry
                        self.save_checkpoint(iteration, {
                            "task": task,
                            "branch": branch,
                            "plan": plan,
                            "changes": changes,
                            "review": review,
                            "tests": result.get("tests", {}),
                        })
                        continue
                    else:
                        self._log_event("max_retries_reached", "Giving up after max retries")
                        result["status"] = "failed"
                        result["failure_reason"] = "review_rejected_max_retries"
                        self._save_log(result)
                        return result

                # 5. Tester runs tests
                self._log_event("phase", "testing")
                tests = self.tester.run_tests()
                result["tests"] = tests
                self._log_event("tests_complete", f"passed={tests.get('passed', 0)}, failed={tests.get('failed', 0)}")
                
                # Save checkpoint after testing phase
                self.save_checkpoint(iteration, {
                    "task": task,
                    "branch": branch,
                    "plan": plan,
                    "changes": changes,
                    "review": review,
                    "tests": tests,
                })

                if not tests.get("all_passed", False):
                    # If tests failed, Coder fixes (up to max_retries)
                    self._log_event("tests_failed", tests.get("message", "Tests failed"))
                    iteration += 1
                    if iteration < max_iterations:
                        self._log_event("retry", f"Attempting fix, iteration {iteration + 1}")
                        # Save checkpoint before retry
                        self.save_checkpoint(iteration, {
                            "task": task,
                            "branch": branch,
                            "plan": plan,
                            "changes": changes,
                            "review": review,
                            "tests": tests,
                        })
                        continue
                    else:
                        self._log_event("max_retries_reached", "Giving up after max retries")
                        result["status"] = "failed"
                        result["failure_reason"] = "tests_failed_max_retries"
                        self._save_log(result)
                        return result

                # 6. Commit and merge to original branch
                self._log_event("phase", "commit_merge")
                commit_result = self.workspace.commit_and_merge(branch)
                result["commit"] = commit_result
                self._log_event("commit_complete", commit_result.get("commit_sha", ""))
                
                # Save final checkpoint before success
                self.save_checkpoint(iteration, {
                    "task": task,
                    "branch": branch,
                    "plan": plan,
                    "changes": changes,
                    "review": review,
                    "tests": tests,
                })

                # Success!
                result["status"] = "success"
                self._log_event("pipeline_complete", "All phases completed successfully")
                self._save_log(result)
                self.clear_checkpoint()
                return result

            except Exception as e:
                self._log_event("fatal_error", str(e))
                logger.exception("Pipeline failed with fatal error")
                
                # Save error checkpoint before cleanup
                self.save_checkpoint(iteration, {
                    "task": task,
                    "branch": result.get("branch", ""),
                    "plan": result.get("plan", {}),
                    "changes": result.get("changes", []),
                    "review": result.get("review", {}),
                    "tests": result.get("tests", {}),
                    "error": str(e),
                })
                
                # Revert everything on fatal error
                self._log_event("revert", "Reverting all changes due to fatal error")
                self.workspace.revert_all()
                
                result["status"] = "failed"
                result["failure_reason"] = f"fatal_error: {str(e)}"
                self._save_log(result)
                return result

        # If we exit the loop without success
        result["status"] = "failed"
        result["failure_reason"] = "max_iterations_exceeded"
        self._save_log(result)
        return result

    def run(self, task: str, resume: bool = False) -> Dict[str, Any]:
        """
        Run the full agent pipeline.
        
        Args:
            task: Natural language description of what to do
            resume: If True, attempt to resume from checkpoint
            
        Returns:
            Result dict with pipeline execution details
        """
        self._log_event("run_start", f"Starting pipeline for task: {task[:100]}...")
        
        result: Dict[str, Any] = {
            "task": task,
            "status": "running",
            "started_at": datetime.now().isoformat(),
        }
        
        # Check for existing checkpoint
        checkpoint = self.load_checkpoint()
        start_iteration = 0
        
        if checkpoint:
            if resume:
                self._log_event("checkpoint_found", f"Resuming from iteration {checkpoint.get('iteration', 0)}")
                result = self._resume_from_checkpoint(task, result, checkpoint)
                start_iteration = checkpoint.get("iteration", 0) + 1
                result["status"] = "running"
                result["resumed"] = True
            else:
                self._log_event("checkpoint_found_skip", "Checkpoint exists but resume=False, starting fresh")
                self.clear_checkpoint()
        else:
            self._log_event("no_checkpoint", "Starting fresh execution")
        
        # Execute the pipeline
        result = self._execute_pipeline(task, result, start_iteration)
        
        result["completed_at"] = datetime.now().isoformat()
        result["log"] = self._log
        
        self._log_event("run_complete", f"Pipeline finished with status: {result.get('status', 'unknown')}")
        
        return result

    def cleanup(self) -> None:
        """Clean up workspace resources."""
        self._log_event("cleanup", "Starting cleanup")
        self.workspace.cleanup()
        self.clear_checkpoint()
        self._log_event("cleanup_complete", "Cleanup finished")