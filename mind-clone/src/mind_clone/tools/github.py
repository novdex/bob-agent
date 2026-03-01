"""
GitHub / Git integration tools.

Provides 6 git workflow tools: commit, branch, diff, log, push, pull.
All operations run via subprocess against the mind-clone repository.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger("mind_clone.tools.github")

# Repository root: mind-clone/ directory
_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)

# Safety limits
_MAX_OUTPUT_CHARS = 8000
_COMMAND_TIMEOUT = 30


def _run_git(args: list[str], timeout: int = _COMMAND_TIMEOUT) -> dict:
    """Run a git command and return result dict."""
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = result.stdout[:_MAX_OUTPUT_CHARS] if result.stdout else ""
        stderr = result.stderr[:_MAX_OUTPUT_CHARS] if result.stderr else ""
        if result.returncode != 0:
            return {"ok": False, "error": stderr or f"git exited with code {result.returncode}", "stdout": stdout}
        return {"ok": True, "output": stdout, "stderr": stderr}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Git command timed out after {timeout}s"}
    except FileNotFoundError:
        return {"ok": False, "error": "git is not installed or not in PATH"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def tool_git_status(args: dict) -> dict:
    """Show git status of the repository."""
    result = _run_git(["status", "--short"])
    if not result["ok"]:
        return result
    branch_result = _run_git(["branch", "--show-current"])
    branch = branch_result.get("output", "").strip() if branch_result["ok"] else "unknown"
    return {
        "ok": True,
        "branch": branch,
        "status": result["output"],
    }


def tool_git_commit(args: dict) -> dict:
    """Stage files and create a commit.

    Args:
        message: Commit message (required)
        files: List of files to stage (default: all changed files)
    """
    message = str(args.get("message", "")).strip()
    if not message:
        return {"ok": False, "error": "Commit message is required"}

    files = args.get("files", [])
    if isinstance(files, str):
        files = [f.strip() for f in files.split(",") if f.strip()]

    # Stage files
    if files:
        add_result = _run_git(["add"] + files)
    else:
        add_result = _run_git(["add", "-A"])
    if not add_result["ok"]:
        return {"ok": False, "error": f"git add failed: {add_result['error']}"}

    # Check if there's anything to commit
    diff_result = _run_git(["diff", "--cached", "--stat"])
    if diff_result["ok"] and not diff_result["output"].strip():
        return {"ok": False, "error": "Nothing to commit (no staged changes)"}

    # Commit
    commit_result = _run_git(["commit", "-m", message])
    if not commit_result["ok"]:
        return commit_result

    return {
        "ok": True,
        "message": message,
        "output": commit_result["output"],
    }


def tool_git_branch(args: dict) -> dict:
    """Create, switch, list, or delete branches.

    Args:
        action: One of "list", "create", "switch", "delete" (default: "list")
        name: Branch name (required for create/switch/delete)
    """
    action = str(args.get("action", "list")).lower()
    name = str(args.get("name", "")).strip()

    if action == "list":
        result = _run_git(["branch", "-a"])
        return {"ok": True, "branches": result.get("output", "")} if result["ok"] else result

    if not name:
        return {"ok": False, "error": f"Branch name is required for action '{action}'"}

    if action == "create":
        return _run_git(["checkout", "-b", name])
    elif action == "switch":
        return _run_git(["checkout", name])
    elif action == "delete":
        return _run_git(["branch", "-d", name])
    else:
        return {"ok": False, "error": f"Unknown action: {action}. Use list/create/switch/delete"}


def tool_git_diff(args: dict) -> dict:
    """Show changes in the working directory or staged area.

    Args:
        staged: If true, show staged changes only (default: false)
        file_path: Optional specific file to diff
    """
    staged = bool(args.get("staged", False))
    file_path = str(args.get("file_path", "")).strip()

    git_args = ["diff"]
    if staged:
        git_args.append("--cached")
    git_args.append("--stat")
    if file_path:
        git_args.extend(["--", file_path])

    stat_result = _run_git(git_args)

    # Also get the actual diff (limited)
    detail_args = ["diff"]
    if staged:
        detail_args.append("--cached")
    if file_path:
        detail_args.extend(["--", file_path])

    detail_result = _run_git(detail_args)

    return {
        "ok": True,
        "stat": stat_result.get("output", "") if stat_result["ok"] else "",
        "diff": detail_result.get("output", "")[:_MAX_OUTPUT_CHARS] if detail_result["ok"] else "",
    }


def tool_git_log(args: dict) -> dict:
    """Show recent commit history.

    Args:
        count: Number of commits to show (default: 10)
        oneline: If true, use compact format (default: true)
    """
    count = min(int(args.get("count", 10)), 50)
    oneline = bool(args.get("oneline", True))

    git_args = ["log", f"-{count}"]
    if oneline:
        git_args.append("--oneline")
    else:
        git_args.extend(["--format=%h %ad %s", "--date=short"])

    return _run_git(git_args)


def tool_git_push(args: dict) -> dict:
    """Push commits to remote repository.

    Args:
        remote: Remote name (default: "origin")
        branch: Branch to push (default: current branch)
        force: Force push (default: false) — use with caution
    """
    remote = str(args.get("remote", "origin")).strip()
    branch = str(args.get("branch", "")).strip()
    force = bool(args.get("force", False))

    git_args = ["push", remote]
    if branch:
        git_args.append(branch)
    if force:
        git_args.append("--force-with-lease")

    return _run_git(git_args, timeout=60)


def tool_git_pull(args: dict) -> dict:
    """Pull latest changes from remote.

    Args:
        remote: Remote name (default: "origin")
        branch: Branch to pull (default: current branch)
    """
    remote = str(args.get("remote", "origin")).strip()
    branch = str(args.get("branch", "")).strip()

    git_args = ["pull", remote]
    if branch:
        git_args.append(branch)

    return _run_git(git_args, timeout=60)
