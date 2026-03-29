"""
Checkpoint & Crash Recovery System — Hive-inspired fault tolerance.

Bob can crash mid-task. This module ensures he can pick up where he left off.

How it works:
- Before each major task stage, Bob saves a checkpoint (JSON file)
- If Bob crashes, on restart he finds incomplete checkpoints and resumes
- Checkpoints expire after 24h to prevent stale recovery loops
- Each checkpoint records: owner, task, stage, full state, and metadata

Inspired by Apache Hive's checkpoint/recovery for long-running queries.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mind_clone.services.checkpoint")

# Default checkpoint directory: ~/.mind-clone/checkpoints/
CHECKPOINT_DIR = Path.home() / ".mind-clone" / "checkpoints"


def _ensure_dir() -> Path:
    """Ensure the checkpoint directory exists and return its path."""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    return CHECKPOINT_DIR


def save_checkpoint(
    owner_id: int,
    task_id: str,
    stage: str,
    state: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Save a checkpoint to disk as a JSON file.

    Args:
        owner_id: The owner/user who initiated the task.
        task_id: Unique identifier for the task being checkpointed.
        stage: Current stage name (e.g. 'research', 'code_gen', 'validation').
        state: Full serializable state dict to restore from.
        metadata: Optional extra metadata (backup paths, tool context, etc.).

    Returns:
        The checkpoint_id (filename stem) that can be used to load/complete it.
    """
    _ensure_dir()
    checkpoint_id = f"{owner_id}_{task_id}_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    payload: Dict[str, Any] = {
        "checkpoint_id": checkpoint_id,
        "owner_id": owner_id,
        "task_id": task_id,
        "stage": stage,
        "state": state,
        "metadata": metadata or {},
        "status": "active",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "error": None,
    }

    filepath = CHECKPOINT_DIR / f"{checkpoint_id}.json"
    try:
        filepath.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        logger.info(
            "CHECKPOINT_SAVED id=%s task=%s stage=%s owner=%d",
            checkpoint_id, task_id, stage, owner_id,
        )
    except Exception as exc:
        logger.error("CHECKPOINT_SAVE_FAIL id=%s: %s", checkpoint_id, exc)
        raise

    return checkpoint_id


def load_checkpoint(checkpoint_id: str) -> Optional[Dict[str, Any]]:
    """Load a checkpoint by its ID.

    Args:
        checkpoint_id: The checkpoint identifier returned by save_checkpoint.

    Returns:
        The full checkpoint dict, or None if not found / corrupted.
    """
    filepath = CHECKPOINT_DIR / f"{checkpoint_id}.json"
    if not filepath.exists():
        logger.warning("CHECKPOINT_NOT_FOUND id=%s", checkpoint_id)
        return None

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
        return data
    except Exception as exc:
        logger.error("CHECKPOINT_LOAD_FAIL id=%s: %s", checkpoint_id, exc)
        return None


def complete_checkpoint(checkpoint_id: str) -> bool:
    """Mark a checkpoint as completed (task finished successfully).

    Args:
        checkpoint_id: The checkpoint to mark complete.

    Returns:
        True if successfully updated, False otherwise.
    """
    filepath = CHECKPOINT_DIR / f"{checkpoint_id}.json"
    if not filepath.exists():
        logger.warning("CHECKPOINT_COMPLETE_NOT_FOUND id=%s", checkpoint_id)
        return False

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
        data["status"] = "completed"
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        filepath.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        logger.info("CHECKPOINT_COMPLETED id=%s", checkpoint_id)
        return True
    except Exception as exc:
        logger.error("CHECKPOINT_COMPLETE_FAIL id=%s: %s", checkpoint_id, exc)
        return False


def fail_checkpoint(checkpoint_id: str, error: str) -> bool:
    """Mark a checkpoint as failed with an error message.

    Args:
        checkpoint_id: The checkpoint to mark failed.
        error: Description of what went wrong.

    Returns:
        True if successfully updated, False otherwise.
    """
    filepath = CHECKPOINT_DIR / f"{checkpoint_id}.json"
    if not filepath.exists():
        logger.warning("CHECKPOINT_FAIL_NOT_FOUND id=%s", checkpoint_id)
        return False

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
        data["status"] = "failed"
        data["error"] = error[:2000]
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        filepath.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        logger.info("CHECKPOINT_FAILED id=%s error=%s", checkpoint_id, error[:200])
        return True
    except Exception as exc:
        logger.error("CHECKPOINT_FAIL_UPDATE_ERROR id=%s: %s", checkpoint_id, exc)
        return False


def find_incomplete_checkpoints(owner_id: int) -> List[Dict[str, Any]]:
    """Find all active (incomplete) checkpoints for an owner that are < 24h old.

    Args:
        owner_id: Owner to search checkpoints for.

    Returns:
        List of checkpoint dicts that are still in 'active' status and not stale.
    """
    _ensure_dir()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    results: List[Dict[str, Any]] = []

    for filepath in CHECKPOINT_DIR.glob("*.json"):
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            if data.get("owner_id") != owner_id:
                continue
            if data.get("status") != "active":
                continue
            # Check age — skip if older than 24h
            created = datetime.fromisoformat(data["created_at"])
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created < cutoff:
                continue
            results.append(data)
        except Exception as exc:
            logger.warning("CHECKPOINT_SCAN_SKIP file=%s: %s", filepath.name, exc)
            continue

    logger.info(
        "CHECKPOINT_SCAN owner=%d found=%d incomplete",
        owner_id, len(results),
    )
    return results


def recover_from_checkpoint(checkpoint: Dict[str, Any]) -> Dict[str, Any]:
    """Attempt recovery from a single checkpoint.

    Recovery strategy:
    - If metadata contains 'backup_path', attempt to restore files from backup.
    - Returns a status dict indicating what was recovered.

    Args:
        checkpoint: The full checkpoint dict (from load_checkpoint or find_incomplete).

    Returns:
        Dict with keys: ok, checkpoint_id, stage, recovered_files, message.
    """
    checkpoint_id = checkpoint.get("checkpoint_id", "unknown")
    stage = checkpoint.get("stage", "unknown")
    metadata = checkpoint.get("metadata", {})
    recovered_files: List[str] = []

    try:
        # Attempt file restoration from backup if paths are specified
        backup_path = metadata.get("backup_path")
        restore_target = metadata.get("restore_target")

        if backup_path and restore_target:
            backup = Path(backup_path)
            target = Path(restore_target)
            if backup.exists():
                if backup.is_dir():
                    shutil.copytree(str(backup), str(target), dirs_exist_ok=True)
                    recovered_files = [str(p) for p in backup.rglob("*") if p.is_file()]
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(backup), str(target))
                    recovered_files = [str(target)]
                logger.info(
                    "CHECKPOINT_RESTORE id=%s files=%d",
                    checkpoint_id, len(recovered_files),
                )

        # Mark the checkpoint as completed after successful recovery
        complete_checkpoint(checkpoint_id)

        return {
            "ok": True,
            "checkpoint_id": checkpoint_id,
            "stage": stage,
            "recovered_files": recovered_files,
            "message": f"Recovered from stage '{stage}' — {len(recovered_files)} files restored.",
        }
    except Exception as exc:
        error_msg = f"Recovery failed: {exc}"
        fail_checkpoint(checkpoint_id, error_msg)
        logger.error("CHECKPOINT_RECOVER_FAIL id=%s: %s", checkpoint_id, exc)
        return {
            "ok": False,
            "checkpoint_id": checkpoint_id,
            "stage": stage,
            "recovered_files": [],
            "message": error_msg,
        }


def run_startup_recovery(owner_id: int) -> Dict[str, Any]:
    """Find and recover all incomplete checkpoints for an owner on startup.

    Called during Bob's boot sequence to resume any interrupted work.

    Args:
        owner_id: The owner whose checkpoints to recover.

    Returns:
        Dict with keys: recovered (count), failed (count), details (list).
    """
    incomplete = find_incomplete_checkpoints(owner_id)
    if not incomplete:
        logger.info("STARTUP_RECOVERY owner=%d nothing_to_recover", owner_id)
        return {"recovered": 0, "failed": 0, "details": []}

    recovered = 0
    failed = 0
    details: List[Dict[str, Any]] = []

    for cp in incomplete:
        result = recover_from_checkpoint(cp)
        details.append(result)
        if result.get("ok"):
            recovered += 1
        else:
            failed += 1

    logger.info(
        "STARTUP_RECOVERY owner=%d recovered=%d failed=%d total=%d",
        owner_id, recovered, failed, len(incomplete),
    )
    return {"recovered": recovered, "failed": failed, "details": details}


def cleanup_old_checkpoints(max_age_hours: int = 24) -> int:
    """Delete checkpoint files older than max_age_hours.

    Args:
        max_age_hours: Maximum age in hours before a checkpoint is deleted.

    Returns:
        Number of checkpoints deleted.
    """
    _ensure_dir()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    deleted = 0

    for filepath in CHECKPOINT_DIR.glob("*.json"):
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(data.get("created_at", "2000-01-01"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created < cutoff:
                filepath.unlink()
                deleted += 1
        except Exception as exc:
            logger.warning("CHECKPOINT_CLEANUP_SKIP file=%s: %s", filepath.name, exc)
            continue

    if deleted:
        logger.info("CHECKPOINT_CLEANUP deleted=%d max_age_hours=%d", deleted, max_age_hours)
    return deleted


# ---------------------------------------------------------------------------
# Tool wrapper (callable from Bob's tool registry)
# ---------------------------------------------------------------------------


def tool_checkpoint_status(args: dict) -> dict:
    """Tool wrapper: get checkpoint status and optionally trigger recovery.

    Args (dict):
        owner_id (int): Owner ID (default 1).
        action (str): One of 'status', 'recover', 'cleanup' (default 'status').
        checkpoint_id (str): Specific checkpoint to load (optional).
        max_age_hours (int): For cleanup, max age in hours (default 24).

    Returns:
        Dict with operation results.
    """
    owner_id = int(args.get("owner_id", 1))
    action = str(args.get("action", "status")).lower()

    try:
        if action == "recover":
            result = run_startup_recovery(owner_id)
            return {"ok": True, "action": "recover", **result}

        if action == "cleanup":
            max_age = int(args.get("max_age_hours", 24))
            deleted = cleanup_old_checkpoints(max_age)
            return {"ok": True, "action": "cleanup", "deleted": deleted}

        if action == "load" and args.get("checkpoint_id"):
            cp = load_checkpoint(str(args["checkpoint_id"]))
            if cp:
                return {"ok": True, "action": "load", "checkpoint": cp}
            return {"ok": False, "error": "Checkpoint not found"}

        # Default: status — list incomplete checkpoints
        incomplete = find_incomplete_checkpoints(owner_id)
        return {
            "ok": True,
            "action": "status",
            "owner_id": owner_id,
            "incomplete_count": len(incomplete),
            "checkpoints": [
                {
                    "id": cp["checkpoint_id"],
                    "task": cp.get("task_id"),
                    "stage": cp.get("stage"),
                    "created": cp.get("created_at"),
                }
                for cp in incomplete
            ],
        }
    except Exception as exc:
        logger.error("tool_checkpoint_status error: %s", exc)
        return {"ok": False, "error": str(exc)[:300]}
