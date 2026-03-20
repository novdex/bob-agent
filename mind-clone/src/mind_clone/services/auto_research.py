"""
Karpathy-style autonomous self-improvement experiment loop.

Bob reads his own codebase, generates improvement hypotheses,
implements them, runs tests, measures composite score, keeps
wins and reverts losses. Runs nightly at 2am UTC.

Steered by BOB_RESEARCH.md (human-editable, like Karpathy's program.md).
"""

from __future__ import annotations

import json
import logging
import subprocess
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from ..database.models import (
    ExperimentLog,
    SelfImprovementNote,
    ToolPerformanceLog,
    ExecutionEvent,
    ScheduledJob,
)
from ..database.session import SessionLocal
from ..utils import utc_now_iso

logger = logging.getLogger("mind_clone.services.auto_research")

# Repo root: mind-clone/
_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
_BOB_RESEARCH_MD = str(Path(_REPO_ROOT) / "BOB_RESEARCH.md")
_PYTEST_CMD = [
    "python", "-m", "pytest", "tests/", "-x", "-q",
    "--ignore=tests/unit/test_agents.py",
    "--ignore=tests/unit/test_knowledge.py",
    "--tb=no",
]
_MAX_LINES_CHANGED = 50
_TIMEOUT_TESTS = 120  # seconds


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def measure_composite_score(db: Session, owner_id: int = 1) -> dict:
    """Measure Bob's current composite score from DB metrics."""
    # Tool success rate: last 200 ToolPerformanceLog entries
    perf_rows = (
        db.query(ToolPerformanceLog)
        .filter(ToolPerformanceLog.owner_id == owner_id)
        .order_by(ToolPerformanceLog.id.desc())
        .limit(200)
        .all()
    )
    if perf_rows:
        successes = sum(1 for r in perf_rows if r.success == 1)
        tool_success_rate = successes / len(perf_rows)
    else:
        tool_success_rate = 0.5  # no data → neutral

    # Error rate: last 100 ExecutionEvents
    exec_rows = (
        db.query(ExecutionEvent)
        .filter(ExecutionEvent.owner_id == owner_id)
        .order_by(ExecutionEvent.id.desc())
        .limit(100)
        .all()
    )
    if exec_rows:
        errors = sum(1 for r in exec_rows if getattr(r, "event_type", "") == "error")
        error_rate = errors / len(exec_rows)
    else:
        error_rate = 0.0  # no data → no errors known

    composite = round(0.6 * tool_success_rate + 0.4 * (1.0 - error_rate), 4)

    return {
        "tool_success_rate": round(tool_success_rate, 4),
        "error_rate": round(error_rate, 4),
        "composite": composite,
        "perf_samples": len(perf_rows),
        "exec_samples": len(exec_rows),
        "measured_at": utc_now_iso(),
    }


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _run_git(args: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Run a git command. Returns (success, output)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode == 0, output
    except Exception as e:
        return False, str(e)


def git_snapshot() -> Optional[str]:
    """Stash current changes as a snapshot. Returns stash ref or None."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    label = f"auto_research_snapshot_{ts}"
    ok, out = _run_git(["stash", "push", "-m", label, "--include-untracked"])
    if ok and "No local changes" not in out:
        logger.info("GIT_SNAPSHOT created: %s", label)
        return label
    return None  # nothing to stash or already clean


def git_revert(stash_label: Optional[str]) -> bool:
    """Pop the stash to revert experiment changes."""
    if not stash_label:
        return True
    ok, out = _run_git(["stash", "pop"])
    if ok:
        logger.info("GIT_REVERT success")
    else:
        logger.warning("GIT_REVERT failed: %s", out)
    return ok


def git_commit_experiment(hypothesis_title: str, score_before: float, score_after: float) -> bool:
    """Commit the experiment changes."""
    delta = round(score_after - score_before, 4)
    msg = (
        f"experiment: {hypothesis_title[:60]}\n\n"
        f"Score: {score_before:.4f} → {score_after:.4f} (+{delta:.4f})\n"
        f"Auto-committed by Bob's nightly experiment loop."
    )
    _run_git(["add", "-A"])
    ok, out = _run_git(["commit", "-m", msg])
    if ok:
        logger.info("GIT_COMMIT success: %s", msg[:80])
    else:
        logger.warning("GIT_COMMIT failed: %s", out)
    return ok


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_tests() -> tuple[bool, str]:
    """Run the test suite. Returns (passed, output)."""
    try:
        result = subprocess.run(
            _PYTEST_CMD,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_TESTS,
        )
        passed = result.returncode == 0
        output = (result.stdout + result.stderr)[-2000:]
        return passed, output
    except subprocess.TimeoutExpired:
        return False, "Tests timed out"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Hypothesis generation via LLM
# ---------------------------------------------------------------------------

def _read_bob_research_md() -> str:
    try:
        return Path(_BOB_RESEARCH_MD).read_text(encoding="utf-8")
    except Exception:
        return "# BOB_RESEARCH.md not found"


def _get_recent_failures(db: Session, owner_id: int, limit: int = 5) -> list[dict]:
    rows = (
        db.query(ExperimentLog)
        .filter(ExperimentLog.owner_id == owner_id, ExperimentLog.improved == False)
        .order_by(ExperimentLog.id.desc())
        .limit(limit)
        .all()
    )
    return [{"title": r.hypothesis_title, "error": r.error_msg or ""} for r in rows]


def _get_improvement_notes(db: Session, owner_id: int, limit: int = 5) -> list[str]:
    rows = (
        db.query(SelfImprovementNote)
        .filter(SelfImprovementNote.owner_id == owner_id)
        .order_by(SelfImprovementNote.priority.desc())
        .limit(limit)
        .all()
    )
    return [getattr(r, "content", str(r))[:200] for r in rows]


def _get_weak_tools(db: Session, owner_id: int, limit: int = 5) -> list[dict]:
    """Find tools with below-average success rates."""
    from sqlalchemy import func as sqlfunc
    rows = (
        db.query(
            ToolPerformanceLog.tool_name,
            sqlfunc.avg(ToolPerformanceLog.success).label("avg_success"),
            sqlfunc.count(ToolPerformanceLog.id).label("calls"),
        )
        .filter(ToolPerformanceLog.owner_id == owner_id)
        .group_by(ToolPerformanceLog.tool_name)
        .having(sqlfunc.count(ToolPerformanceLog.id) >= 3)
        .order_by(sqlfunc.avg(ToolPerformanceLog.success).asc())
        .limit(limit)
        .all()
    )
    return [{"tool": r.tool_name, "success_rate": round(float(r.avg_success), 3)} for r in rows]


def generate_hypotheses(db: Session, owner_id: int = 1) -> list[dict]:
    """Ask LLM to generate 3 improvement hypotheses based on current state."""
    from ..agent.llm import call_llm_json_task

    research_md = _read_bob_research_md()
    recent_failures = _get_recent_failures(db, owner_id)
    improvement_notes = _get_improvement_notes(db, owner_id)
    weak_tools = _get_weak_tools(db, owner_id)

    prompt = textwrap.dedent(f"""
    You are Bob's self-improvement research engine. Your job is to propose 3 specific,
    testable code improvement hypotheses for Bob's codebase.

    ## Steering document (BOB_RESEARCH.md):
    {research_md[:1500]}

    ## Recent failed experiments (avoid repeating these):
    {json.dumps(recent_failures, indent=2)}

    ## Known improvement opportunities (SelfImprovementNotes):
    {json.dumps(improvement_notes, indent=2)}

    ## Tools with low success rates:
    {json.dumps(weak_tools, indent=2)}

    ## Instructions:
    Generate exactly 3 hypotheses. Each must:
    - Target a specific file listed in BOB_RESEARCH.md allowed files
    - Describe a concrete, small change (max 50 lines)
    - Be different from the recent failures
    - Be safe and conservative

    Return a JSON object with key "hypotheses" containing an array of 3 objects, each with:
    - title: short name (max 60 chars)
    - target_file: relative path from repo root (e.g. src/mind_clone/services/retro.py)
    - description: what to change and why (max 200 chars)
    - expected_impact: float 0.0-1.0 (estimated score improvement)
    - reasoning: one sentence justification
    """).strip()

    schema = {
        "type": "object",
        "properties": {
            "hypotheses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "target_file": {"type": "string"},
                        "description": {"type": "string"},
                        "expected_impact": {"type": "number"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["title", "target_file", "description", "expected_impact"],
                },
                "minItems": 1,
                "maxItems": 3,
            }
        },
        "required": ["hypotheses"],
    }

    try:
        result = call_llm_json_task(prompt, schema)
        hypotheses = result.get("hypotheses", [])
        # Sort by expected_impact descending
        hypotheses.sort(key=lambda h: float(h.get("expected_impact", 0)), reverse=True)
        logger.info("HYPOTHESES_GENERATED count=%d", len(hypotheses))
        return hypotheses
    except Exception as e:
        logger.error("HYPOTHESIS_GENERATION_FAILED: %s", e)
        return []


# ---------------------------------------------------------------------------
# Hypothesis implementation
# ---------------------------------------------------------------------------

def implement_hypothesis(hypothesis: dict) -> tuple[bool, str]:
    """Use LLM to implement a hypothesis change in the target file."""
    from ..agent.llm import call_llm

    target_file = hypothesis.get("target_file", "")
    description = hypothesis.get("description", "")
    title = hypothesis.get("title", "")

    if not target_file:
        return False, "No target_file specified"

    file_path = Path(_REPO_ROOT) / target_file
    if not file_path.exists():
        return False, f"File not found: {target_file}"

    # Safety check — never modify protected files
    protected = [
        "database/models.py", "config.py", "api/factory.py",
        "auto_research.py", "services/scheduler.py",
    ]
    if any(p in target_file for p in protected):
        return False, f"Target file {target_file} is protected"

    current_content = file_path.read_text(encoding="utf-8")

    prompt = [
        {
            "role": "user",
            "content": (
                f"You are improving Bob's codebase. Make this specific change:\n\n"
                f"Title: {title}\n"
                f"Description: {description}\n\n"
                f"File to modify ({target_file}):\n"
                f"```python\n{current_content[:4000]}\n```\n\n"
                f"Return ONLY the complete modified file content. "
                f"Make the smallest possible change that achieves the description. "
                f"Max 50 lines changed. Do not add imports that don't exist. "
                f"Return plain Python code, no markdown fences."
            ),
        }
    ]

    try:
        response = call_llm(prompt, temperature=0.2)
        new_content = ""
        if isinstance(response, dict):
            # Extract text from response
            choices = response.get("choices", [])
            if choices:
                new_content = choices[0].get("message", {}).get("content", "")
        elif isinstance(response, str):
            new_content = response

        new_content = new_content.strip()
        if new_content.startswith("```"):
            lines = new_content.split("\n")
            new_content = "\n".join(lines[1:-1]) if lines[-1] == "```" else "\n".join(lines[1:])
            new_content = new_content.strip()

        if not new_content or len(new_content) < 50:
            return False, "LLM returned empty or too-short content"

        # Count changed lines
        old_lines = current_content.splitlines()
        new_lines = new_content.splitlines()
        changed = sum(1 for a, b in zip(old_lines, new_lines) if a != b)
        changed += abs(len(new_lines) - len(old_lines))
        if changed > _MAX_LINES_CHANGED:
            return False, f"Too many lines changed ({changed} > {_MAX_LINES_CHANGED})"

        file_path.write_text(new_content, encoding="utf-8")
        logger.info("HYPOTHESIS_IMPLEMENTED file=%s lines_changed=%d", target_file, changed)
        return True, f"Changed {changed} lines in {target_file}"

    except Exception as e:
        return False, f"LLM error: {str(e)[:200]}"


# ---------------------------------------------------------------------------
# Main experiment loop
# ---------------------------------------------------------------------------

def run_experiment_loop(db: Session, owner_id: int = 1) -> dict:
    """
    Full Karpathy-style experiment loop:
    1. Measure baseline composite score
    2. Git snapshot (safe rollback)
    3. Generate hypotheses via LLM
    4. Pick top hypothesis, implement it
    5. Run tests — fail → revert
    6. Measure again
    7. Improved → commit + Telegram report
    8. Worse → revert + log failure
    9. Save ExperimentLog entry
    """
    logger.info("EXPERIMENT_LOOP_START owner_id=%d", owner_id)
    ts = utc_now_iso()

    # Step 1: Baseline
    baseline = measure_composite_score(db, owner_id)
    score_before = baseline["composite"]
    logger.info("BASELINE score=%.4f", score_before)

    # Step 2: Generate hypotheses
    hypotheses = generate_hypotheses(db, owner_id)
    if not hypotheses:
        _save_experiment_log(db, owner_id, "no_hypotheses", "", score_before, score_before,
                             False, False, False, "LLM returned no hypotheses", {})
        return {"ok": False, "reason": "no hypotheses generated", "score_before": score_before}

    hypothesis = hypotheses[0]
    logger.info("HYPOTHESIS_SELECTED title=%s", hypothesis.get("title"))

    # Step 3: Snapshot
    stash_label = git_snapshot()

    # Step 4: Implement
    implemented, impl_msg = implement_hypothesis(hypothesis)
    if not implemented:
        git_revert(stash_label)
        _save_experiment_log(db, owner_id, hypothesis.get("title", ""), hypothesis.get("target_file", ""),
                             score_before, score_before, False, False, True,
                             f"Implementation failed: {impl_msg}", hypothesis)
        return {"ok": False, "reason": impl_msg, "score_before": score_before}

    # Step 5: Run tests
    tests_passed, test_output = run_tests()
    if not tests_passed:
        git_revert(stash_label)
        _save_experiment_log(db, owner_id, hypothesis.get("title", ""), hypothesis.get("target_file", ""),
                             score_before, score_before, False, False, True,
                             f"Tests failed: {test_output[-300:]}", hypothesis)
        return {"ok": False, "reason": "tests failed", "test_output": test_output[-500:], "score_before": score_before}

    # Step 6: Measure again
    after = measure_composite_score(db, owner_id)
    score_after = after["composite"]
    improved = score_after > score_before
    logger.info("EXPERIMENT_MEASURED before=%.4f after=%.4f improved=%s", score_before, score_after, improved)

    if improved:
        # Step 7: Commit win
        git_commit_experiment(hypothesis.get("title", ""), score_before, score_after)
        _save_experiment_log(db, owner_id, hypothesis.get("title", ""), hypothesis.get("target_file", ""),
                             score_before, score_after, True, True, False, None, hypothesis)
        _send_telegram_report(owner_id, hypothesis, score_before, score_after)
        return {
            "ok": True,
            "improved": True,
            "hypothesis": hypothesis.get("title"),
            "score_before": score_before,
            "score_after": score_after,
            "delta": round(score_after - score_before, 4),
        }
    else:
        # Step 8: Revert loss
        git_revert(stash_label)
        _save_experiment_log(db, owner_id, hypothesis.get("title", ""), hypothesis.get("target_file", ""),
                             score_before, score_after, False, False, True,
                             "No improvement detected", hypothesis)
        return {
            "ok": True,
            "improved": False,
            "hypothesis": hypothesis.get("title"),
            "score_before": score_before,
            "score_after": score_after,
            "reason": "No score improvement — reverted",
        }


def _save_experiment_log(
    db: Session, owner_id: int, title: str, target_file: str,
    score_before: float, score_after: float,
    improved: bool, committed: bool, reverted: bool,
    error_msg: Optional[str], hypothesis: dict,
) -> None:
    try:
        entry = ExperimentLog(
            owner_id=owner_id,
            hypothesis_title=title[:200],
            target_file=target_file[:300] if target_file else None,
            score_before=score_before,
            score_after=score_after,
            improved=improved,
            committed=committed,
            reverted=reverted,
            tests_passed=(not reverted and not error_msg),
            error_msg=error_msg[:500] if error_msg else None,
            hypothesis_json=json.dumps(hypothesis, ensure_ascii=False)[:2000],
        )
        db.add(entry)
        db.commit()
    except Exception as e:
        logger.error("SAVE_EXPERIMENT_LOG_FAILED: %s", e)


def _send_telegram_report(owner_id: int, hypothesis: dict, score_before: float, score_after: float) -> None:
    """Send a Telegram message reporting a successful experiment."""
    try:
        from .proactive import send_telegram_message
        delta = round(score_after - score_before, 4)
        msg = (
            f"🧪 *Experiment Success!*\n\n"
            f"*Hypothesis:* {hypothesis.get('title', 'Unknown')}\n"
            f"*File:* `{hypothesis.get('target_file', '?')}`\n"
            f"*Score:* {score_before:.4f} → {score_after:.4f} (+{delta:.4f})\n"
            f"*Change:* {hypothesis.get('description', '')[:100]}\n\n"
            f"Committed and live 🚀"
        )
        send_telegram_message(owner_id, msg)
    except Exception as e:
        logger.warning("TELEGRAM_REPORT_FAILED: %s", e)


# ---------------------------------------------------------------------------
# Tool wrapper (called from tools/registry.py)
# ---------------------------------------------------------------------------

def tool_run_experiment(args: dict) -> dict:
    """Tool: Run Bob's nightly self-improvement experiment loop once."""
    owner_id = int(args.get("_owner_id", 1))
    db = SessionLocal()
    try:
        return run_experiment_loop(db, owner_id)
    except Exception as e:
        logger.error("TOOL_RUN_EXPERIMENT_FAILED: %s", e)
        return {"ok": False, "error": str(e)[:300]}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Nightly job setup
# ---------------------------------------------------------------------------

def ensure_nightly_experiment_job(db: Session, owner_id: int = 1) -> None:
    """Create nightly experiment ScheduledJob if it doesn't exist."""
    from datetime import timedelta

    existing = (
        db.query(ScheduledJob)
        .filter(ScheduledJob.name == "nightly_experiment", ScheduledJob.owner_id == owner_id)
        .first()
    )
    if existing:
        return

    # Calculate next 2am UTC
    now = datetime.now(timezone.utc)
    next_2am = now.replace(hour=2, minute=0, second=0, microsecond=0)
    if next_2am <= now:
        next_2am = next_2am + timedelta(days=1)

    job = ScheduledJob(
        owner_id=owner_id,
        name="nightly_experiment",
        message="Run the self-improvement experiment loop using the run_experiment tool. Read BOB_RESEARCH.md first for context. Generate a hypothesis, implement it, test it, and report back.",
        lane="cron",
        interval_seconds=86400,  # 24 hours
        next_run_at=next_2am,
        enabled=1,
        run_count=0,
    )
    db.add(job)
    db.commit()
    logger.info("NIGHTLY_EXPERIMENT_JOB created next_run=%s", next_2am.isoformat())
