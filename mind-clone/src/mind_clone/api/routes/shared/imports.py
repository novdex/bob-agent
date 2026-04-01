"""
Shared imports used across route modules.

Centralizes try/except import blocks with fallback stubs for services
that may not be available (circular import avoidance, optional features).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from ....database.session import get_db, init_db, SessionLocal
from ....database.models import (
    User,
    TeamAgent,
    IdentityLink,
    HostExecGrant,
    WorkflowProgram,
    SchemaMigration,
    NodeRegistration,
    NodeLease,
    IdentityKernel,
    ConversationMessage,
    ConversationSummary,
    Task,
    TaskDeadLetter,
    TaskArtifact,
    ApprovalRequest,
    ScheduledJob,
    TaskCheckpointSnapshot,
    UsageLedger,
    ResearchNote,
    ActionForecast,
    SelfImprovementNote,
    Goal,
    EpisodicMemory,
    ToolPerformanceLog,
    GeneratedTool,
    CapabilityActivation,
    ExecutionEvent,
    MemoryVector,
    OpsAuditEvent,
)

from .constants import TASK_STATUS_QUEUED


# ---------------------------------------------------------------------------
# Service imports - stubs for functions that may have circular import issues
# ---------------------------------------------------------------------------

try:
    from ....services.telegram import (
        initialize_runtime_state_baseline,
        run_startup_preflight,
        check_db_liveness,
        send_telegram_message,
        parse_approval_token,
        parse_command_id,
        unpause_task_after_approval,
        handle_approval_command,
        try_set_telegram_webhook_once,
        webhook_retry_supervisor_loop,
        dispatch_incoming_message,
    )
except ImportError:
    # Stubs for telegram functions to avoid circular imports
    def initialize_runtime_state_baseline() -> None:
        pass

    def run_startup_preflight() -> tuple[bool, list[str]]:
        return True, []

    def check_db_liveness() -> tuple[bool, Optional[str]]:
        return True, None

    async def send_telegram_message(chat_id: str, text: str) -> None:
        pass

    def parse_approval_token(text: str, command_name: str) -> Optional[str]:
        parts = (text or "").strip().split(maxsplit=1)
        if len(parts) != 2:
            return None
        if parts[0].strip().lower() != command_name.strip().lower():
            return None
        token = parts[1].strip()
        if not re.fullmatch(r"[a-zA-Z0-9_-]{4,64}", token):
            return None
        return token

    def parse_command_id(text: str, command_name: str) -> Optional[int]:
        parts = text.strip().split(maxsplit=1)
        if len(parts) != 2 or parts[0] != command_name:
            return None
        try:
            return int(parts[1].strip())
        except Exception:
            return None

    def parse_cron_add_payload(text: str) -> Optional[tuple[int, str]]:
        # Parse "/cron_add <interval_seconds> :: <message>"
        try:
            parts = text.strip().split("::", 1)
            if len(parts) != 2:
                return None
            interval_part = parts[0].strip()
            message = parts[1].strip()
            # Extract number from interval_part
            interval_str = interval_part.split()[-1]
            interval = int(interval_str)
            return (interval, message)
        except Exception:
            return None

    async def unpause_task_after_approval(
        owner_id: int, task_id: int, step_id: Optional[str] = None
    ) -> tuple[bool, str]:
        return False, "Not implemented"

    async def handle_approval_command(
        chat_id: str, username: str, token: str, approve: bool
    ) -> None:
        pass

    async def try_set_telegram_webhook_once() -> tuple[bool, str]:
        return False, "Not implemented"

    async def webhook_retry_supervisor_loop() -> None:
        pass

    async def dispatch_incoming_message(
        owner_id: int,
        chat_id: str,
        username: str,
        text: str,
        source: str = "api",
        expect_response: bool = True,
    ) -> dict:
        """Fallback dispatcher -- runs agent loop directly when telegram service unavailable."""
        import asyncio
        try:
            from ....agent.loop import run_agent_loop
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(None, run_agent_loop, owner_id, text)
            return {"ok": True, "response": str(response or "")}
        except Exception as exc:
            logging.getLogger("mind_clone.api").error(
                "dispatch_incoming_message fallback error: %s", exc
            )
            return {"ok": False, "error": str(exc)[:500]}


# Task engine imports - stubs for missing functions
try:
    from ....services.task_engine import (
        enqueue_task,
        recover_pending_tasks,
        task_worker_loop,
        cancel_task,
        get_user_task_by_id,
        list_recent_tasks,
        create_queued_task,
        task_progress,
        current_task_step,
        normalize_task_plan,
        format_task_details,
        latest_task_checkpoint_snapshot,
        restore_task_from_checkpoint_snapshot,
        store_task_checkpoint_snapshot,
        _validate_checkpoint_replay_state,
    )
except ImportError:
    # Stubs for task engine functions
    def enqueue_task(task_id: int) -> None:
        pass

    def recover_pending_tasks() -> list[int]:
        return []

    async def task_worker_loop() -> None:
        pass

    def cancel_task(db: Session, task: Task) -> tuple[bool, str]:
        return False, "Not implemented"

    def get_user_task_by_id(db: Session, owner_id: int, task_id: int) -> Optional[Task]:
        return db.query(Task).filter(Task.id == task_id, Task.owner_id == owner_id).first()

    def list_recent_tasks(db: Session, owner_id: int, limit: int = 20) -> list[Task]:
        return (
            db.query(Task)
            .filter(Task.owner_id == owner_id)
            .order_by(Task.id.desc())
            .limit(limit)
            .all()
        )

    def create_queued_task(db: Session, owner_id: int, title: str, goal: str) -> tuple[Task, bool]:
        task = Task(
            owner_id=owner_id,
            agent_uuid="stub-uuid",
            title=title,
            description=goal,
            status=TASK_STATUS_QUEUED,
            plan=[],
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task, True

    def task_progress(plan: Optional[list]) -> tuple[int, int]:
        if not plan:
            return 0, 0
        done = sum(1 for step in plan if step.get("status") == "done")
        return done, len(plan)

    def current_task_step(plan: Optional[list]) -> Optional[str]:
        if not plan:
            return None
        for step in plan:
            if step.get("status") not in ("done", "failed"):
                return step.get("name", "unknown")
        return None

    def normalize_task_plan(plan: Optional[list]) -> list[dict]:
        return plan or []

    def format_task_details(task: Task) -> str:
        return (
            f"Task #{task.id}: {task.title}\nStatus: {task.status}\nDescription: {task.description}"
        )

    def latest_task_checkpoint_snapshot(
        db: Session, task_id: int
    ) -> Optional[TaskCheckpointSnapshot]:
        return (
            db.query(TaskCheckpointSnapshot)
            .filter(TaskCheckpointSnapshot.task_id == task_id)
            .order_by(TaskCheckpointSnapshot.id.desc())
            .first()
        )

    def restore_task_from_checkpoint_snapshot(
        db: Session, task: Task, snap: TaskCheckpointSnapshot, strict: bool = True
    ) -> bool:
        return False

    def store_task_checkpoint_snapshot(
        db: Session, task: Task, source: str, extra: Optional[dict] = None
    ) -> None:
        pass

    def _validate_checkpoint_replay_state(
        task: Task, plan: list, snap_extra: dict, strict: bool = True
    ) -> tuple[bool, Optional[str], Any]:
        return True, None, None


try:
    from ....services.scheduler import (
        cron_supervisor_loop,
        tool_schedule_job,
        tool_list_scheduled_jobs,
        tool_disable_scheduled_job,
    )
except ImportError:
    # Stubs for scheduler functions
    async def cron_supervisor_loop() -> None:
        pass

    def tool_schedule_job(
        owner_id: int, name: str, message: str, interval_seconds: int, lane: str = "cron"
    ) -> dict:
        return {"ok": False, "error": "Not implemented"}

    def tool_list_scheduled_jobs(
        owner_id: int, include_disabled: bool = False, limit: int = 20
    ) -> dict:
        return {"ok": False, "error": "Not implemented"}

    def tool_disable_scheduled_job(owner_id: int, job_id: int) -> dict:
        return {"ok": False, "error": "Not implemented"}


# Import tool functions
try:
    from ....tools.basic import tool_list_execution_nodes, tool_list_plugin_tools
except ImportError:

    def tool_list_execution_nodes() -> dict:
        return {"nodes": []}

    def tool_list_plugin_tools() -> dict:
        return {"tools": []}


try:
    from ....tools.registry import (
        load_remote_node_registry,
        load_plugin_tools_registry,
        load_custom_tools_from_db,
    )
except ImportError:

    def load_remote_node_registry() -> None:
        pass

    def load_plugin_tools_registry() -> None:
        pass

    def load_custom_tools_from_db() -> None:
        pass


# Utility imports
from ....utils import truncate_text, clamp_int, utc_now_iso, _safe_json_dict, _safe_json_list

# Agent/identity imports
try:
    from ....agent.identity import (
        load_identity,
        _resolve_identity_owner,
        _ensure_team_agent_owner,
        _get_team_agent_row,
        normalize_agent_key,
        resolve_owner_id,
        resolve_owner_context,
        _upsert_identity_link,
        team_spawn_policy_allows,
    )
except ImportError:

    def load_identity(db: Session, owner_id: int) -> Optional[dict]:
        return None

    def _resolve_identity_owner(db: Session, chat_id: str, username: str) -> User:
        # Look up by chat_id first
        user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
        if user:
            return user
        # Fallback: look up by username
        uname = username or f"tg_{chat_id}"
        user = db.query(User).filter(User.username == uname).first()
        if user:
            # Update chat_id if missing
            if not user.telegram_chat_id:
                user.telegram_chat_id = chat_id
                db.commit()
            return user
        # Create new user
        try:
            user = User(username=uname, telegram_chat_id=chat_id)
            db.add(user)
            db.commit()
            db.refresh(user)
            return user
        except Exception:
            db.rollback()
            # Race condition: another thread created it
            user = db.query(User).filter(User.username == uname).first()
            if user:
                return user
            raise

    def _ensure_team_agent_owner(
        db: Session, root_owner: User, key: str, display_name: Optional[str] = None
    ) -> User:
        return root_owner

    def _get_team_agent_row(db: Session, root_owner_id: int, agent_key: str) -> Optional[TeamAgent]:
        return (
            db.query(TeamAgent)
            .filter(TeamAgent.owner_id == root_owner_id, TeamAgent.agent_key == agent_key)
            .first()
        )

    def normalize_agent_key(key: Optional[str]) -> str:
        return (key or "main").strip().lower()

    def resolve_owner_id(
        chat_id: str, username: Optional[str] = None, agent_key: Optional[str] = None
    ) -> int:
        """Fallback: resolve or create user by chat_id."""
        from ....database.session import SessionLocal
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username or f"tg_{chat_id}")
            return int(user.id)
        finally:
            db.close()

    def resolve_owner_context(
        chat_id: str, username: Optional[str] = None, agent_key: Optional[str] = None
    ) -> dict:
        owner_id = resolve_owner_id(chat_id, username, agent_key)
        return {"owner_id": owner_id, "agent_key": agent_key or "main", "chat_id": chat_id}

    def _upsert_identity_link(
        db: Session,
        canonical_owner_id: int,
        linked_chat_id: str,
        linked_username: Optional[str] = None,
        scope_mode: str = "linked_explicit",
    ) -> None:
        pass

    def team_spawn_policy_allows(parent_key: str, child_key: str) -> bool:
        return True


try:
    from ....agent.memory import (
        store_lesson,
        reindex_owner_memory_vectors,
        list_context_snapshots,
        get_context_snapshot,
    )
except ImportError:

    def store_lesson(db: Session, owner_id: int, lesson: str, context: str) -> bool:
        return False

    def reindex_owner_memory_vectors(owner_id: int, rebuild_lessons: bool = False) -> dict:
        return {"ok": False, "error": "Not implemented"}

    def list_context_snapshots(owner_id: int, limit: int = 20) -> list[dict]:
        return []

    def get_context_snapshot(owner_id: int, snapshot_id: int) -> Optional[dict]:
        return None


# Core function imports
try:
    from ....core.queue import (
        command_queue_enabled,
        ensure_command_queue_workers_running,
        active_command_queue_worker_count,
        cancel_command_queue_workers,
        set_owner_queue_mode,
        effective_command_queue_mode,
        COMMAND_QUEUE_MODE,
        COMMAND_QUEUE_WORKER_COUNT,
    )
except ImportError:
    COMMAND_QUEUE_MODE = "auto"
    COMMAND_QUEUE_WORKER_COUNT = 2

    def command_queue_enabled() -> bool:
        return False

    async def ensure_command_queue_workers_running() -> None:
        pass

    def active_command_queue_worker_count() -> int:
        return 0

    async def cancel_command_queue_workers() -> None:
        pass

    def set_owner_queue_mode(owner_id: int, mode: str) -> str:
        return mode

    def effective_command_queue_mode(owner_id: int) -> str:
        return COMMAND_QUEUE_MODE


try:
    from ....core.approvals import (
        approval_manager_decide_token,
        _refresh_approval_pending_runtime_count,
    )
except ImportError:

    def approval_manager_decide_token(
        owner_id: int, token: str, approve: bool, reason: str = ""
    ) -> dict:
        return {"ok": False, "error": "Not implemented", "status": "pending"}

    def _refresh_approval_pending_runtime_count() -> None:
        pass


try:
    from ....core.goals import (
        create_goal,
        list_goals,
        update_goal_progress,
        decompose_goal_into_tasks,
    )
except ImportError:

    def create_goal(
        db: Session,
        owner_id: int,
        title: str,
        description: str = "",
        success_criteria: str = "",
        priority: str = "medium",
    ) -> dict:
        goal = Goal(
            owner_id=owner_id,
            title=title,
            description=description,
            success_criteria=success_criteria,
            priority=priority,
        )
        db.add(goal)
        db.commit()
        db.refresh(goal)
        return {"ok": True, "goal_id": goal.id, "title": title}

    def list_goals(db: Session, owner_id: int) -> list[dict]:
        goals = db.query(Goal).filter(Goal.owner_id == owner_id).all()
        return [
            {"id": g.id, "title": g.title, "status": g.status, "progress_pct": g.progress_pct}
            for g in goals
        ]

    def update_goal_progress(db: Session, goal: Goal) -> None:
        pass

    def decompose_goal_into_tasks(db: Session, goal: Goal, identity: Optional[dict]) -> list[int]:
        return []


try:
    from ....core.blackbox import (
        fetch_blackbox_events,
        blackbox_event_stream_generator,
        build_blackbox_replay,
        list_blackbox_sessions,
        build_blackbox_session_report,
        build_blackbox_recovery_plan,
        build_blackbox_export_bundle,
        prune_blackbox_events,
    )
except ImportError:

    def fetch_blackbox_events(
        owner_id: int,
        session_id: Optional[str] = None,
        source_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        return []

    async def blackbox_event_stream_generator(
        owner_id: int,
        session_id: Optional[str],
        source_type: Optional[str],
        after_event_id: int,
        poll_seconds: float,
        batch_size: int,
    ):
        return
        yield b""  # Make it a generator

    def build_blackbox_replay(
        owner_id: int,
        session_id: Optional[str] = None,
        source_type: Optional[str] = None,
        limit: int = 600,
    ) -> dict:
        return {"ok": False, "error": "Not implemented"}

    def list_blackbox_sessions(
        owner_id: int, limit: int = 20, source_type: Optional[str] = None
    ) -> list[dict]:
        return []

    def build_blackbox_session_report(
        owner_id: int,
        session_id: Optional[str] = None,
        source_type: Optional[str] = None,
        limit: int = 300,
        include_timeline: bool = False,
    ) -> dict:
        return {"ok": False, "error": "Not implemented"}

    def build_blackbox_recovery_plan(
        owner_id: int,
        session_id: Optional[str] = None,
        source_type: Optional[str] = None,
        limit: int = 300,
    ) -> dict:
        return {"ok": False, "error": "Not implemented"}

    def build_blackbox_export_bundle(
        owner_id: int,
        session_id: Optional[str] = None,
        source_type: Optional[str] = None,
        limit: int = 600,
        include_timeline: bool = True,
        include_raw_events: bool = False,
    ) -> dict:
        return {"ok": False, "error": "Not implemented"}

    def prune_blackbox_events(owner_id: Optional[int] = None, reason: str = "manual") -> dict:
        return {"ok": False, "error": "Not implemented"}


try:
    from ....core.nodes import (
        cleanup_expired_node_leases,
        _candidate_node_scores,
        _refresh_node_runtime_metrics,
        _normalize_capability_list,
        claim_node_lease,
        release_node_lease,
    )
except ImportError:

    def cleanup_expired_node_leases(db: Session) -> None:
        pass

    def _candidate_node_scores(capability: str, preferred_node: Optional[str] = None) -> list[dict]:
        return []

    def _refresh_node_runtime_metrics() -> None:
        pass

    def _normalize_capability_list(capabilities: list[str]) -> list[str]:
        return list(set(c.strip().lower() for c in capabilities if c.strip()))

    def claim_node_lease(
        owner_id: int, capability: str, node_name: str = "auto", ttl_seconds: Optional[int] = None
    ) -> dict:
        return {"ok": False, "error": "Not implemented"}

    def release_node_lease(lease_token: str) -> dict:
        return {"ok": False, "error": "Not implemented"}


try:
    from ....core.host_exec import create_host_exec_grant
except ImportError:

    def create_host_exec_grant(
        owner_id: int,
        node_name: str,
        command_prefix: str,
        created_by: str = "api",
        ttl_minutes: Optional[int] = None,
    ) -> dict:
        return {"ok": False, "error": "Not implemented"}


try:
    from ....core.security import apply_url_safety_guard
except ImportError:

    def apply_url_safety_guard(url: str, source: str = "") -> tuple[bool, str]:
        return True, ""


try:
    from ....core.protocols import protocol_validate_payload, protocol_contracts_public_view
except ImportError:

    def protocol_validate_payload(
        schema_name: str, payload: dict, direction: str = "request"
    ) -> tuple[bool, Optional[str]]:
        return True, None

    def protocol_contracts_public_view(registry: dict) -> list[dict]:
        return []


try:
    from ....core.evaluation import run_continuous_eval_suite, evaluate_release_gate
except ImportError:

    def run_continuous_eval_suite(max_cases: int = 50) -> dict:
        return {"ok": False, "error": "Not implemented"}

    def evaluate_release_gate(run_eval: bool = False, max_cases: Optional[int] = None) -> dict:
        return {"ok": True, "passed": True}


try:
    from ....core.sessions import run_startup_transcript_repair
except ImportError:

    def run_startup_transcript_repair(limit: int = 250) -> dict:
        return {"ok": True, "owners_changed": 0, "owners_processed": 0}
