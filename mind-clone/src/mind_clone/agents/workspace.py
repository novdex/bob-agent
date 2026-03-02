"""
Workspace manager — git branches, file I/O, safety rails.

Handles all filesystem and git operations for the agent team.
Every task runs on an isolated branch. Tests must pass before merge.
Auto-revert on failure.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from .config import AgentConfig

logger = logging.getLogger("mind_clone.agents.workspace")


class Workspace:
    """Manages git branches and file operations for agent tasks."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.root = Path(config.repo_root)
        self._original_branch: Optional[str] = None
        self._task_branch: Optional[str] = None

    # ------------------------------------------------------------------
    # Git operations
    # ------------------------------------------------------------------

    def _run_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a git command in the repo root."""
        cmd = ["git", "-C", str(self.root)] + list(args)
        logger.debug("git: %s", " ".join(cmd))
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=check,
        )

    def current_branch(self) -> str:
        """Get the current branch name."""
        result = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        return result.stdout.strip()

    def is_clean(self) -> bool:
        """Check if the working tree is clean."""
        result = self._run_git("status", "--porcelain")
        return result.stdout.strip() == ""

    def create_task_branch(self, task_name: str) -> str:
        """
        Create and switch to a new branch for a task.

        Args:
            task_name: Human-readable task name (will be slugified)

        Returns:
            Branch name created
        """
        self._original_branch = self.current_branch()
        slug = re.sub(r"[^a-z0-9]+", "-", task_name.lower()).strip("-")[:50]
        branch = f"{self.config.branch_prefix}{slug}"

        # Check if branch exists already
        result = self._run_git("branch", "--list", branch)
        if result.stdout.strip():
            # Branch exists — delete it first
            self._run_git("branch", "-D", branch)

        self._run_git("checkout", "-b", branch)
        self._task_branch = branch
        logger.info("Created task branch: %s", branch)
        return branch

    def commit_changes(self, message: str) -> bool:
        """
        Stage all changes and commit.

        Returns:
            True if commit was made, False if nothing to commit
        """
        if self.is_clean():
            logger.info("No changes to commit")
            return False

        self._run_git("add", "-A")
        self._run_git("commit", "-m", message)
        logger.info("Committed: %s", message)
        return True

    def merge_to_original(self) -> bool:
        """
        Merge task branch back to the original branch.

        Returns:
            True if merge succeeded
        """
        if not self._original_branch or not self._task_branch:
            logger.error("No task branch to merge")
            return False

        self._run_git("checkout", self._original_branch)
        result = self._run_git("merge", self._task_branch, "--no-ff",
                                "-m", f"Merge {self._task_branch}", check=False)
        if result.returncode != 0:
            logger.error("Merge failed: %s", result.stderr)
            return False

        logger.info("Merged %s into %s", self._task_branch, self._original_branch)
        return True

    def abort_and_revert(self) -> None:
        """Abandon task branch and return to original branch."""
        if not self._original_branch:
            return

        # Discard all changes
        self._run_git("checkout", "--", ".", check=False)
        self._run_git("clean", "-fd", check=False)
        self._run_git("checkout", self._original_branch, check=False)

        if self._task_branch:
            self._run_git("branch", "-D", self._task_branch, check=False)
            logger.warning("Reverted: deleted branch %s", self._task_branch)

        self._task_branch = None

    def cleanup_branch(self) -> None:
        """Delete the task branch after successful merge."""
        if self._task_branch:
            self._run_git("branch", "-d", self._task_branch, check=False)
            self._task_branch = None

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def read_file(self, rel_path: str) -> Optional[str]:
        """Read a file relative to repo root. Returns None if not found."""
        full = self.root / rel_path
        if not full.exists() or not full.is_file():
            return None
        try:
            return full.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.error("Failed to read %s: %s", rel_path, e)
            return None

    def write_file(self, rel_path: str, content: str) -> bool:
        """
        Write content to a file. Creates parent dirs if needed.
        Refuses to write to protected paths.

        Returns:
            True if written successfully
        """
        if self.config.is_protected(rel_path):
            logger.warning("BLOCKED: attempted write to protected path: %s", rel_path)
            return False

        full = self.root / rel_path
        try:
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
            logger.info("Wrote %d bytes to %s", len(content), rel_path)
            return True
        except Exception as e:
            logger.error("Failed to write %s: %s", rel_path, e)
            return False

    def list_files(self, pattern: str = "**/*.py", exclude_dirs: Optional[List[str]] = None) -> List[str]:
        """
        List files matching a glob pattern, relative to repo root.

        Args:
            pattern: Glob pattern (default: all Python files)
            exclude_dirs: Directory prefixes to exclude

        Returns:
            List of relative file paths
        """
        exclude = exclude_dirs or ["__pycache__", ".git", "node_modules", ".venv", "persist"]
        files = []
        for f in self.root.glob(pattern):
            rel = str(f.relative_to(self.root))
            if any(rel.startswith(ex) or f"/{ex}/" in f"/{rel}" for ex in exclude):
                continue
            files.append(rel)
        return sorted(files)

    def file_exists(self, rel_path: str) -> bool:
        """Check if a file exists."""
        return (self.root / rel_path).is_file()

    def get_diff(self) -> str:
        """Get the current git diff (staged + unstaged)."""
        result = self._run_git("diff", "HEAD", check=False)
        return result.stdout

    # ------------------------------------------------------------------
    # Test runner
    # ------------------------------------------------------------------

    def run_tests(self, timeout: int = 300) -> Tuple[bool, str]:
        """
        Run the test suite.

        Returns:
            (passed: bool, output: str)
        """
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "--tb=short", "-q", "--no-header"],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.root),
            )
            passed = result.returncode == 0
            # stderr first — collection errors live here
            stderr_text = result.stderr.strip()
            stdout_text = result.stdout.strip()
            parts = []
            if stderr_text:
                parts.append(stderr_text[:2000])
            if stdout_text:
                parts.append(stdout_text[-3000:])
            output = "\n".join(parts)
            return passed, output
        except subprocess.TimeoutExpired:
            return False, f"Tests timed out after {timeout}s"
        except Exception as e:
            return False, f"Test runner error: {e}"

    def run_compile_check(self) -> Tuple[bool, str]:
        """Run compile check on all Python files."""
        try:
            result = subprocess.run(
                ["python", "-m", "compileall", "-q", "src/"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.root),
            )
            return result.returncode == 0, result.stderr[:1000]
        except Exception as e:
            return False, str(e)
