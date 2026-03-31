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
                plan = self.planner.create_plan(task)
                result["plan"] = plan
                self._log_event("plan_created", f"Plan with {len(plan.get('steps', []))} steps")
                
                # Save checkpoint after planning
                self.save_checkpoint(iteration, {
                    "task": task,
                    "branch": branch,
                    "plan": plan,
                    "changes": result["changes"],
                    "review": result["review"],
                    "tests": result["tests"],
                })
                
                # 3. Coder executes plan
                changes = self.coder.execute_plan(plan)
                result["changes"] = changes
                self._log_event("code_executed", f"{len(changes)} changes made")
                
                # Save checkpoint after coding
                self.save_checkpoint(iteration, {
                    "task": task,
                    "branch": branch,
                    "plan": plan,
                    "changes": changes,
                    "review": result["review"],
                    "tests": result["tests"],
                })
                
                # 4. Reviewer reviews changes
                review = self.reviewer.review_changes(changes)
                result["review"] = review
                self._log_event("review_completed", f"Status: {review.get('status', 'unknown')}")
                
                # Save checkpoint after review
                self.save_checkpoint(iteration, {
                    "task": task,
                    "branch": branch,
                    "plan": plan,
                    "changes": changes,
                    "review": review,
                    "tests": result["tests"],
                })
                
                if review.get("status") == "rejected":
                    if iteration < max_iterations - 1:
                        self._log_event("review_rejected", "Attempting fixes")
                        # Coder fixes issues
                        fixes = self.coder.fix_issues(review.get("issues", []))
                        result["changes"].extend(fixes)
                        iteration += 1
                        continue
                    else:
                        result["error"] = "Max review iterations reached"
                        self._log_event("max_iterations_reached", "Review")
                        self.workspace.abort_and_revert()
                        return result
                
                # 5. Tester runs tests
                tests = self.tester.run_tests()
                result["tests"] = tests
                self._log_event("tests_completed", f"Passed: {tests.get('passed', 0)}")
                
                # Save checkpoint after testing
                self.save_checkpoint(iteration, {
                    "task": task,
                    "branch": branch,
                    "plan": plan,
                    "changes": changes,
                    "review": review,
                    "tests": tests,
                })
                
                if not tests.get("ok", False):
                    if iteration < max_iterations - 1:
                        self._log_event("tests_failed", "Attempting fixes")
                        # Coder fixes test failures
                        fixes = self.coder.fix_issues(tests.get("failures", []))
                        result["changes"].extend(fixes)
                        iteration += 1
                        continue
                    else:
                        result["error"] = "Max test iterations reached"
                        self._log_event("max_iterations_reached", "Tests")
                        self.workspace.abort_and_revert()
                        return result
                
                # 6. Commit and merge
                self.workspace.commit_and_merge()
                self._log_event("merge_complete", "Changes merged successfully")
                
                # 7. Cleanup
                self.workspace.cleanup()
                self._log_event("cleanup_complete", "Workspace cleaned up")
                
                # Clear checkpoint on success
                self.clear_checkpoint()
                
                result["ok"] = True
                self._log_event("pipeline_complete", "Task completed successfully")
                return result
                
            except Exception as e:
                error_msg = f"Iteration {iteration} failed: {e}"
                self._log_event("iteration_error", error_msg)
                logger.exception(error_msg)
                
                # Save checkpoint on error for potential resume
                self.save_checkpoint(iteration, {
                    "task": task,
                    "branch": result.get("branch", ""),
                    "plan": result.get("plan", {}),
                    "changes": result.get("changes", []),
                    "review": result.get("review", {}),
                    "tests": result.get("tests", {}),
                })
                
                if iteration >= max_iterations - 1:
                    result["error"] = f"Max iterations reached after error: {e}"
                    self.workspace.abort_and_revert()
                    return result
                
                iteration += 1
        
        result["error"] = "Pipeline failed after all iterations"
        self.workspace.abort_and_revert()
        return result

    def run(self, task: str, resume: bool = False) -> Dict[str, Any]:
        """
        Execute a full task pipeline.

        Args:
            task: Natural language description of what to do
            resume: If True, attempt to resume from checkpoint

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
                "checkpoint_info": dict,
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
            "checkpoint_info": {},
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
                    "plan": checkpoint.get("plan", {}),
                    "changes": checkpoint.get("changes", []),
                    "review": checkpoint.get("review", {}),
                    "tests": checkpoint.get("tests", {}),
                }
                
                # If resume flag is set, skip to the checkpoint state
                if resume:
                    self._log_event("resume_attempt", "Attempting to resume from checkpoint")
                    return self._resume_from_checkpoint(task, result, checkpoint)

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

        # Persist log for debugging
        self._save_log(result)
        
        return result

    def run_experiment(
        self, 
        tasks: list[str], 
        experiment_name: Optional[str] = None,
        resume: bool = False
    ) -> Dict[str, Any]:
        """
        Run multiple tasks as an experiment loop with checkpoint support.
        
        Args:
            tasks: List of natural language task descriptions
            experiment_name: Name for this experiment (used in checkpoint file)
            resume: If True, attempt to resume from checkpoint
            
        Returns:
            {
                "experiment_name": str,
                "ok": bool,
                "results": list[Dict[str, Any]],
                "summary": dict,
                "duration_s": float,
            }
        """
        start = time.time()
        experiment_name = experiment_name or f"experiment_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Create experiment-specific checkpoint directory
        exp_checkpoint_dir = os.path.join(self.checkpoint_dir, experiment_name)
        os.makedirs(exp_checkpoint_dir, exist_ok=True)
        
        exp_checkpoint_file = os.path.join(exp_checkpoint_dir, "experiment_state.json")
        
        # Update checkpoint file for this experiment
        self._checkpoint_file = exp_checkpoint_file
        
        results = []
        completed_tasks = 0
        failed_tasks = 0
        
        self._log_event("experiment_start", f"Starting experiment: {experiment_name}")
        
        # Check for experiment checkpoint
        if self.has_checkpoint():
            checkpoint = self.load_checkpoint()
            if checkpoint and resume:
                completed_tasks = checkpoint.get("completed_tasks", 0)
                results = checkpoint.get("results", [])
                self._log = checkpoint.get("log", [])
                self._log_event("experiment_resume", f"Resuming at task {completed_tasks + 1}")
        
        for i, task in enumerate(tasks[completed_tasks:], start=completed_tasks):
            self._log_event("experiment_task_start", f"Task {i + 1}/{len(tasks)}: {task[:100]}")
            
            task_result = self.run(task, resume=resume and i == completed_tasks)
            results.append(task_result)
            
            if task_result.get("ok", False):
                completed_tasks += 1
                self._log_event("experiment_task_complete", f"Task {i + 1} succeeded")
            else:
                failed_tasks += 1
                self._log_event("experiment_task_failed", f"Task {i + 1} failed: {task_result.get('error', 'unknown')}")
            
            # Save experiment checkpoint after each task
            self.save_checkpoint(i, {
                "task": task,
                "experiment_name": experiment_name,
                "completed_tasks": completed_tasks,
                "results": results,
                "failed_tasks": failed_tasks,
            })
        
        # Clear checkpoint on experiment completion
        self.clear_checkpoint()
        
        self._log_event("experiment_complete", f"Completed: {completed_tasks}, Failed: {failed_tasks}")
        
        summary = {
            "total_tasks": len(tasks),
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
            "success_rate": completed_tasks / len(tasks) if tasks else 0,
        }
        
        return {
            "experiment_name": experiment_name,
            "ok": failed_tasks == 0,
            "results": results,
            "summary": summary,
            "duration_s": round(time.time() - start, 1),
        }