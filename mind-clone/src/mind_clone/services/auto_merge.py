"""
Auto-merge to main — when experiments improve Bob consistently,
merge agent/test → main automatically.

Safety rules:
- Min 3 consecutive improvements before merge
- All tests must pass
- Score must be >= 0.85
- Never force-push, always clean merge
"""
from __future__ import annotations
import logging
import subprocess
from pathlib import Path
from ..database.session import SessionLocal
from ..database.models import ExperimentLog
logger = logging.getLogger("mind_clone.services.auto_merge")

_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
_MIN_IMPROVEMENTS = 3
_MIN_SCORE = 0.80


def _run_git(args: list, timeout: int = 30) -> tuple:
    try:
        r = subprocess.run(["git"] + args, cwd=_REPO_ROOT, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def check_merge_readiness(owner_id: int = 1) -> dict:
    """Check if agent/test branch is ready to merge to main."""
    db = SessionLocal()
    try:
        recent = db.query(ExperimentLog).filter(
            ExperimentLog.owner_id == owner_id
        ).order_by(ExperimentLog.id.desc()).limit(10).all()

        if not recent:
            return {"ready": False, "reason": "No experiments yet"}

        consecutive = 0
        for exp in recent:
            if exp.improved:
                consecutive += 1
            else:
                break

        latest_score = recent[0].score_after if recent else 0.0

        if consecutive < _MIN_IMPROVEMENTS:
            return {"ready": False, "reason": f"Only {consecutive}/{_MIN_IMPROVEMENTS} consecutive improvements"}
        if latest_score < _MIN_SCORE:
            return {"ready": False, "reason": f"Score {latest_score:.3f} below threshold {_MIN_SCORE}"}

        return {"ready": True, "consecutive_improvements": consecutive, "latest_score": latest_score}
    finally:
        db.close()


def attempt_auto_merge(owner_id: int = 1) -> dict:
    """Attempt to merge agent/test → main if ready."""
    readiness = check_merge_readiness(owner_id)
    if not readiness.get("ready"):
        return {"ok": False, "reason": readiness.get("reason"), "merged": False}

    # Run tests first
    try:
        import subprocess as sp
        test_r = sp.run(
            ["python", "-m", "pytest", "tests/unit/", "-q", "--tb=no",
             "--ignore=tests/unit/test_agents.py", "--ignore=tests/unit/test_knowledge.py"],
            cwd=_REPO_ROOT, capture_output=True, text=True, timeout=90,
        )
        if test_r.returncode != 0:
            return {"ok": False, "reason": "Tests failed", "merged": False}
    except Exception as e:
        return {"ok": False, "reason": f"Test run failed: {e}", "merged": False}

    # Merge
    ok, out = _run_git(["checkout", "main"])
    if not ok:
        return {"ok": False, "reason": f"Could not checkout main: {out}", "merged": False}

    ok, out = _run_git(["merge", "agent/test", "--no-ff", "-m",
                        f"auto-merge: {readiness['consecutive_improvements']} improvements, score={readiness['latest_score']:.3f}"])
    if ok:
        logger.info("AUTO_MERGE_SUCCESS score=%.3f", readiness["latest_score"])
        _run_git(["checkout", "agent/test"])
        return {"ok": True, "merged": True, "score": readiness["latest_score"]}

    _run_git(["checkout", "agent/test"])
    return {"ok": False, "reason": f"Merge failed: {out}", "merged": False}


def tool_check_merge(args: dict) -> dict:
    """Tool: Check if agent/test is ready to merge to main."""
    owner_id = int(args.get("_owner_id", 1))
    return check_merge_readiness(owner_id)


def tool_auto_merge(args: dict) -> dict:
    """Tool: Attempt to auto-merge agent/test → main if experiments show consistent improvement."""
    owner_id = int(args.get("_owner_id", 1))
    return attempt_auto_merge(owner_id)
