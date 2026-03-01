#!/usr/bin/env python3
"""
Bob Agent Loop — Infinite loop runner for parallel agent teams.

Picks tasks from tasks/pending/, executes them with the appropriate
Claude model in isolated Git worktrees, and merges passing changes
to main. Inspired by Anthropic's C compiler agent team architecture.

Usage:
    python bob_agent_loop.py --agent-id agent-1
    python bob_agent_loop.py --agent-id agent-2 --tier-cap haiku
    python bob_agent_loop.py --agent-id agent-1 --max-iterations 5 --fast
"""

import argparse
import json
import logging
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths — resolve relative to this script
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
MIND_CLONE_DIR = SCRIPT_DIR.parent
ROOT_DIR = MIND_CLONE_DIR.parent
TASKS_DIR = ROOT_DIR / "tasks"
WORKTREES_DIR = ROOT_DIR / ".worktrees"
LOG_DIR = MIND_CLONE_DIR / "persist"
LOG_FILE = LOG_DIR / "team_log.jsonl"

# Import shared logic from bob_team_mcp.py
sys.path.insert(0, str(SCRIPT_DIR))
from bob_team_mcp import (
    _classify,
    _build_system_prompt,
    _get_tools,
    _append_log,
    MODELS,
    COOLDOWNS,
    TIER_LABELS,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
STALE_LOCK_MINUTES = 30
IDLE_POLL_SECONDS = 30
TIER_TIMEOUTS = {"haiku": 600, "sonnet": 1800, "opus": 3600}
TIER_ORDER = {"haiku": 0, "sonnet": 1, "opus": 2}
RECLASSIFY_AFTER_FAILURES = 2

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_shutdown_requested = False


def _handle_signal(signum: int, frame: object) -> None:
    """Handle SIGINT/SIGTERM for graceful shutdown."""
    global _shutdown_requested
    _shutdown_requested = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(agent_id: str, verbose: bool = False) -> logging.Logger:
    """Set up per-agent logging to file and console."""
    log = logging.getLogger(f"bob_agent.{agent_id}")
    log.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(logging.Formatter(f"[{agent_id}] %(asctime)s %(levelname)s: %(message)s", datefmt="%H:%M:%S"))
    log.addHandler(ch)

    # File handler
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(LOG_DIR / f"{agent_id}.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(f"[{agent_id}] %(asctime)s %(levelname)s: %(message)s"))
    log.addHandler(fh)

    return log


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------

def ensure_directories() -> None:
    """Create all required task directories if they don't exist."""
    for subdir in ["pending", "in-progress", "completed", "failed", "locks"]:
        (TASKS_DIR / subdir).mkdir(parents=True, exist_ok=True)
    WORKTREES_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Lock management
# ---------------------------------------------------------------------------

def release_stale_locks(log: logging.Logger) -> None:
    """Release locks older than STALE_LOCK_MINUTES and recover tasks."""
    locks_dir = TASKS_DIR / "locks"
    if not locks_dir.exists():
        return

    now = time.time()
    for lock_file in locks_dir.glob("*.lock"):
        age_minutes = (now - lock_file.stat().st_mtime) / 60
        if age_minutes > STALE_LOCK_MINUTES:
            try:
                lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
                task_name = lock_data.get("task_file", "")
                in_progress_path = TASKS_DIR / "in-progress" / task_name

                if in_progress_path.exists():
                    pending_path = TASKS_DIR / "pending" / task_name
                    os.rename(str(in_progress_path), str(pending_path))
                    log.warning(f"Recovered stale task: {task_name} (lock age: {age_minutes:.0f}min)")

                lock_file.unlink(missing_ok=True)
            except Exception as e:
                log.error(f"Error releasing stale lock {lock_file.name}: {e}")


def write_lock(agent_id: str, task_name: str) -> None:
    """Write a lock file for the current agent."""
    lock_file = TASKS_DIR / "locks" / f"{agent_id}.lock"
    lock_data = {
        "agent_id": agent_id,
        "task_file": task_name,
        "claimed_at": datetime.now().isoformat(),
        "pid": os.getpid(),
    }
    lock_file.write_text(json.dumps(lock_data, indent=2), encoding="utf-8")


def release_lock(agent_id: str) -> None:
    """Remove the lock file for the current agent."""
    lock_file = TASKS_DIR / "locks" / f"{agent_id}.lock"
    lock_file.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Task management
# ---------------------------------------------------------------------------

def _extract_priority(content: str) -> int:
    """Extract priority from task content. P1=1, P2=2, P3=3."""
    if "## Priority: P1" in content:
        return 1
    elif "## Priority: P3" in content:
        return 3
    return 2  # default P2


def _get_fail_count(content: str) -> int:
    """Extract fail count from task metadata."""
    for line in content.split("\n"):
        if line.strip().startswith("fail_count:"):
            try:
                return int(line.split(":")[1].strip())
            except (ValueError, IndexError):
                return 0
    return 0


def _get_last_tier(content: str) -> str:
    """Extract last attempted tier from task metadata."""
    for line in content.split("\n"):
        if line.strip().startswith("last_tier:"):
            return line.split(":")[1].strip()
    return ""


def _update_task_metadata(task_path: Path, fail_count: int, last_tier: str) -> None:
    """Update fail_count and last_tier in task file metadata."""
    content = task_path.read_text(encoding="utf-8")

    # Remove existing metadata lines
    lines = content.split("\n")
    lines = [l for l in lines if not l.strip().startswith(("fail_count:", "last_tier:"))]

    # Append metadata
    lines.append(f"\nfail_count: {fail_count}")
    lines.append(f"last_tier: {last_tier}")

    task_path.write_text("\n".join(lines), encoding="utf-8")


def pick_next_task(
    agent_id: str,
    tier_cap: Optional[str],
    log: logging.Logger,
) -> Optional[Path]:
    """Pick the highest-priority unclaimed task respecting tier cap."""
    pending_dir = TASKS_DIR / "pending"
    if not pending_dir.exists():
        return None

    tasks = list(pending_dir.glob("*.md"))
    if not tasks:
        return None

    # Sort by priority then filename
    prioritized = []
    for task_path in tasks:
        content = task_path.read_text(encoding="utf-8")
        priority = _extract_priority(content)
        tier = _classify(content)

        # Tier cap: skip tasks above agent's capability
        if tier_cap and TIER_ORDER.get(tier, 1) > TIER_ORDER.get(tier_cap, 1):
            log.debug(f"Skipping {task_path.name} (tier={tier}, cap={tier_cap})")
            continue

        prioritized.append((priority, task_path.name, task_path))

    prioritized.sort()

    if not prioritized:
        return None

    return prioritized[0][2]


def claim_task(agent_id: str, task_path: Path, log: logging.Logger) -> bool:
    """Atomically claim a task by moving it from pending/ to in-progress/."""
    dest = TASKS_DIR / "in-progress" / task_path.name

    try:
        os.rename(str(task_path), str(dest))
    except (FileNotFoundError, OSError):
        # Another agent grabbed it first
        log.debug(f"Race lost on {task_path.name}, trying next")
        return False

    write_lock(agent_id, task_path.name)
    log.info(f"Claimed task: {task_path.name}")
    return True


def move_task(task_name: str, from_dir: str, to_dir: str) -> None:
    """Move a task file between directories."""
    src = TASKS_DIR / from_dir / task_name
    dst = TASKS_DIR / to_dir / task_name
    if src.exists():
        os.rename(str(src), str(dst))


# ---------------------------------------------------------------------------
# Git worktree management
# ---------------------------------------------------------------------------

def create_worktree(agent_id: str, task_id: str, log: logging.Logger) -> Optional[Path]:
    """Create an isolated Git worktree for this agent/task.

    Uses a unique path per task (agent_id + short hash) so Windows file locks
    on old worktrees never block new tasks.
    """
    # Unique path per task — old locked dirs don't block new ones
    short_hash = abs(hash(task_id)) % 99999
    worktree_name = f"{agent_id}-{short_hash}"
    branch = f"agent/{agent_id}/{task_id}"
    worktree_path = WORKTREES_DIR / worktree_name

    # Best-effort cleanup of old worktrees for this agent
    _cleanup_old_worktrees(agent_id, log)

    # Delete stale branch if it exists from a previous run
    subprocess.run(
        ["git", "branch", "-D", branch],
        capture_output=True, text=True, cwd=str(ROOT_DIR), timeout=10,
    )

    # Remove target dir if it somehow still exists
    if worktree_path.exists():
        import shutil
        shutil.rmtree(str(worktree_path), ignore_errors=True)

    try:
        # Create worktree with a new branch from current HEAD
        result = subprocess.run(
            ["git", "worktree", "add", str(worktree_path), "-b", branch],
            capture_output=True, text=True, cwd=str(ROOT_DIR), timeout=30,
        )
        if result.returncode != 0:
            log.error(f"Failed to create worktree: {result.stderr.strip()}")
            return None

        log.info(f"Created worktree at {worktree_path} on branch {branch}")
        return worktree_path

    except Exception as e:
        log.error(f"Worktree creation error: {e}")
        return None


def _cleanup_old_worktrees(agent_id: str, log: logging.Logger) -> None:
    """Best-effort cleanup of old worktrees for this agent. Non-blocking."""
    import shutil

    if not WORKTREES_DIR.exists():
        return

    for d in WORKTREES_DIR.iterdir():
        if d.is_dir() and d.name.startswith(agent_id):
            try:
                subprocess.run(
                    ["git", "worktree", "remove", str(d), "--force"],
                    capture_output=True, cwd=str(ROOT_DIR), timeout=10,
                )
                if d.exists():
                    shutil.rmtree(str(d), ignore_errors=True)
            except Exception:
                pass  # Skip locked dirs — they'll get cleaned next time

    subprocess.run(
        ["git", "worktree", "prune"],
        capture_output=True, cwd=str(ROOT_DIR), timeout=10,
    )


def remove_worktree(agent_id: str, log: logging.Logger, task_id: str = "") -> None:
    """Remove a Git worktree and its branch. Retries for Windows file locks."""
    import shutil

    worktree_path = WORKTREES_DIR / agent_id

    # Step 1: git worktree remove
    try:
        subprocess.run(
            ["git", "worktree", "remove", str(worktree_path), "--force"],
            capture_output=True, text=True, cwd=str(ROOT_DIR), timeout=30,
        )
    except Exception as e:
        log.warning(f"Worktree remove warning: {e}")

    # Step 2: Force-delete directory with retries (Windows file locks)
    for attempt in range(5):
        if not worktree_path.exists():
            break
        try:
            shutil.rmtree(str(worktree_path))
        except Exception:
            time.sleep(2)  # Wait for Windows to release file locks

    # Step 3: Delete the branch
    if task_id:
        branch = f"agent/{agent_id}/{task_id}"
        subprocess.run(
            ["git", "branch", "-D", branch],
            capture_output=True, text=True, cwd=str(ROOT_DIR), timeout=10,
        )

    # Step 4: Prune stale worktree metadata
    subprocess.run(
        ["git", "worktree", "prune"],
        capture_output=True, cwd=str(ROOT_DIR), timeout=10,
    )

    if worktree_path.exists():
        log.warning(f"Could not fully remove {worktree_path} — will retry on next task")


def merge_to_main(agent_id: str, task_id: str, worktree_path: Path, log: logging.Logger) -> bool:
    """Commit changes in worktree and merge branch to main.

    Handles two scenarios:
    1. Claude CLI left uncommitted changes — we commit them first.
    2. Claude CLI already committed — git status is clean but branch
       has commits ahead of main. We still need to merge.

    Also stashes any dirty working-tree state in the main repo before
    merging, to avoid 'local changes would be overwritten' errors.
    """
    branch = f"agent/{agent_id}/{task_id}"

    try:
        # Step 1: Stage and commit any uncommitted changes in worktree
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(worktree_path), capture_output=True, timeout=30,
        )

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(worktree_path), capture_output=True, text=True, timeout=30,
        )
        if status.stdout.strip():
            commit_result = subprocess.run(
                ["git", "commit", "-m", f"agent({agent_id}): complete {task_id}"],
                cwd=str(worktree_path), capture_output=True, text=True, timeout=30,
            )
            if commit_result.returncode != 0:
                log.error(f"Commit failed: {commit_result.stderr.strip()}")
                return False
            log.info("Committed uncommitted changes in worktree")

        # Step 2: Rebase onto latest main to absorb other agents' merges.
        # This prevents merge conflicts when multiple agents modify the same files.
        main_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(ROOT_DIR), capture_output=True, text=True, timeout=10,
        ).stdout.strip() or "master"

        rebase_result = subprocess.run(
            ["git", "rebase", main_branch],
            cwd=str(worktree_path), capture_output=True, text=True, timeout=60,
        )
        if rebase_result.returncode != 0:
            log.warning(f"Rebase failed, will try direct merge: {rebase_result.stderr.strip()[:200]}")
            subprocess.run(
                ["git", "rebase", "--abort"],
                cwd=str(worktree_path), capture_output=True, timeout=10,
            )

        # Step 3: Check if branch has commits ahead of main
        ahead_check = subprocess.run(
            ["git", "rev-list", "--count", f"HEAD..{branch}"],
            cwd=str(ROOT_DIR), capture_output=True, text=True, timeout=10,
        )
        commits_ahead = int(ahead_check.stdout.strip()) if ahead_check.returncode == 0 else 0

        if commits_ahead == 0:
            log.info(f"Branch {branch} has no commits ahead of main — nothing to merge")
            return True

        log.info(f"Branch {branch} has {commits_ahead} commit(s) to merge")

        # Step 4: Stash dirty working tree in main repo (if any)
        main_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(ROOT_DIR), capture_output=True, text=True, timeout=10,
        )
        stashed = False
        if main_status.stdout.strip():
            stash_result = subprocess.run(
                ["git", "stash", "push", "-m", f"agent-merge-{agent_id}-{task_id}"],
                cwd=str(ROOT_DIR), capture_output=True, text=True, timeout=30,
            )
            stashed = stash_result.returncode == 0
            if stashed:
                log.debug("Stashed main repo working tree before merge")

        # Step 5: Merge branch into main
        current_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(ROOT_DIR), capture_output=True, text=True, timeout=10,
        ).stdout.strip()

        merge_result = subprocess.run(
            ["git", "merge", branch, "--no-edit"],
            cwd=str(ROOT_DIR), capture_output=True, text=True, timeout=60,
        )

        if merge_result.returncode != 0:
            log.error(f"Merge failed: {merge_result.stderr.strip()}")
            subprocess.run(
                ["git", "merge", "--abort"],
                cwd=str(ROOT_DIR), capture_output=True, timeout=10,
            )
            if stashed:
                subprocess.run(
                    ["git", "stash", "pop"],
                    cwd=str(ROOT_DIR), capture_output=True, timeout=30,
                )
            return False

        log.info(f"Merged {branch} to {current_branch} ({commits_ahead} commit(s))")

        # Step 6: Restore stashed working tree
        if stashed:
            subprocess.run(
                ["git", "stash", "pop"],
                cwd=str(ROOT_DIR), capture_output=True, timeout=30,
            )
            log.debug("Restored stashed working tree after merge")

        # Step 6: Delete the feature branch
        subprocess.run(
            ["git", "branch", "-d", branch],
            cwd=str(ROOT_DIR), capture_output=True, timeout=10,
        )
        return True

    except Exception as e:
        log.error(f"Merge error: {e}")
        return False


# ---------------------------------------------------------------------------
# CI gate
# ---------------------------------------------------------------------------

def run_ci_gate(worktree_path: Path, fast: bool, agent_id: str, log: logging.Logger) -> tuple[bool, str]:
    """Run bob_check.py (or fast subset) as CI gate."""
    try:
        if fast:
            # Fast mode: run ~10% of tests randomly, seeded per agent
            test_dir = worktree_path / "mind-clone" / "tests"
            all_tests = list(test_dir.rglob("test_*.py")) if test_dir.exists() else []
            if all_tests:
                seed = hash(agent_id) % 10000
                rng = random.Random(seed)
                count = max(1, len(all_tests) // 10)
                selected = rng.sample(all_tests, min(count, len(all_tests)))
                test_paths = [str(t) for t in selected]

                cmd = ["python", "-m", "pytest", *test_paths, "--tb=short", "-q"]
                log.info(f"Fast mode: running {len(selected)}/{len(all_tests)} tests")
            else:
                cmd = ["python", "-m", "compileall", "-q", str(worktree_path / "mind-clone" / "src")]
        else:
            # Full mode: bob_check.py
            check_script = worktree_path / "mind-clone" / "scripts" / "bob_check.py"
            if check_script.exists():
                cmd = ["python", str(check_script)]
            else:
                # Fallback: compile check + pytest
                cmd = ["python", "-m", "pytest", str(worktree_path / "mind-clone" / "tests"), "--tb=short", "-q"]

        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            cwd=str(worktree_path),
            timeout=300,
        )

        passed = result.returncode == 0
        output = result.stderr[:500] if result.stderr else result.stdout[:500]

        if passed:
            log.info("CI gate PASSED")
        else:
            log.warning(f"CI gate FAILED: {output[:200]}")

        return passed, output

    except subprocess.TimeoutExpired:
        log.error("CI gate timed out (300s)")
        return False, "CI gate timed out after 300 seconds"
    except Exception as e:
        log.error(f"CI gate error: {e}")
        return False, str(e)


# ---------------------------------------------------------------------------
# Knowledge sharing
# ---------------------------------------------------------------------------

def append_progress(message: str) -> None:
    """Append a timestamped line to PROGRESS.md."""
    progress_file = TASKS_DIR / "PROGRESS.md"
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(progress_file, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


def read_shared_knowledge() -> str:
    """Read LESSONS.md and recent PROGRESS.md for agent context."""
    parts = []

    # Read lessons
    lessons_file = TASKS_DIR / "LESSONS.md"
    if lessons_file.exists():
        content = lessons_file.read_text(encoding="utf-8")
        if content.strip():
            parts.append(f"## Lessons Learned\n{content}")

    # Read last 30 lines of progress
    progress_file = TASKS_DIR / "PROGRESS.md"
    if progress_file.exists():
        lines = progress_file.read_text(encoding="utf-8").strip().split("\n")
        recent = "\n".join(lines[-30:])
        if recent.strip():
            parts.append(f"## Recent Progress\n{recent}")

    return "\n\n".join(parts)


def get_recent_git_log(cwd: Path) -> str:
    """Get last 10 commits for inter-agent visibility."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            capture_output=True, text=True, cwd=str(cwd), timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _clean_env() -> dict[str, str]:
    """Build a clean env dict without Claude Code vars to allow nested sessions."""
    blocked = {"CLAUDECODE", "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_ENTRYPOINT"}
    return {k: v for k, v in os.environ.items() if k not in blocked}


def write_failure_analysis(
    agent_id: str, task_name: str, tier: str, elapsed: float,
    error_output: str, log: logging.Logger,
) -> None:
    """Use haiku to generate failure analysis and append to PROGRESS.md."""
    # Ensure we always have some context even if output is empty
    if not error_output or len(error_output.strip()) < 10:
        error_output = f"Task '{task_name}' failed with {tier} model after {elapsed}s. No detailed error output captured."

    analysis_prompt = (
        f"A development task failed. Based on the error output below, write EXACTLY 4 lines:\n"
        f"WHAT WENT WRONG: <one sentence describing the error>\n"
        f"WHAT WAS TRIED: <one sentence about what the agent attempted>\n"
        f"WHY IT FAILED: <one sentence root cause>\n"
        f"SUGGESTION: <one actionable sentence for the next agent to try differently>\n\n"
        f"Task: {task_name}\n"
        f"Model: {tier}\n"
        f"Duration: {elapsed}s\n\n"
        f"Error output:\n{error_output[:2000]}"
    )

    try:
        result = subprocess.run(
            [
                "claude", "-p", analysis_prompt,
                "--model", MODELS["haiku"],
                "--dangerously-skip-permissions",
                "--output-format", "text",
            ],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT_DIR),
            env=_clean_env(), stdin=subprocess.DEVNULL,
        )
        analysis = result.stdout.strip() if result.returncode == 0 else "Analysis unavailable"
    except Exception:
        analysis = "Analysis unavailable (haiku call failed)"

    # Append to PROGRESS.md
    append_progress(
        f"Agent {agent_id} FAILED {task_name} (model: {tier}, {elapsed:.1f}s)\n"
        f"  {analysis}"
    )
    log.info(f"Failure analysis written for {task_name}")


def write_lesson(
    agent_id: str, task_name: str, tier: str, success: bool,
    output: str, log: logging.Logger,
) -> None:
    """Use haiku to distill a lesson and append to LESSONS.md."""
    context = "succeeded" if success else "failed"
    output_text = output[:800] if output else f"Task '{task_name}' {context} with {tier} model."
    lesson_prompt = (
        f"A development task just {context}. Write ONLY one short lesson — a single sentence, "
        f"max 100 characters, starting with a verb. No markdown, no extra text, just the lesson.\n\n"
        f"Task: {task_name}\n"
        f"Output:\n{output_text}"
    )

    try:
        result = subprocess.run(
            [
                "claude", "-p", lesson_prompt,
                "--model", MODELS["haiku"],
                "--dangerously-skip-permissions",
                "--output-format", "text",
            ],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT_DIR),
            env=_clean_env(), stdin=subprocess.DEVNULL,
        )
        lesson = result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        lesson = None

    if lesson:
        date = datetime.now().strftime("%Y-%m-%d")
        lessons_file = TASKS_DIR / "LESSONS.md"
        with open(lessons_file, "a", encoding="utf-8") as f:
            f.write(f"- [{date}] {lesson} ({agent_id}, {task_name})\n")
        log.debug(f"Lesson written: {lesson[:80]}")


# ---------------------------------------------------------------------------
# Re-classification on repeated failure
# ---------------------------------------------------------------------------

def reclassify_task(task_content: str, fail_count: int, last_tier: str, log: logging.Logger) -> str:
    """Re-classify a task after repeated failures at the same tier."""
    # Include failure context in classification
    enhanced = f"{task_content}\n\n[CONTEXT: This task failed {fail_count} times with {last_tier} model.]"
    new_tier = _classify(enhanced)

    if new_tier != last_tier:
        log.info(f"Re-classified from {last_tier} to {new_tier} after {fail_count} failures")
    else:
        log.debug(f"Re-classification unchanged: {new_tier} (still appropriate)")

    return new_tier


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

def agent_loop(
    agent_id: str,
    max_iterations: int = 0,
    tier_cap: Optional[str] = None,
    fast: bool = False,
    log: logging.Logger = logging.getLogger(),
) -> None:
    """The infinite loop: pick → claim → worktree → execute → verify → merge → repeat."""
    iteration = 0
    log.info(f"Agent {agent_id} starting (tier_cap={tier_cap}, fast={fast}, max_iter={max_iterations or 'infinite'})")
    append_progress(f"Agent {agent_id} ONLINE (tier_cap={tier_cap}, fast={fast})")

    while not _shutdown_requested:
        iteration += 1
        if max_iterations > 0 and iteration > max_iterations:
            log.info(f"Reached max iterations ({max_iterations}), exiting")
            break

        # Step 1: Clean up stale locks
        release_stale_locks(log)

        # Step 2: Pick next task
        task_path = pick_next_task(agent_id, tier_cap, log)
        if task_path is None:
            log.debug(f"No tasks available, sleeping {IDLE_POLL_SECONDS}s")
            for _ in range(IDLE_POLL_SECONDS):
                if _shutdown_requested:
                    break
                time.sleep(1)
            continue

        # Step 3: Claim the task
        if not claim_task(agent_id, task_path, log):
            continue

        task_name = task_path.name
        task_content = (TASKS_DIR / "in-progress" / task_name).read_text(encoding="utf-8")
        task_id = task_name.replace(".md", "")

        # Step 4: Classify (with re-classification if needed)
        fail_count = _get_fail_count(task_content)
        last_tier = _get_last_tier(task_content)

        if fail_count >= RECLASSIFY_AFTER_FAILURES and last_tier:
            tier = reclassify_task(task_content, fail_count, last_tier, log)
        else:
            tier = _classify(task_content)

        model = MODELS[tier]
        timeout = TIER_TIMEOUTS[tier]
        cooldown = COOLDOWNS[tier]

        log.info(f"Executing {task_name} with {TIER_LABELS[tier]} (attempt #{fail_count + 1})")

        # Step 5: Create worktree
        worktree_path = create_worktree(agent_id, task_id, log)
        if worktree_path is None:
            log.error("Failed to create worktree, returning task to pending (cooldown 10s)")
            move_task(task_name, "in-progress", "pending")
            release_lock(agent_id)
            # Cooldown to prevent spin loop on persistent worktree errors
            for _ in range(10):
                if _shutdown_requested:
                    break
                time.sleep(1)
            continue

        # Log STARTED only after worktree succeeds (prevents spam on retries)
        append_progress(f"Agent {agent_id} STARTED {task_name} (model: {tier}, attempt: {fail_count + 1})")

        # Step 6: Pull latest main into worktree
        subprocess.run(
            ["git", "pull", "--rebase"],
            cwd=str(worktree_path), capture_output=True, timeout=30,
        )

        # Step 7: Build prompt with shared knowledge
        agent_prompt = (TASKS_DIR / "AGENT_PROMPT.md").read_text(encoding="utf-8")
        shared_knowledge = read_shared_knowledge()
        recent_log = get_recent_git_log(worktree_path)

        full_prompt = (
            f"{agent_prompt}\n\n"
            f"{shared_knowledge}\n\n"
            f"## Recent Commits (by other agents)\n```\n{recent_log}\n```\n\n"
            f"## Current Task\n{task_content}"
        )

        # Step 8: Execute with Claude CLI
        system_prompt = _build_system_prompt(tier)
        allowed_tools = _get_tools(tier)

        # Build clean env — remove Claude Code vars to allow nested sessions
        clean_env = _clean_env()

        start_time = time.time()
        try:
            cmd = [
                "claude", "-p", full_prompt,
                "--model", model,
                "--allowedTools", allowed_tools,
                "--append-system-prompt", system_prompt,
                "--dangerously-skip-permissions",
                "--output-format", "text",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True, text=True,
                timeout=timeout,
                cwd=str(worktree_path),
                env=clean_env,
                stdin=subprocess.DEVNULL,
            )
            elapsed = round(time.time() - start_time, 1)
            exit_code = result.returncode
            stderr_output = result.stderr[:2000] if result.stderr else ""
            stdout_output = result.stdout[:2000] if result.stdout else ""

        except subprocess.TimeoutExpired:
            elapsed = round(time.time() - start_time, 1)
            exit_code = 1
            stderr_output = f"Task timed out after {timeout}s"
            stdout_output = ""
            log.error(f"Task {task_name} timed out ({timeout}s)")

        # Step 9: CI gate
        if exit_code == 0:
            ci_passed, ci_output = run_ci_gate(worktree_path, fast, agent_id, log)
        else:
            ci_passed = False
            ci_output = stderr_output

        # Build combined error context (stderr + stdout + ci output)
        # Claude CLI often puts errors in stdout, so we capture everything
        error_context = "\n".join(filter(None, [
            f"EXIT CODE: {exit_code}",
            f"CI PASSED: {ci_passed}",
            f"STDERR:\n{stderr_output}" if stderr_output else "",
            f"STDOUT (last 1500 chars):\n{stdout_output[-1500:]}" if stdout_output else "",
            f"CI OUTPUT:\n{ci_output}" if ci_output and ci_output != stderr_output else "",
        ]))

        # Step 10: Handle result
        if exit_code == 0 and ci_passed:
            # SUCCESS: merge to main
            merged = merge_to_main(agent_id, task_id, worktree_path, log)
            if merged:
                move_task(task_name, "in-progress", "completed")
                append_progress(f"Agent {agent_id} COMPLETED {task_name} ({elapsed}s)")
                log.info(f"COMPLETED {task_name} in {elapsed}s")

                # Write lesson (success)
                write_lesson(agent_id, task_name, tier, True, stdout_output, log)
            else:
                # Merge failed (conflict) — treat as failure
                move_task(task_name, "in-progress", "pending")
                _update_task_metadata(TASKS_DIR / "pending" / task_name, fail_count + 1, tier)
                write_failure_analysis(agent_id, task_name, tier, elapsed, "Merge conflict with main branch", log)
                write_lesson(agent_id, task_name, tier, False, "Merge conflict", log)
                log.warning(f"Merge conflict on {task_name}, returning to pending")
        else:
            # FAILURE: revert and return to pending
            log.warning(f"FAILED {task_name} in {elapsed}s (exit={exit_code}, ci={ci_passed})")

            # Revert changes in worktree (guard against deleted/invalid dirs)
            if worktree_path and worktree_path.is_dir():
                try:
                    subprocess.run(
                        ["git", "checkout", "--", "."],
                        cwd=str(worktree_path), capture_output=True, timeout=10,
                    )
                except (OSError, subprocess.SubprocessError) as e:
                    log.debug(f"Worktree revert skipped: {e}")

            # Move back to pending (infinite retry)
            move_task(task_name, "in-progress", "pending")
            _update_task_metadata(TASKS_DIR / "pending" / task_name, fail_count + 1, tier)

            # Write failure analysis and lesson with full context
            write_failure_analysis(agent_id, task_name, tier, elapsed, error_context, log)
            write_lesson(agent_id, task_name, tier, False, error_context, log)

        # Step 11: Clean up worktree
        remove_worktree(agent_id, log, task_id=task_id)
        release_lock(agent_id)

        # Step 12: Log to JSONL
        _append_log({
            "agent_id": agent_id,
            "task": task_name,
            "tier": tier,
            "model": model,
            "elapsed_seconds": elapsed,
            "exit_code": exit_code,
            "ci_passed": ci_passed if exit_code == 0 else False,
            "success": exit_code == 0 and ci_passed,
            "attempt": fail_count + 1,
            "timestamp": datetime.now().isoformat(),
        })

        # Step 13: Cooldown
        if not _shutdown_requested:
            log.info(f"Cooldown {cooldown}s (tier: {tier})")
            for _ in range(cooldown):
                if _shutdown_requested:
                    break
                time.sleep(1)

    # Shutdown
    append_progress(f"Agent {agent_id} OFFLINE (completed {iteration - 1} iterations)")
    log.info(f"Agent {agent_id} shutting down after {iteration - 1} iterations")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse args and start the agent loop."""
    parser = argparse.ArgumentParser(
        description="Bob Agent Loop — Infinite loop runner for parallel agent teams",
    )
    parser.add_argument(
        "--agent-id", required=True,
        help="Unique agent identifier (e.g., agent-1)",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=0,
        help="Max tasks to process (0=infinite, default: infinite)",
    )
    parser.add_argument(
        "--tier-cap", choices=["haiku", "sonnet", "opus"],
        help="Only pick tasks at or below this tier (e.g., haiku skips sonnet/opus)",
    )
    parser.add_argument(
        "--fast", action="store_true",
        help="Fast mode: run 10%% random tests instead of full suite",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable verbose/debug logging",
    )

    args = parser.parse_args()

    log = setup_logging(args.agent_id, args.verbose)
    ensure_directories()

    agent_loop(
        agent_id=args.agent_id,
        max_iterations=args.max_iterations,
        tier_cap=args.tier_cap,
        fast=args.fast,
        log=log,
    )


if __name__ == "__main__":
    main()
