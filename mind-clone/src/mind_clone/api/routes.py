# SECTION 11: FASTAPI APPLICATION
# ============================================================================

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import subprocess
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse boolean environment variable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


# Config imports - settings is a singleton instance of Settings class
from ..config import settings

# Access config values through settings instance
TELEGRAM_BOT_TOKEN = settings.telegram_bot_token
TOKEN_PLACEHOLDER = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
KIMI_MODEL = settings.kimi_model
KIMI_FALLBACK_MODEL = settings.kimi_fallback_model
OPS_AUTH_ENABLED = False  # Default, may be overridden
OPS_AUTH_TOKEN = os.getenv("OPS_AUTH_TOKEN", "")
OPS_AUTH_REQUIRE_SIGNATURE = _env_flag("OPS_AUTH_REQUIRE_SIGNATURE", False)
OPS_AUTH_ROLE_SECRETS = {}  # Default empty
OPS_AUTH_ALLOWED_ROLES = set()
OPS_AUTH_SIGNATURE_SKEW_SECONDS = 300
BLACKBOX_ENABLED = settings.blackbox_enabled
NODE_CONTROL_PLANE_ENABLED = settings.node_control_plane_enabled
HEARTBEAT_AUTONOMY_ENABLED = _env_flag("HEARTBEAT_AUTONOMY_ENABLED", False)
CRON_ENABLED = settings.cron_enabled
TEAM_MODE_ENABLED = settings.team_mode_enabled
TEAM_AGENT_DEFAULT_KEY = settings.team_agent_default_key
TEAM_BROADCAST_ENABLED = settings.team_broadcast_enabled
IDENTITY_SCOPE_MODE = settings.identity_scope_mode
WORKFLOW_V2_ENABLED = settings.workflow_v2_enabled
WORKFLOW_LOOP_MAX_ITERATIONS = settings.workflow_loop_max_iterations
WORKFLOW_MAX_STEPS = 100
EVAL_MAX_CASES = int(os.getenv("EVAL_MAX_CASES", "50"))
EVENT_STREAM_POLL_SECONDS = float(os.getenv("EVENT_STREAM_POLL_SECONDS", "0.5"))
EVENT_STREAM_BATCH_SIZE = int(os.getenv("EVENT_STREAM_BATCH_SIZE", "100"))
MEMORY_VAULT_ROOT = Path(
    os.getenv("MEMORY_VAULT_ROOT", str(settings.app_dir / "persist" / "memory_vault"))
)
UI_DIST_DIR = settings.ui_dist_dir
NODE_AUTO_CAPABILITY_DEFAULT = os.getenv("NODE_AUTO_CAPABILITY_DEFAULT", "general")
NODE_SCHEDULER_LEASE_PENALTY = float(os.getenv("NODE_SCHEDULER_LEASE_PENALTY", "10.0"))
NODE_SCHEDULER_FAILURE_PENALTY = float(os.getenv("NODE_SCHEDULER_FAILURE_PENALTY", "50.0"))
NODE_SCHEDULER_LATENCY_PENALTY = float(os.getenv("NODE_SCHEDULER_LATENCY_PENALTY", "5.0"))
NODE_SCHEDULER_RECOVERY_BONUS = float(os.getenv("NODE_SCHEDULER_RECOVERY_BONUS", "20.0"))
NODE_SCHEDULER_FAILURE_WINDOW_SECONDS = int(
    os.getenv("NODE_SCHEDULER_FAILURE_WINDOW_SECONDS", "300")
)
TASK_CHECKPOINT_REPLAY_STRICT = _env_flag("TASK_CHECKPOINT_REPLAY_STRICT", True)
TASK_STATUS_QUEUED = "queued"

# Database imports
from ..database.session import get_db, init_db, SessionLocal
from ..database.models import (
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

# Core state imports
from ..core.state import (
    RUNTIME_STATE,
    get_runtime_state,
    get_runtime_metrics,
    RUNTIME_STATE_LOCK,
)

# Global background task handles (module level)
TASK_WORKER_TASK: Optional[asyncio.Task] = None
WEBHOOK_RETRY_TASK: Optional[asyncio.Task] = None
WEBHOOK_SUPERVISOR_TASK: Optional[asyncio.Task] = None
SPINE_SUPERVISOR_TASK: Optional[asyncio.Task] = None
COMMAND_QUEUE_WORKER_TASK: Optional[asyncio.Task] = None
CRON_SUPERVISOR_TASK: Optional[asyncio.Task] = None
HEARTBEAT_SUPERVISOR_TASK: Optional[asyncio.Task] = None
HEARTBEAT_WAKE_EVENT: Optional[asyncio.Event] = None

# Global locks and state mirrors (for compatibility)
OWNER_STATE_LOCK = RUNTIME_STATE_LOCK
OWNER_QUEUE_COUNTS: Dict[int, int] = {}
OWNER_ACTIVE_RUNS: Dict[int, int] = {}
COMMAND_QUEUE_WORKER_TASKS: List[asyncio.Task] = []
NODE_CONTROL_LOCK = RUNTIME_STATE_LOCK
NODE_HEARTBEAT_MAP: Dict[str, Dict] = {}
PROTOCOL_SCHEMA_LOCK = RUNTIME_STATE_LOCK
PROTOCOL_SCHEMA_REGISTRY: Dict[str, Any] = {}
CANARY_STATE: Dict[str, Any] = {}
CANARY_ROUTER_ENABLED = _env_flag("CANARY_ROUTER_ENABLED", False)


def runtime_metrics() -> Dict[str, Any]:
    """Get runtime metrics (wrapper for get_runtime_metrics)."""
    return get_runtime_metrics()


def runtime_uptime_seconds() -> float:
    """Get runtime uptime in seconds."""
    start = RUNTIME_STATE.get("app_start_monotonic")
    if start is None:
        return 0.0
    return time.monotonic() - float(start)


# Service imports - stubs for functions that may have circular import issues
try:
    from ..services.telegram import (
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
        """Fallback dispatcher — runs agent loop directly when telegram service unavailable."""
        import asyncio
        try:
            from ..agent.loop import run_agent_loop
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
    from ..services.task_engine import (
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
    from ..services.scheduler import (
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
    from ..tools.basic import tool_list_execution_nodes, tool_list_plugin_tools
except ImportError:

    def tool_list_execution_nodes() -> dict:
        return {"nodes": []}

    def tool_list_plugin_tools() -> dict:
        return {"tools": []}


try:
    from ..tools.registry import (
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
from ..utils import truncate_text, clamp_int, utc_now_iso, _safe_json_dict, _safe_json_list

# Agent/identity imports
try:
    from ..agent.identity import (
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
        from ..database.session import SessionLocal
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
    from ..agent.memory import (
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
    from ..core.queue import (
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
    from ..core.approvals import (
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
    from ..core.goals import (
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
    from ..core.blackbox import (
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
    from ..core.nodes import (
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
    from ..core.host_exec import create_host_exec_grant
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
    from ..core.protocols import protocol_validate_payload, protocol_contracts_public_view
except ImportError:

    def protocol_validate_payload(
        schema_name: str, payload: dict, direction: str = "request"
    ) -> tuple[bool, Optional[str]]:
        return True, None

    def protocol_contracts_public_view(registry: dict) -> list[dict]:
        return []


try:
    from ..core.evaluation import run_continuous_eval_suite, evaluate_release_gate
except ImportError:

    def run_continuous_eval_suite(max_cases: int = 50) -> dict:
        return {"ok": False, "error": "Not implemented"}

    def evaluate_release_gate(run_eval: bool = False, max_cases: Optional[int] = None) -> dict:
        return {"ok": True, "passed": True}


try:
    from ..core.session import run_startup_transcript_repair
except ImportError:

    def run_startup_transcript_repair(limit: int = 250) -> dict:
        return {"ok": True, "owners_changed": 0, "owners_processed": 0}


logger = logging.getLogger("mind_clone.api")
log = logger  # alias used by monolith-ported lifespan code
router = APIRouter()


# Stub fallbacks for functions that come from telegram.py but are used in lifespan
try:
    spine_supervisor_loop  # type: ignore[name-defined]
except NameError:
    async def spine_supervisor_loop() -> None:
        """No-op spine supervisor when telegram module unavailable."""
        import asyncio as _aio
        while True:
            await _aio.sleep(60)

try:
    heartbeat_supervisor_loop  # type: ignore[name-defined]
except NameError:
    async def heartbeat_supervisor_loop() -> None:
        """No-op heartbeat supervisor when telegram module unavailable."""
        import asyncio as _aio
        while True:
            await _aio.sleep(60)

try:
    cancel_background_task  # type: ignore[name-defined]
except NameError:
    async def cancel_background_task(task, name: str = "") -> None:
        """Cancel an asyncio background task safely."""
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    global \
        TASK_WORKER_TASK, \
        WEBHOOK_RETRY_TASK, \
        WEBHOOK_SUPERVISOR_TASK, \
        SPINE_SUPERVISOR_TASK, \
        COMMAND_QUEUE_WORKER_TASK, \
        CRON_SUPERVISOR_TASK, \
        HEARTBEAT_SUPERVISOR_TASK, \
        HEARTBEAT_WAKE_EVENT

    initialize_runtime_state_baseline()
    _preflight_ok, preflight_errors = run_startup_preflight()
    critical_preflight_errors = [
        err
        for err in preflight_errors
        if "OS_SANDBOX_REQUIRED" in str(err) or "OS sandbox is required" in str(err)
    ]
    if critical_preflight_errors:
        raise RuntimeError(
            "Critical startup preflight failure: " + "; ".join(critical_preflight_errors)
        )
    if HEARTBEAT_WAKE_EVENT is None:
        HEARTBEAT_WAKE_EVENT = asyncio.Event()

    init_db()
    repair_boot = await asyncio.to_thread(run_startup_transcript_repair, 250)
    if isinstance(repair_boot, dict):
        if repair_boot.get("ok"):
            if int(repair_boot.get("owners_changed", 0)) > 0:
                log.info(
                    "SESSION_TRANSCRIPT_STARTUP_REPAIR owners_processed=%d owners_changed=%d",
                    int(repair_boot.get("owners_processed", 0)),
                    int(repair_boot.get("owners_changed", 0)),
                )
        else:
            log.warning("SESSION_TRANSCRIPT_STARTUP_REPAIR_FAIL error=%s", repair_boot.get("error"))
    load_remote_node_registry()
    load_plugin_tools_registry()
    load_custom_tools_from_db()
    _refresh_approval_pending_runtime_count()
    try:
        db_boot = SessionLocal()
        try:
            RUNTIME_STATE["team_agents_total"] = int(db_boot.query(TeamAgent).count())
            RUNTIME_STATE["workflow_programs_total"] = int(db_boot.query(WorkflowProgram).count())
            RUNTIME_STATE["ops_audit_events_total"] = int(db_boot.query(OpsAuditEvent).count())
            last_audit = db_boot.query(OpsAuditEvent).order_by(OpsAuditEvent.id.desc()).first()
            if last_audit is not None:
                RUNTIME_STATE["ops_audit_last_hash"] = str(last_audit.event_hash or "")
            usage_rows = db_boot.query(UsageLedger).all()
            RUNTIME_STATE["usage_ledger_events"] = int(len(usage_rows))
            usage_cost = 0.0
            for row in usage_rows:
                try:
                    usage_cost += float(row.estimated_cost_usd or "0")
                except Exception:
                    continue
            RUNTIME_STATE["usage_ledger_cost_usd"] = round(float(usage_cost), 8)
        finally:
            db_boot.close()
    except Exception:
        pass
    check_db_liveness()
    try:
        evaluate_release_gate(run_eval=False)
    except Exception as e:
        log.warning("RELEASE_GATE_BOOTSTRAP_FAIL error=%s", truncate_text(str(e), 220))
    log.info("Database initialized")

    if TASK_WORKER_TASK is None or TASK_WORKER_TASK.done():
        TASK_WORKER_TASK = asyncio.create_task(task_worker_loop())
        log.info("Task worker started")

    if command_queue_enabled():
        await ensure_command_queue_workers_running()
        log.info(
            "Command queue workers started (mode=%s target=%d alive=%d)",
            COMMAND_QUEUE_MODE,
            COMMAND_QUEUE_WORKER_COUNT,
            active_command_queue_worker_count(),
        )

    recovered = recover_pending_tasks()
    for task_id in recovered:
        enqueue_task(task_id)
    if recovered:
        log.info(f"Recovered {len(recovered)} queued task(s)")

    if TELEGRAM_BOT_TOKEN != TOKEN_PLACEHOLDER:
        ok, _ = await try_set_telegram_webhook_once()
        if not ok and (WEBHOOK_SUPERVISOR_TASK is None or WEBHOOK_SUPERVISOR_TASK.done()):
            WEBHOOK_SUPERVISOR_TASK = asyncio.create_task(webhook_retry_supervisor_loop())
        elif ok:
            log.info("Telegram webhook set")
    else:
        RUNTIME_STATE["webhook_last_error"] = "Telegram bot token not configured."
        log.warning("Telegram bot token not configured")

    if SPINE_SUPERVISOR_TASK is None or SPINE_SUPERVISOR_TASK.done():
        SPINE_SUPERVISOR_TASK = asyncio.create_task(spine_supervisor_loop())

    if HEARTBEAT_AUTONOMY_ENABLED and (
        HEARTBEAT_SUPERVISOR_TASK is None or HEARTBEAT_SUPERVISOR_TASK.done()
    ):
        HEARTBEAT_SUPERVISOR_TASK = asyncio.create_task(heartbeat_supervisor_loop())

    if CRON_ENABLED and (CRON_SUPERVISOR_TASK is None or CRON_SUPERVISOR_TASK.done()):
        CRON_SUPERVISOR_TASK = asyncio.create_task(cron_supervisor_loop())

    try:
        yield
    finally:
        RUNTIME_STATE["shutting_down"] = True

        await cancel_background_task(SPINE_SUPERVISOR_TASK, "spine supervisor")
        SPINE_SUPERVISOR_TASK = None

        await cancel_background_task(HEARTBEAT_SUPERVISOR_TASK, "heartbeat supervisor")
        HEARTBEAT_SUPERVISOR_TASK = None

        await cancel_command_queue_workers()

        await cancel_background_task(CRON_SUPERVISOR_TASK, "cron supervisor")
        CRON_SUPERVISOR_TASK = None

        await cancel_background_task(WEBHOOK_SUPERVISOR_TASK, "webhook supervisor")
        WEBHOOK_SUPERVISOR_TASK = None

        await cancel_background_task(WEBHOOK_RETRY_TASK, "webhook retry")
        WEBHOOK_RETRY_TASK = None

        await cancel_background_task(TASK_WORKER_TASK, "task worker")
        TASK_WORKER_TASK = None

        RUNTIME_STATE["worker_alive"] = False
        RUNTIME_STATE["spine_supervisor_alive"] = False
        RUNTIME_STATE["heartbeat_supervisor_alive"] = False
        RUNTIME_STATE["heartbeat_next_tick_at"] = None
        RUNTIME_STATE["webhook_next_retry_at"] = None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ops_auth_fail(status_code: int, message: str):
    RUNTIME_STATE["ops_auth_failures"] = int(RUNTIME_STATE.get("ops_auth_failures", 0)) + 1
    RUNTIME_STATE["ops_auth_last_error"] = truncate_text(message, 220)
    raise HTTPException(status_code=status_code, detail=message)


def _extract_ops_token(request: Request) -> str:
    auth = str(request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    token = str(request.headers.get("x-ops-token") or "").strip()
    if token:
        return token
    return str(request.query_params.get("ops_token") or "").strip()


def _ops_signature_secret(role: str | None) -> str:
    role_key = str(role or "").strip().lower()
    if role_key:
        specific = str(OPS_AUTH_ROLE_SECRETS.get(role_key) or "").strip()
        if specific:
            return specific
    fallback = str(OPS_AUTH_ROLE_SECRETS.get("default") or "").strip()
    if fallback:
        return fallback
    return OPS_AUTH_TOKEN


def _ops_signature_payload(request: Request, timestamp: int) -> str:
    method = str(request.method or "GET").upper()
    path = str(request.url.path or "")
    query = str(request.url.query or "")
    return f"{method}\n{path}\n{query}\n{int(timestamp)}"


def _verify_ops_signature(request: Request, role: str | None) -> tuple[bool, str]:
    timestamp_raw = str(request.headers.get("x-ops-timestamp") or "").strip()
    signature = str(request.headers.get("x-ops-signature") or "").strip().lower()
    if not timestamp_raw:
        return False, "Missing x-ops-timestamp header."
    if not signature:
        return False, "Missing x-ops-signature header."
    try:
        timestamp = int(timestamp_raw)
    except Exception:
        return False, "Invalid x-ops-timestamp header."
    now_epoch = int(time.time())
    skew = abs(now_epoch - int(timestamp))
    if skew > int(OPS_AUTH_SIGNATURE_SKEW_SECONDS):
        return False, f"Signature timestamp skew too high ({skew}s)."
    secret = _ops_signature_secret(role)
    payload = _ops_signature_payload(request, timestamp)
    expected = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False, "Invalid ops request signature."
    return True, ""


def record_ops_audit_event(
    *,
    actor_role: str | None,
    actor_ref: str | None,
    action: str,
    target: str | None = None,
    status: str = "ok",
    detail: dict | None = None,
):
    try:
        db = SessionLocal()
    except Exception:
        return
    try:
        prev_row = db.query(OpsAuditEvent).order_by(OpsAuditEvent.id.desc()).first()
        prev_hash = str(prev_row.event_hash or "") if prev_row else ""
        detail_obj = _safe_json_dict(detail, {})
        detail_json = json.dumps(detail_obj, ensure_ascii=False, sort_keys=True)
        hash_raw = (
            f"{prev_hash}|{str(actor_role or '')}|{str(actor_ref or '')}|{str(action or '')}|"
            f"{str(target or '')}|{str(status or '')}|{detail_json}|{utc_now_iso()}"
        )
        event_hash = hashlib.sha256(hash_raw.encode("utf-8")).hexdigest()
        row = OpsAuditEvent(
            actor_role=truncate_text(str(actor_role or ""), 40) or None,
            actor_ref=truncate_text(str(actor_ref or ""), 140) or None,
            action=truncate_text(str(action or ""), 120) or "unknown",
            target=truncate_text(str(target or ""), 220) or None,
            status=truncate_text(str(status or "ok"), 20) or "ok",
            detail_json=detail_json,
            prev_hash=prev_hash or None,
            event_hash=event_hash,
        )
        db.add(row)
        db.commit()
        RUNTIME_STATE["ops_audit_events_total"] = (
            int(RUNTIME_STATE.get("ops_audit_events_total", 0)) + 1
        )
        RUNTIME_STATE["ops_audit_last_hash"] = event_hash
    except Exception:
        db.rollback()
    finally:
        db.close()


def require_ops_auth(request: Request):
    if not OPS_AUTH_ENABLED:
        return {"enabled": False, "role": None}
    if not OPS_AUTH_TOKEN:
        _ops_auth_fail(503, "Ops auth enabled but OPS_AUTH_TOKEN is not configured.")

    token = _extract_ops_token(request)
    if not token:
        _ops_auth_fail(401, "Missing ops auth token.")
    if token != OPS_AUTH_TOKEN:
        _ops_auth_fail(403, "Invalid ops auth token.")

    role = str(request.headers.get("x-ops-role") or "").strip().lower()
    if OPS_AUTH_ALLOWED_ROLES and role and role not in OPS_AUTH_ALLOWED_ROLES:
        _ops_auth_fail(403, f"Role '{role}' is not allowed for ops routes.")

    actor_ref = str(request.headers.get("x-ops-actor") or "").strip()
    if not actor_ref:
        actor_ref = str(request.client.host) if request.client else "unknown"

    if OPS_AUTH_REQUIRE_SIGNATURE:
        sig_ok, sig_error = _verify_ops_signature(request, role=role)
        if not sig_ok:
            RUNTIME_STATE["ops_signature_failures"] = (
                int(RUNTIME_STATE.get("ops_signature_failures", 0)) + 1
            )
            record_ops_audit_event(
                actor_role=role or None,
                actor_ref=actor_ref,
                action=f"{str(request.method).upper()} {request.url.path}",
                target=request.url.path,
                status="denied",
                detail={"reason": sig_error, "signature_required": True},
            )
            _ops_auth_fail(403, sig_error)

    record_ops_audit_event(
        actor_role=role or None,
        actor_ref=actor_ref,
        action=f"{str(request.method).upper()} {request.url.path}",
        target=request.url.path,
        status="ok",
        detail={"query": truncate_text(str(request.url.query or ""), 240)},
    )

    return {
        "enabled": True,
        "role": role or None,
        "actor_ref": actor_ref,
    }


def iso_datetime_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    try:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    except Exception:
        try:
            return value.isoformat()
        except Exception:
            return None


def resolve_ui_user_context(
    db: Session,
    chat_id: str,
    username: str | None,
    agent_key: str | None = None,
) -> tuple[User, int, str]:
    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        raise ValueError("chat_id is required.")
    normalized_username = str(username or "").strip()
    if not normalized_username or normalized_username == "api_user":
        normalized_username = f"tg_{normalized_chat_id}"
    root_user = _resolve_identity_owner(db, normalized_chat_id, normalized_username)
    key = normalize_agent_key(agent_key)
    if TEAM_MODE_ENABLED and key != TEAM_AGENT_DEFAULT_KEY:
        user = _ensure_team_agent_owner(db, root_user, key)
    else:
        user = root_user
    return user, int(user.id), normalized_chat_id


def serialize_task_summary(task: Task) -> dict:
    done, total = task_progress(task.plan)
    return {
        "id": int(task.id),
        "title": task.title,
        "status": task.status,
        "created_at": iso_datetime_or_none(task.created_at),
        "progress_done": int(done),
        "progress_total": int(total),
        "current_step": current_task_step(task.plan),
    }


def serialize_pending_approval(row: ApprovalRequest) -> dict:
    return {
        "token": row.token,
        "tool_name": row.tool_name,
        "source_type": row.source_type,
        "source_ref": row.source_ref,
        "step_id": row.step_id,
        "created_at": iso_datetime_or_none(row.created_at),
        "expires_at": iso_datetime_or_none(row.expires_at),
    }


def list_pending_approvals_for_owner(db: Session, owner_id: int, limit: int = 20) -> list[dict]:
    now_dt = datetime.utcnow()
    rows = (
        db.query(ApprovalRequest)
        .filter(
            ApprovalRequest.owner_id == int(owner_id),
            ApprovalRequest.status == "pending",
            ApprovalRequest.expires_at > now_dt,
        )
        .order_by(ApprovalRequest.id.desc())
        .limit(clamp_int(limit, 1, 100, 20))
        .all()
    )
    return [serialize_pending_approval(row) for row in rows]


def resolve_root_ui_user_context(
    db: Session, chat_id: str, username: str | None
) -> tuple[User, int, str]:
    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        raise ValueError("chat_id is required.")
    normalized_username = str(username or "").strip()
    if not normalized_username or normalized_username == "api_user":
        normalized_username = f"tg_{normalized_chat_id}"
    root_owner = _resolve_identity_owner(db, normalized_chat_id, normalized_username)
    return root_owner, int(root_owner.id), normalized_chat_id


def get_team_agent_with_user(
    db: Session, root_owner_id: int, agent_key: str
) -> tuple[TeamAgent | None, User | None]:
    row = _get_team_agent_row(db, root_owner_id, agent_key)
    if not row:
        return None, None
    user = db.query(User).filter(User.id == int(row.agent_owner_id)).first()
    return row, user


def serialize_team_agent(row: TeamAgent, user: User | None = None) -> dict:
    return {
        "agent_key": str(row.agent_key),
        "display_name": str(row.display_name or row.agent_key),
        "status": str(row.status or "active"),
        "owner_id": int(row.owner_id),
        "agent_owner_id": int(row.agent_owner_id),
        "workspace_root": str(row.workspace_root or ""),
        "username": str(user.username) if user else None,
        "chat_id": str(user.telegram_chat_id) if user and user.telegram_chat_id else None,
        "created_at": iso_datetime_or_none(row.created_at),
        "updated_at": iso_datetime_or_none(row.updated_at),
        "last_seen_at": iso_datetime_or_none(row.last_seen_at),
    }


def list_team_agents_for_owner(
    db: Session, root_owner_id: int, include_stopped: bool = True
) -> list[dict]:
    q = db.query(TeamAgent).filter(TeamAgent.owner_id == int(root_owner_id))
    if not include_stopped:
        q = q.filter(TeamAgent.status == "active")
    rows = q.order_by(TeamAgent.id.asc()).all()
    payload: list[dict] = []
    for row in rows:
        user = db.query(User).filter(User.id == int(row.agent_owner_id)).first()
        payload.append(serialize_team_agent(row, user))
    return payload


def resolve_team_agent_owner_for_request(
    db: Session,
    chat_id: str,
    username: str | None,
    agent_key: str | None,
    create_if_missing: bool = False,
    require_active: bool = True,
) -> tuple[User, User, int, str]:
    root_owner, root_owner_id, normalized_chat_id = resolve_root_ui_user_context(
        db, chat_id, username
    )
    key = normalize_agent_key(agent_key)
    if key == TEAM_AGENT_DEFAULT_KEY or not TEAM_MODE_ENABLED:
        return root_owner, root_owner, root_owner_id, normalized_chat_id

    row, user = get_team_agent_with_user(db, root_owner_id, key)
    if row is None or user is None:
        if not create_if_missing:
            raise ValueError(f"Agent '{key}' does not exist. Spawn it first.")
        user = _ensure_team_agent_owner(db, root_owner, key)
        row, _ = get_team_agent_with_user(db, root_owner_id, key)
    if row is None or user is None:
        raise ValueError(f"Failed to resolve agent '{key}'.")
    if require_active and str(row.status or "active") != "active":
        raise ValueError(f"Agent '{key}' is stopped.")
    row.last_seen_at = datetime.utcnow()
    db.commit()
    return root_owner, user, root_owner_id, normalized_chat_id


def _compile_workflow_step(line: str, line_no: int) -> dict | None:
    text = str(line or "").strip()
    if not text or text.startswith("#"):
        return None
    upper = text.upper()
    if upper == "ENDIF":
        return {"kind": "endif"}
    if upper == "ENDLOOP":
        return {"kind": "endloop"}
    if upper.startswith("SET "):
        payload = text[len("SET ") :].strip()
        if "=" not in payload:
            raise ValueError(f"Line {line_no}: SET requires 'name = value'.")
        key, value = payload.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,40}", key):
            raise ValueError(f"Line {line_no}: invalid SET variable name '{key}'.")
        return {"kind": "set", "name": key, "value": truncate_text(value.strip(), 2000)}
    if upper.startswith("IF "):
        condition = truncate_text(text[len("IF ") :].strip(), 320)
        if not condition:
            raise ValueError(f"Line {line_no}: IF requires a condition.")
        return {"kind": "if", "condition": condition}
    if upper.startswith("LOOP "):
        count_raw = text[len("LOOP ") :].strip()
        try:
            count = int(count_raw)
        except Exception:
            raise ValueError(f"Line {line_no}: LOOP requires an integer count.")
        count = clamp_int(count, 1, WORKFLOW_LOOP_MAX_ITERATIONS, 1)
        return {"kind": "loop", "count": int(count)}
    if upper.startswith("SEND "):
        _, payload = text.split(" ", 1)
        if "::" not in payload:
            raise ValueError(f"Line {line_no}: SEND requires 'agent_key :: message'.")
        agent_key, message = payload.split("::", 1)
        return {
            "kind": "send",
            "agent_key": normalize_agent_key(agent_key),
            "message": truncate_text(message.strip(), 4000),
        }
    if upper.startswith("BROADCAST "):
        payload = text[len("BROADCAST ") :]
        if "::" in payload:
            _, message = payload.split("::", 1)
            payload = message
        return {"kind": "broadcast", "message": truncate_text(payload.strip(), 4000)}
    if upper.startswith("SLEEP "):
        seconds_raw = text[len("SLEEP ") :].strip()
        try:
            seconds = float(seconds_raw)
        except Exception:
            raise ValueError(f"Line {line_no}: invalid SLEEP seconds.")
        return {"kind": "sleep", "seconds": max(0.0, min(120.0, seconds))}
    if upper.startswith("TASK "):
        _, payload = text.split(" ", 1)
        parts = payload.split("::")
        if len(parts) < 3:
            raise ValueError(f"Line {line_no}: TASK requires 'agent_key :: title :: goal'.")
        agent_key = normalize_agent_key(parts[0].strip())
        title = truncate_text(parts[1].strip(), 140)
        goal = truncate_text("::".join(parts[2:]).strip(), 6000)
        if not title or not goal:
            raise ValueError(f"Line {line_no}: TASK title/goal cannot be empty.")
        return {"kind": "task", "agent_key": agent_key, "title": title, "goal": goal}
    raise ValueError(f"Line {line_no}: unknown workflow command.")


def _count_workflow_actions(steps: list[dict]) -> int:
    total = 0
    for step in steps:
        kind = str(step.get("kind") or "").strip().lower()
        if kind in {"if", "loop"}:
            nested = _count_workflow_actions(_safe_json_list(step.get("steps"), []))
            if kind == "loop":
                total += int(step.get("count", 1)) * nested
            else:
                total += nested
            continue
        total += 1
    return int(total)


def parse_workflow_program_text(body_text: str) -> list[dict]:
    lines = str(body_text or "").splitlines()
    root_steps: list[dict] = []
    stack: list[dict] = [{"kind": "root", "line_no": 0, "steps": root_steps}]
    for idx, line in enumerate(lines, 1):
        step = _compile_workflow_step(line, idx)
        if step is not None:
            kind = str(step.get("kind") or "").strip().lower()
            if kind in {"if", "loop"}:
                node = dict(step)
                node["steps"] = []
                stack[-1]["steps"].append(node)
                stack.append({"kind": kind, "line_no": idx, "steps": node["steps"]})
                continue
            if kind == "endif":
                if len(stack) <= 1 or stack[-1]["kind"] != "if":
                    raise ValueError(f"Line {idx}: ENDIF without matching IF.")
                stack.pop()
                continue
            if kind == "endloop":
                if len(stack) <= 1 or stack[-1]["kind"] != "loop":
                    raise ValueError(f"Line {idx}: ENDLOOP without matching LOOP.")
                stack.pop()
                continue
            stack[-1]["steps"].append(step)
    if len(stack) != 1:
        dangling = stack[-1]
        raise ValueError(
            f"Unclosed {dangling['kind'].upper()} block starting at line {dangling['line_no']}."
        )
    if not root_steps:
        raise ValueError("Workflow has no executable steps.")
    total_actions = _count_workflow_actions(root_steps)
    if total_actions > WORKFLOW_MAX_STEPS:
        raise ValueError(f"Workflow exceeds max steps ({WORKFLOW_MAX_STEPS}).")
    return root_steps


def _workflow_render_template(text: str, variables: dict[str, str]) -> str:
    raw = str(text or "")
    if "{{" not in raw:
        return raw

    def _replace(match: re.Match) -> str:
        key = str(match.group(1) or "").strip()
        if not key:
            return ""
        return str(variables.get(key, ""))

    return re.sub(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", _replace, raw)


def _workflow_eval_condition(condition: str, variables: dict[str, str]) -> bool:
    expr = str(condition or "").strip()
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(==|!=)\s*(.+)$", expr)
    if not match:
        raise ValueError("Condition must be in format: <var> == <value> or <var> != <value>.")
    var_name = match.group(1)
    op = match.group(2)
    right = str(match.group(3) or "").strip()
    if (right.startswith("'") and right.endswith("'")) or (
        right.startswith('"') and right.endswith('"')
    ):
        right = right[1:-1]
    left_val = str(variables.get(var_name, ""))
    right_val = _workflow_render_template(right, variables)
    if op == "==":
        return left_val == right_val
    return left_val != right_val


def _vault_owner_dir(owner_id: int) -> Path:
    path = (MEMORY_VAULT_ROOT / f"owner_{int(owner_id)}").resolve(strict=False)
    return path


def _vault_git_run(vault_dir: Path, args: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(vault_dir),
            capture_output=True,
            text=True,
            timeout=45,
        )
        if result.returncode != 0:
            return False, truncate_text(result.stderr or result.stdout or "git failed", 500)
        return True, truncate_text(result.stdout or "ok", 500)
    except Exception as e:
        return False, truncate_text(str(e), 500)


def memory_vault_bootstrap(owner_id: int) -> dict:
    vault_dir = _vault_owner_dir(owner_id)
    vault_dir.mkdir(parents=True, exist_ok=True)
    readme = vault_dir / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Bob Memory Vault\n\nPrivate backup repository for agent memory snapshots.\n",
            encoding="utf-8",
        )
    if not (vault_dir / ".git").exists():
        ok, out = _vault_git_run(vault_dir, ["init"])
        if not ok:
            return {"ok": False, "error": f"git init failed: {out}", "path": str(vault_dir)}
    _vault_git_run(vault_dir, ["config", "user.name", "bob-vault"])
    _vault_git_run(vault_dir, ["config", "user.email", "bob-vault@local"])
    RUNTIME_STATE["memory_vault_bootstraps"] = (
        int(RUNTIME_STATE.get("memory_vault_bootstraps", 0)) + 1
    )
    return {"ok": True, "path": str(vault_dir)}


def _build_memory_export_payload(db: Session, owner_id: int) -> dict:
    notes = (
        db.query(ResearchNote)
        .filter(ResearchNote.owner_id == int(owner_id))
        .order_by(ResearchNote.id.asc())
        .all()
    )
    summaries = (
        db.query(ConversationSummary)
        .filter(ConversationSummary.owner_id == int(owner_id))
        .order_by(ConversationSummary.id.asc())
        .all()
    )
    lessons = (
        db.query(MemoryVector)
        .filter(
            MemoryVector.owner_id == int(owner_id),
            MemoryVector.memory_type == "lesson",
        )
        .order_by(MemoryVector.id.asc())
        .all()
    )
    return {
        "exported_at": utc_now_iso(),
        "owner_id": int(owner_id),
        "research_notes": [
            {
                "topic": row.topic,
                "summary": row.summary,
                "sources": _safe_json_list(row.sources_json, []),
                "tags": _safe_json_list(row.tags_json, []),
            }
            for row in notes
        ],
        "conversation_summaries": [
            {
                "start_message_id": int(row.start_message_id),
                "end_message_id": int(row.end_message_id),
                "summary": row.summary,
                "key_points": _safe_json_list(row.key_points_json, []),
                "open_loops": _safe_json_list(row.open_loops_json, []),
            }
            for row in summaries
        ],
        "lessons": [{"lesson": str(row.text_preview or ""), "context": ""} for row in lessons],
    }


def memory_vault_backup(owner_id: int, message: str = "vault backup") -> dict:
    init = memory_vault_bootstrap(owner_id)
    if not init.get("ok"):
        return init
    vault_dir = Path(init["path"]).resolve(strict=False)
    db = SessionLocal()
    try:
        payload = _build_memory_export_payload(db, owner_id)
    finally:
        db.close()
    export_path = vault_dir / "memory_export.json"
    export_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _vault_git_run(vault_dir, ["add", "memory_export.json"])
    commit_msg = truncate_text(str(message or "vault backup"), 120)
    ok, out = _vault_git_run(vault_dir, ["commit", "-m", commit_msg, "--allow-empty"])
    if not ok:
        return {"ok": False, "error": out}
    RUNTIME_STATE["memory_vault_backups"] = int(RUNTIME_STATE.get("memory_vault_backups", 0)) + 1
    return {"ok": True, "path": str(export_path), "commit": out}


def memory_vault_restore(owner_id: int, ref: str = "HEAD") -> dict:
    vault_dir = _vault_owner_dir(owner_id)
    if not (vault_dir / ".git").exists():
        return {"ok": False, "error": "Vault is not initialized."}
    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:memory_export.json"],
            cwd=str(vault_dir),
            capture_output=True,
            text=True,
            timeout=45,
        )
        if result.returncode != 0:
            return {"ok": False, "error": truncate_text(result.stderr or "git show failed", 500)}
        payload = json.loads(result.stdout or "{}")
    except Exception as e:
        return {"ok": False, "error": truncate_text(str(e), 500)}

    db = SessionLocal()
    restored = {"research_notes": 0, "conversation_summaries": 0, "lessons": 0}
    try:
        for item in payload.get("research_notes", []):
            if not isinstance(item, dict):
                continue
            topic = truncate_text(str(item.get("topic") or "").strip(), 200)
            summary = truncate_text(str(item.get("summary") or "").strip(), 6000)
            if not topic or not summary:
                continue
            row = ResearchNote(
                owner_id=int(owner_id),
                topic=topic,
                summary=summary,
                sources_json=json.dumps(
                    _safe_json_list(item.get("sources"), []), ensure_ascii=False
                ),
                tags_json=json.dumps(_safe_json_list(item.get("tags"), []), ensure_ascii=False),
            )
            db.add(row)
            restored["research_notes"] += 1
        for item in payload.get("conversation_summaries", []):
            if not isinstance(item, dict):
                continue
            summary = truncate_text(str(item.get("summary") or "").strip(), 8000)
            if not summary:
                continue
            row = ConversationSummary(
                owner_id=int(owner_id),
                start_message_id=int(item.get("start_message_id") or 0),
                end_message_id=int(item.get("end_message_id") or 0),
                summary=summary,
                key_points_json=json.dumps(
                    _safe_json_list(item.get("key_points"), []), ensure_ascii=False
                ),
                open_loops_json=json.dumps(
                    _safe_json_list(item.get("open_loops"), []), ensure_ascii=False
                ),
            )
            db.add(row)
            restored["conversation_summaries"] += 1
        for item in payload.get("lessons", []):
            if not isinstance(item, dict):
                continue
            lesson = truncate_text(str(item.get("lesson") or "").strip(), 800)
            if not lesson:
                continue
            context_text = truncate_text(str(item.get("context") or ""), 1200)
            if store_lesson(db, int(owner_id), lesson, context_text):
                restored["lessons"] += 1
        db.commit()
    except Exception as e:
        db.rollback()
        return {"ok": False, "error": truncate_text(str(e), 500)}
    finally:
        db.close()

    RUNTIME_STATE["memory_vault_restores"] = int(RUNTIME_STATE.get("memory_vault_restores", 0)) + 1
    return {"ok": True, "restored": restored, "ref": ref}


def ui_dist_ready() -> tuple[Path, Path, bool]:
    dist_dir = UI_DIST_DIR.resolve(strict=False)
    index_file = (dist_dir / "index.html").resolve(strict=False)
    ready = dist_dir.exists() and dist_dir.is_dir() and index_file.exists() and index_file.is_file()
    return dist_dir, index_file, ready


def ui_not_built_response() -> JSONResponse:
    dist_dir, _, _ = ui_dist_ready()
    return JSONResponse(
        status_code=503,
        content={
            "ok": False,
            "error": "UI bundle not found. Build UI first in mind-clone-ui using npm install && npm run build.",
            "ui_dist_dir": str(dist_dir),
        },
    )


def resolve_ui_asset_path(path: str) -> Path | None:
    dist_dir, index_file, ready = ui_dist_ready()
    if not ready:
        return None

    raw_path = str(path or "").strip().lstrip("/")
    if not raw_path:
        return index_file

    candidate = (dist_dir / raw_path).resolve(strict=False)
    try:
        candidate.relative_to(dist_dir)
    except Exception:
        return index_file

    if candidate.exists() and candidate.is_file():
        return candidate

    if "." in raw_path:
        return None
    return index_file


# --- Heartbeat ---
@router.get("/heartbeat")
def heartbeat():
    payload = {
        "status": "alive",
        "agent": "Mind Clone",
        "model": KIMI_MODEL,
        **runtime_metrics(),
        "timestamp": utc_now_iso(),
    }
    protocol_validate_payload("runtime.metrics.response", payload, direction="response")
    return payload


@router.get("/status/runtime")
def status_runtime():
    payload = runtime_metrics()
    payload["uptime_seconds"] = runtime_uptime_seconds()
    payload["timestamp"] = utc_now_iso()
    protocol_validate_payload("runtime.metrics.response", payload, direction="response")
    return payload


@router.post("/heartbeat/wake")
def heartbeat_wake(_ops=Depends(require_ops_auth)):
    if HEARTBEAT_WAKE_EVENT is not None:
        HEARTBEAT_WAKE_EVENT.set()
    return {
        "ok": True,
        "wakeup_requested": True,
        "next_tick_at": RUNTIME_STATE.get("heartbeat_next_tick_at"),
        "timestamp": utc_now_iso(),
    }


@router.get("/debug/blackbox")
def debug_blackbox_events(
    owner_id: int,
    limit: int = 100,
    session_id: str | None = None,
    source_type: str | None = None,
    _ops=Depends(require_ops_auth),
):
    if owner_id <= 0:
        return {"ok": False, "error": "owner_id must be > 0"}
    if not BLACKBOX_ENABLED:
        return {"ok": False, "error": "blackbox disabled", "enabled": False}

    events = fetch_blackbox_events(
        owner_id=owner_id,
        session_id=session_id,
        source_type=source_type,
        limit=limit,
    )
    return {
        "ok": True,
        "enabled": True,
        "owner_id": owner_id,
        "session_id": session_id,
        "source_type": source_type,
        "count": len(events),
        "events": events,
        "timestamp": utc_now_iso(),
    }


@router.get("/debug/blackbox/stream")
async def debug_blackbox_stream(
    owner_id: int,
    session_id: str | None = None,
    source_type: str | None = None,
    after_event_id: int = 0,
    poll_seconds: float = EVENT_STREAM_POLL_SECONDS,
    _ops=Depends(require_ops_auth),
):
    if owner_id <= 0:
        raise HTTPException(status_code=400, detail="owner_id must be > 0")
    if not BLACKBOX_ENABLED:
        raise HTTPException(status_code=400, detail="blackbox disabled")

    stream = blackbox_event_stream_generator(
        owner_id=owner_id,
        session_id=session_id,
        source_type=source_type,
        after_event_id=after_event_id,
        poll_seconds=poll_seconds,
        batch_size=EVENT_STREAM_BATCH_SIZE,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/debug/blackbox/replay")
def debug_blackbox_replay(
    owner_id: int,
    session_id: str | None = None,
    source_type: str | None = None,
    limit: int = 600,
    _ops=Depends(require_ops_auth),
):
    if owner_id <= 0:
        return {"ok": False, "error": "owner_id must be > 0"}
    if not BLACKBOX_ENABLED:
        return {"ok": False, "error": "blackbox disabled", "enabled": False}
    replay = build_blackbox_replay(
        owner_id=owner_id,
        session_id=session_id,
        source_type=source_type,
        limit=limit,
    )
    if not replay.get("ok"):
        return replay
    return {**replay, "enabled": True, "timestamp": utc_now_iso()}


@router.get("/debug/blackbox/sessions")
def debug_blackbox_sessions(
    owner_id: int,
    limit: int = 20,
    source_type: str | None = None,
    _ops=Depends(require_ops_auth),
):
    if owner_id <= 0:
        return {"ok": False, "error": "owner_id must be > 0"}
    if not BLACKBOX_ENABLED:
        return {"ok": False, "error": "blackbox disabled", "enabled": False}

    sessions = list_blackbox_sessions(
        owner_id=owner_id,
        limit=limit,
        source_type=source_type,
    )
    return {
        "ok": True,
        "enabled": True,
        "owner_id": owner_id,
        "source_type": source_type,
        "count": len(sessions),
        "sessions": sessions,
        "timestamp": utc_now_iso(),
    }


@router.get("/debug/blackbox/session_report")
def debug_blackbox_session_report(
    owner_id: int,
    session_id: str | None = None,
    source_type: str | None = None,
    limit: int = 300,
    include_timeline: bool = False,
    _ops=Depends(require_ops_auth),
):
    if owner_id <= 0:
        return {"ok": False, "error": "owner_id must be > 0"}
    if not BLACKBOX_ENABLED:
        return {"ok": False, "error": "blackbox disabled", "enabled": False}

    report = build_blackbox_session_report(
        owner_id=owner_id,
        session_id=session_id,
        source_type=source_type,
        limit=limit,
        include_timeline=bool(include_timeline),
    )
    if not report.get("ok"):
        return report

    return {
        **report,
        "enabled": True,
        "timestamp": utc_now_iso(),
    }


@router.get("/debug/blackbox/recovery_plan")
def debug_blackbox_recovery_plan(
    owner_id: int,
    session_id: str | None = None,
    source_type: str | None = None,
    limit: int = 300,
    _ops=Depends(require_ops_auth),
):
    if owner_id <= 0:
        return {"ok": False, "error": "owner_id must be > 0"}
    if not BLACKBOX_ENABLED:
        return {"ok": False, "error": "blackbox disabled", "enabled": False}

    plan = build_blackbox_recovery_plan(
        owner_id=owner_id,
        session_id=session_id,
        source_type=source_type,
        limit=limit,
    )
    if not plan.get("ok"):
        return plan

    return {
        **plan,
        "enabled": True,
        "timestamp": utc_now_iso(),
    }


@router.get("/debug/blackbox/export_bundle")
def debug_blackbox_export_bundle(
    owner_id: int,
    session_id: str | None = None,
    source_type: str | None = None,
    limit: int = 600,
    include_timeline: bool = True,
    include_raw_events: bool = False,
    _ops=Depends(require_ops_auth),
):
    if owner_id <= 0:
        return {"ok": False, "error": "owner_id must be > 0"}
    if not BLACKBOX_ENABLED:
        return {"ok": False, "error": "blackbox disabled", "enabled": False}

    bundle = build_blackbox_export_bundle(
        owner_id=owner_id,
        session_id=session_id,
        source_type=source_type,
        limit=limit,
        include_timeline=bool(include_timeline),
        include_raw_events=bool(include_raw_events),
    )
    if not bundle.get("ok"):
        return bundle
    bundle["timestamp"] = utc_now_iso()
    return bundle


@router.post("/debug/blackbox/prune")
def debug_blackbox_prune(
    owner_id: int | None = None,
    reason: str = "manual_api",
    _ops=Depends(require_ops_auth),
):
    if not BLACKBOX_ENABLED:
        return {"ok": False, "error": "blackbox disabled", "enabled": False}
    if owner_id is not None and int(owner_id) <= 0:
        return {"ok": False, "error": "owner_id must be > 0 when provided"}

    return prune_blackbox_events(owner_id=owner_id, reason=reason)


@router.get("/nodes")
def list_nodes_endpoint(_ops=Depends(require_ops_auth)):
    return tool_list_execution_nodes()


class NodeRegisterRequest(BaseModel):
    node_name: str
    base_url: str
    auth_token: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    enabled: bool = True


class NodeHeartbeatRequest(BaseModel):
    node_name: str
    healthy: bool = True
    last_error: str | None = None


class NodeLeaseClaimRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str | None = None
    capability: str = "general"
    node_name: str | None = None
    ttl_seconds: int | None = None


class NodeLeaseReleaseRequest(BaseModel):
    lease_token: str


@router.post("/nodes/register")
def node_register_endpoint(req: NodeRegisterRequest, _ops=Depends(require_ops_auth)):
    if not NODE_CONTROL_PLANE_ENABLED:
        return {"ok": False, "error": "Node control-plane is disabled."}
    name = str(req.node_name or "").strip().lower()
    base_url = str(req.base_url or "").strip().rstrip("/")
    if not name or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,40}", name):
        return {"ok": False, "error": "Invalid node_name."}
    if not re.match(r"^https?://", base_url, re.IGNORECASE):
        return {"ok": False, "error": "base_url must start with http:// or https://"}
    safe_ok, safe_reason = apply_url_safety_guard(base_url, source=f"node_register:{name}")
    if not safe_ok:
        return {"ok": False, "error": safe_reason}
    capabilities = _normalize_capability_list(req.capabilities)
    db = SessionLocal()
    try:
        row = db.query(NodeRegistration).filter(NodeRegistration.node_name == name).first()
        if row is None:
            row = NodeRegistration(node_name=name, base_url=base_url)
            db.add(row)
        row.base_url = base_url
        row.auth_token = truncate_text(str(req.auth_token or "").strip(), 240) or None
        row.capabilities_json = json.dumps(capabilities, ensure_ascii=False)
        row.enabled = 1 if bool(req.enabled) else 0
        row.last_error = None
        db.commit()
    except Exception as e:
        db.rollback()
        return {"ok": False, "error": truncate_text(str(e), 260)}
    finally:
        db.close()
    load_remote_node_registry()
    return {
        "ok": True,
        "node_name": name,
        "enabled": bool(req.enabled),
        "capabilities": capabilities,
        "source": "control_plane",
    }


@router.post("/nodes/heartbeat")
def node_heartbeat_endpoint(req: NodeHeartbeatRequest, _ops=Depends(require_ops_auth)):
    if not NODE_CONTROL_PLANE_ENABLED:
        return {"ok": False, "error": "Node control-plane is disabled."}
    name = str(req.node_name or "").strip().lower()
    if not name:
        return {"ok": False, "error": "node_name is required."}
    heartbeat_at = datetime.utcnow()
    db = SessionLocal()
    try:
        row = db.query(NodeRegistration).filter(NodeRegistration.node_name == name).first()
        if row is None:
            return {"ok": False, "error": f"Node '{name}' is not registered."}
        row.last_heartbeat_at = heartbeat_at
        row.last_error = truncate_text(str(req.last_error or "").strip(), 500) or None
        db.commit()
    except Exception as e:
        db.rollback()
        return {"ok": False, "error": truncate_text(str(e), 260)}
    finally:
        db.close()
    with NODE_CONTROL_LOCK:
        NODE_HEARTBEAT_MAP[name] = {
            "last_heartbeat_at": heartbeat_at.replace(tzinfo=timezone.utc).isoformat(),
            "healthy": bool(req.healthy),
            "last_error": truncate_text(str(req.last_error or "").strip(), 220) or None,
        }
    load_remote_node_registry()
    return {"ok": True, "node_name": name, "healthy": bool(req.healthy)}


@router.get("/nodes/control_plane")
def node_control_plane_status_endpoint(
    limit: int = 50,
    capability: str | None = None,
    preferred_node: str | None = None,
    _ops=Depends(require_ops_auth),
):
    db = SessionLocal()
    try:
        cleanup_expired_node_leases(db)
        db.commit()
        rows = (
            db.query(NodeLease)
            .order_by(NodeLease.id.desc())
            .limit(clamp_int(limit, 1, 500, 50))
            .all()
        )
        leases = [
            {
                "lease_token": row.lease_token,
                "node_name": row.node_name,
                "owner_id": row.owner_id,
                "capability": row.capability,
                "status": row.status,
                "expires_at": iso_datetime_or_none(row.expires_at),
                "released_at": iso_datetime_or_none(row.released_at),
                "created_at": iso_datetime_or_none(row.created_at),
            }
            for row in rows
        ]
    finally:
        db.close()
    required_capability = str(capability or "").strip().lower()
    candidate_scores = _candidate_node_scores(
        capability=required_capability or NODE_AUTO_CAPABILITY_DEFAULT,
        preferred_node=preferred_node,
    )
    candidate_map = {
        str(item.get("node_name")): float(item.get("score", 0.0)) for item in candidate_scores
    }
    nodes_payload = tool_list_execution_nodes().get("nodes", [])
    for row in nodes_payload:
        node_name = str(row.get("name") or "")
        row["scheduler_score"] = candidate_map.get(node_name)
    _refresh_node_runtime_metrics()
    return {
        "ok": True,
        "enabled": bool(NODE_CONTROL_PLANE_ENABLED),
        "nodes": nodes_payload,
        "leases": leases,
        "lease_count": len(leases),
        "recommended_node": candidate_scores[0]["node_name"] if candidate_scores else None,
        "scheduler": {
            "capability": required_capability or None,
            "preferred_node": str(preferred_node or "").strip().lower() or None,
            "lease_penalty": float(NODE_SCHEDULER_LEASE_PENALTY),
            "failure_penalty": float(NODE_SCHEDULER_FAILURE_PENALTY),
            "latency_penalty": float(NODE_SCHEDULER_LATENCY_PENALTY),
            "recovery_bonus": float(NODE_SCHEDULER_RECOVERY_BONUS),
            "failure_window_seconds": int(NODE_SCHEDULER_FAILURE_WINDOW_SECONDS),
            "candidates": [
                {
                    "node_name": str(item.get("node_name")),
                    "score": float(item.get("score", 0.0)),
                    "healthy": bool(item.get("healthy", False)),
                    "exact_capability": bool(item.get("exact_capability", False)),
                    "lease_count": int(item.get("lease_count", 0)),
                    "stats": item.get("stats", {}),
                }
                for item in candidate_scores
            ],
        },
    }


@router.post("/nodes/lease/claim")
def node_lease_claim_endpoint(req: NodeLeaseClaimRequest, _ops=Depends(require_ops_auth)):
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    capability = (
        str(req.capability or NODE_AUTO_CAPABILITY_DEFAULT).strip().lower()
        or NODE_AUTO_CAPABILITY_DEFAULT
    )
    node_name = str(req.node_name or "auto").strip().lower() or "auto"
    result = claim_node_lease(
        owner_id=owner_id,
        capability=capability,
        node_name=node_name,
        ttl_seconds=req.ttl_seconds,
    )
    return result


@router.post("/nodes/lease/release")
def node_lease_release_endpoint(req: NodeLeaseReleaseRequest, _ops=Depends(require_ops_auth)):
    return release_node_lease(req.lease_token)


@router.get("/ops/audit/events")
def ops_audit_events_endpoint(limit: int = 60, _ops=Depends(require_ops_auth)):
    db = SessionLocal()
    try:
        rows = (
            db.query(OpsAuditEvent)
            .order_by(OpsAuditEvent.id.desc())
            .limit(clamp_int(limit, 1, 500, 60))
            .all()
        )
        return {
            "ok": True,
            "count": len(rows),
            "items": [
                {
                    "id": int(row.id),
                    "actor_role": row.actor_role,
                    "actor_ref": row.actor_ref,
                    "action": row.action,
                    "target": row.target,
                    "status": row.status,
                    "created_at": iso_datetime_or_none(row.created_at),
                    "event_hash": row.event_hash,
                    "prev_hash": row.prev_hash,
                    "detail": _safe_json_dict(row.detail_json, {}),
                }
                for row in rows
            ],
        }
    finally:
        db.close()


@router.get("/ops/usage/summary")
def usage_summary_endpoint(
    owner_id: int | None = None,
    source_type: str | None = None,
    max_rows: int = 5000,
    _ops=Depends(require_ops_auth),
):
    db = SessionLocal()
    try:
        q = db.query(UsageLedger)
        if owner_id is not None:
            q = q.filter(UsageLedger.owner_id == int(owner_id))
        if source_type:
            q = q.filter(UsageLedger.source_type == truncate_text(str(source_type), 40))
        rows = q.order_by(UsageLedger.id.desc()).limit(clamp_int(max_rows, 20, 20000, 5000)).all()
        total_cost = 0.0
        total_prompt = 0
        total_completion = 0
        by_model: dict[str, dict] = {}
        for row in rows:
            try:
                total_cost += float(row.estimated_cost_usd or "0")
            except Exception:
                pass
            total_prompt += int(row.prompt_tokens or 0)
            total_completion += int(row.completion_tokens or 0)
            model_name = str(row.model_name or "unknown")
            bucket = by_model.setdefault(
                model_name,
                {"events": 0, "cost_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0},
            )
            bucket["events"] += 1
            bucket["prompt_tokens"] += int(row.prompt_tokens or 0)
            bucket["completion_tokens"] += int(row.completion_tokens or 0)
            try:
                bucket["cost_usd"] += float(row.estimated_cost_usd or "0")
            except Exception:
                pass
        return {
            "ok": True,
            "rows": len(rows),
            "total_prompt_tokens": int(total_prompt),
            "total_completion_tokens": int(total_completion),
            "total_cost_usd": round(float(total_cost), 8),
            "owner_rollup_snapshot": dict(
                RUNTIME_STATE.get("usage_ledger_last_owner_summary") or {}
            ),
            "task_rollup_snapshot": dict(RUNTIME_STATE.get("usage_ledger_last_task_summary") or {}),
            "session_rollup_snapshot": dict(
                RUNTIME_STATE.get("usage_ledger_last_session_summary") or {}
            ),
            "by_model": {
                key: {
                    "events": int(val["events"]),
                    "prompt_tokens": int(val["prompt_tokens"]),
                    "completion_tokens": int(val["completion_tokens"]),
                    "cost_usd": round(float(val["cost_usd"]), 8),
                }
                for key, val in sorted(by_model.items(), key=lambda item: item[0])
            },
        }
    finally:
        db.close()


@router.get("/ops/usage/session")
def usage_session_endpoint(session_id: str, max_rows: int = 500, _ops=Depends(require_ops_auth)):
    sid = str(session_id or "").strip()
    if not sid:
        return {"ok": False, "error": "session_id is required."}
    db = SessionLocal()
    try:
        rows = (
            db.query(UsageLedger)
            .filter(UsageLedger.session_id == sid)
            .order_by(UsageLedger.id.desc())
            .limit(clamp_int(max_rows, 1, 5000, 500))
            .all()
        )
        total_cost = 0.0
        prompt_tokens = 0
        completion_tokens = 0
        for row in rows:
            prompt_tokens += int(row.prompt_tokens or 0)
            completion_tokens += int(row.completion_tokens or 0)
            try:
                total_cost += float(row.estimated_cost_usd or "0")
            except Exception:
                continue
        return {
            "ok": True,
            "session_id": sid,
            "rows": len(rows),
            "total_prompt_tokens": int(prompt_tokens),
            "total_completion_tokens": int(completion_tokens),
            "total_cost_usd": round(float(total_cost), 8),
        }
    finally:
        db.close()


@router.get("/ops/schema/version")
def schema_version_endpoint(_ops=Depends(require_ops_auth)):
    db = SessionLocal()
    try:
        rows = db.query(SchemaMigration).order_by(SchemaMigration.version.asc()).all()
        latest = int(rows[-1].version) if rows else 0
        return {
            "ok": True,
            "schema_version": latest,
            "migrations": [
                {
                    "version": int(row.version),
                    "name": row.name,
                    "checksum": row.checksum,
                    "applied_at": iso_datetime_or_none(row.applied_at),
                }
                for row in rows
            ],
        }
    finally:
        db.close()


# Pillar 3: Goal API endpoints
@router.post("/goal")
async def create_goal_endpoint(request: Request, _ops=Depends(require_ops_auth)):
    body = await request.json() if hasattr(request, "json") else {}
    db = SessionLocal()
    try:
        owner_id = int(body.get("owner_id", 1))
        title = str(body.get("title", "")).strip()
        if not title:
            return {"ok": False, "error": "title required"}
        result = create_goal(
            db,
            owner_id,
            title,
            description=str(body.get("description", "")),
            success_criteria=str(body.get("success_criteria", "")),
            priority=str(body.get("priority", "medium")),
        )
        if result.get("ok"):
            goal_obj = db.query(Goal).filter(Goal.id == result["goal_id"]).first()
            if goal_obj:
                identity = load_identity(db, owner_id)
                task_ids = decompose_goal_into_tasks(db, goal_obj, identity)
                for tid in task_ids:
                    enqueue_task(tid)
                result["task_ids"] = task_ids
        return result
    finally:
        db.close()


@router.get("/goals")
def list_goals_endpoint(_ops=Depends(require_ops_auth), owner_id: int = 1):
    db = SessionLocal()
    try:
        return {"ok": True, "goals": list_goals(db, owner_id)}
    finally:
        db.close()


@router.get("/goal/{goal_id}")
def get_goal_endpoint(goal_id: int, _ops=Depends(require_ops_auth)):
    db = SessionLocal()
    try:
        goal = db.query(Goal).filter(Goal.id == goal_id).first()
        if not goal:
            return {"ok": False, "error": "Goal not found"}
        update_goal_progress(db, goal)
        return {
            "ok": True,
            "goal": {
                "id": goal.id,
                "title": goal.title,
                "description": goal.description,
                "status": goal.status,
                "progress_pct": goal.progress_pct,
                "priority": goal.priority,
                "task_ids": json.loads(goal.task_ids_json or "[]"),
                "milestones": json.loads(goal.milestones_json or "[]"),
                "created_at": str(goal.created_at),
            },
        }
    finally:
        db.close()


@router.patch("/goal/{goal_id}")
async def update_goal_endpoint(goal_id: int, request: Request, _ops=Depends(require_ops_auth)):
    body = await request.json() if hasattr(request, "json") else {}
    db = SessionLocal()
    try:
        goal = db.query(Goal).filter(Goal.id == goal_id).first()
        if not goal:
            return {"ok": False, "error": "Goal not found"}
        if "status" in body:
            goal.status = str(body["status"])[:20]
        if "priority" in body:
            goal.priority = str(body["priority"])[:10]
        db.commit()
        return {"ok": True, "goal_id": goal.id, "status": goal.status}
    finally:
        db.close()


@router.get("/ops/protocol/contracts")
def protocol_contracts_endpoint(_ops=Depends(require_ops_auth)):
    with PROTOCOL_SCHEMA_LOCK:
        contracts = protocol_contracts_public_view(dict(PROTOCOL_SCHEMA_REGISTRY))
    return {
        "ok": True,
        "count": len(contracts),
        "contracts": contracts,
        "timestamp": utc_now_iso(),
    }


@router.post("/ops/memory/reindex")
def ops_memory_reindex_endpoint(
    owner_id: int, rebuild_lessons: bool = False, _ops=Depends(require_ops_auth)
):
    if int(owner_id) <= 0:
        return {"ok": False, "error": "owner_id must be > 0"}
    result = reindex_owner_memory_vectors(
        owner_id=int(owner_id), rebuild_lessons=bool(rebuild_lessons)
    )
    result["timestamp"] = utc_now_iso()
    return result


@router.get("/plugins/tools")
def list_plugins_endpoint(_ops=Depends(require_ops_auth)):
    return tool_list_plugin_tools()


@router.post("/plugins/reload")
def reload_plugins_endpoint(_ops=Depends(require_ops_auth)):
    load_plugin_tools_registry()
    return tool_list_plugin_tools()


@router.post("/eval/run")
def eval_run_endpoint(max_cases: int = EVAL_MAX_CASES, _ops=Depends(require_ops_auth)):
    report = run_continuous_eval_suite(max_cases=max_cases)
    if not report.get("ok", False):
        return {**report, "timestamp": utc_now_iso()}
    return {**report, "timestamp": utc_now_iso()}


@router.get("/eval/last")
def eval_last_endpoint(_ops=Depends(require_ops_auth)):
    report = dict(RUNTIME_STATE.get("eval_last_report") or {})
    if not report:
        return {"ok": False, "error": "No eval run recorded yet.", "timestamp": utc_now_iso()}
    report["timestamp"] = utc_now_iso()
    return report


@router.get("/release/gate")
def release_gate_endpoint(
    run_eval: bool = False, max_cases: int | None = None, _ops=Depends(require_ops_auth)
):
    result = evaluate_release_gate(run_eval=bool(run_eval), max_cases=max_cases)
    result["timestamp"] = utc_now_iso()
    return result


# --- Telegram Webhook ---
@router.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Receive messages from Telegram."""
    data = await request.json()

    # Extract message
    message = data.get("message")
    if not message:
        return {"ok": True}

    chat_id = str(message["chat"]["id"])
    text = message.get("text", "")
    username = message.get("from", {}).get("username", "")

    if not text:
        return {"ok": True}

    log.info(f"Telegram message from {username} ({chat_id}): {text}")

    # Handle /start command
    if text.strip() == "/start":
        await send_telegram_message(
            chat_id,
            "ðŸ§ *Mind Clone activated.*\n\n"
            "I am your sovereign AI agent. I can:\n"
            "â€¢ Search the web\n"
            "â€¢ Read and write files\n"
            "â€¢ Run shell commands\n"
            "â€¢ Read webpages\n\n"
            "Send me any task.",
        )
        return {"ok": True}

    # Handle /identity command â€” show current identity
    if text.strip() == "/identity":
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            identity = load_identity(db, user.id)
            if identity:
                msg = (
                    f"ðŸ† *Identity Kernel*\n\n"
                    f"*UUID:* `{identity['agent_uuid']}`\n"
                    f"*Origin:* {identity['origin_statement']}\n\n"
                    f"*Values:* {', '.join(identity['core_values'])}\n\n"
                    f"*Directives:* {json.dumps(identity['authority_bounds'], indent=2)}"
                )
            else:
                msg = "No identity kernel found."
            await send_telegram_message(chat_id, msg)
        finally:
            db.close()
        return {"ok": True}

    # Handle /clear command â€” clear conversation history
    if text.strip() == "/clear":
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            db.query(ConversationMessage).filter(ConversationMessage.owner_id == user.id).delete()
            db.commit()
            await send_telegram_message(chat_id, "ðŸ§¹ Conversation history cleared.")
        finally:
            db.close()
        return {"ok": True}

    if text.strip().startswith("/approve"):
        token = parse_approval_token(text, "/approve")
        if not token:
            await send_telegram_message(chat_id, "Usage: /approve <token>")
            return {"ok": True}
        await handle_approval_command(chat_id=chat_id, username=username, token=token, approve=True)
        return {"ok": True}

    if text.strip().startswith("/reject"):
        token = parse_approval_token(text, "/reject")
        if not token:
            await send_telegram_message(chat_id, "Usage: /reject <token>")
            return {"ok": True}
        await handle_approval_command(
            chat_id=chat_id, username=username, token=token, approve=False
        )
        return {"ok": True}

    if text.strip().startswith("/cron_add"):
        parsed_cron = parse_cron_add_payload(text.strip())
        if not parsed_cron:
            await send_telegram_message(chat_id, "Usage: /cron_add <interval_seconds> :: <message>")
            return {"ok": True}
        interval_seconds, cron_message = parsed_cron
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            result = tool_schedule_job(
                owner_id=int(user.id),
                name=f"telegram_cron_{int(time.time())}",
                message=cron_message,
                interval_seconds=interval_seconds,
                lane="cron",
            )
            if result.get("ok"):
                await send_telegram_message(
                    chat_id,
                    (
                        f"Cron job created: #{result.get('job_id')}\n"
                        f"Interval: {result.get('interval_seconds')}s\n"
                        f"Next run: {result.get('next_run_at')}"
                    ),
                )
            else:
                await send_telegram_message(
                    chat_id, f"⚠️ {result.get('error', 'Failed to create cron job.')}"
                )
        finally:
            db.close()
        return {"ok": True}

    if text.strip() == "/cron_list":
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            result = tool_list_scheduled_jobs(
                owner_id=int(user.id), include_disabled=True, limit=30
            )
            if not result.get("ok"):
                await send_telegram_message(
                    chat_id, f"⚠️ {result.get('error', 'Failed to list cron jobs.')}"
                )
            else:
                jobs = result.get("jobs", [])
                if not jobs:
                    await send_telegram_message(chat_id, "No cron jobs found.")
                else:
                    lines = ["Cron jobs:"]
                    for row in jobs:
                        status = "on" if row.get("enabled") else "off"
                        lines.append(
                            f"#{row.get('job_id')} [{status}] every {row.get('interval_seconds')}s "
                            f"runs={row.get('run_count')} next={row.get('next_run_at')}"
                        )
                    await send_telegram_message(chat_id, "\n".join(lines))
        finally:
            db.close()
        return {"ok": True}

    if text.strip().startswith("/cron_disable"):
        job_id = parse_command_id(text, "/cron_disable")
        if job_id is None:
            await send_telegram_message(chat_id, "Usage: /cron_disable <job_id>")
            return {"ok": True}
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            result = tool_disable_scheduled_job(owner_id=int(user.id), job_id=job_id)
            if result.get("ok"):
                await send_telegram_message(chat_id, f"Cron job #{job_id} disabled.")
            else:
                await send_telegram_message(
                    chat_id, f"⚠️ {result.get('error', 'Failed to disable cron job.')}"
                )
        finally:
            db.close()
        return {"ok": True}

    if text.strip().startswith("/queue_mode"):
        parts = text.strip().split(maxsplit=1)
        if len(parts) != 2:
            await send_telegram_message(
                chat_id, "Usage: /queue_mode <off|on|auto|steer|followup|collect>"
            )
            return {"ok": True}
        mode_raw = parts[1].strip().lower()
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            mode_set = set_owner_queue_mode(int(user.id), mode_raw)
            await send_telegram_message(
                chat_id, f"Queue mode set to `{mode_set}` for this session."
            )
        finally:
            db.close()
        return {"ok": True}

    if text.strip() == "/tasks":
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            tasks = list_recent_tasks(db, user.id, limit=10)
            if not tasks:
                await send_telegram_message(chat_id, "No tasks found.")
            else:
                lines = ["Recent tasks:"]
                for task in tasks:
                    done, total = task_progress(task.plan)
                    lines.append(
                        f"#{task.id} | {task.status} | {done}/{total} | {truncate_text(task.title, 70)}"
                    )
                await send_telegram_message(chat_id, "\n".join(lines))
        finally:
            db.close()
        return {"ok": True}

    if text.strip().startswith("/task_status"):
        task_id = parse_command_id(text, "/task_status")
        if task_id is None:
            await send_telegram_message(chat_id, "Usage: /task_status <id>")
            return {"ok": True}

        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            task = get_user_task_by_id(db, user.id, task_id)
            if not task:
                await send_telegram_message(chat_id, f"Task #{task_id} not found.")
            else:
                await send_telegram_message(chat_id, format_task_details(task))
        finally:
            db.close()
        return {"ok": True}

    if text.strip().startswith("/task_cancel"):
        task_id = parse_command_id(text, "/task_cancel")
        if task_id is None:
            await send_telegram_message(chat_id, "Usage: /task_cancel <id>")
            return {"ok": True}

        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            task = get_user_task_by_id(db, user.id, task_id)
            if not task:
                await send_telegram_message(chat_id, f"Task #{task_id} not found.")
            else:
                _, msg = cancel_task(db, task)
                await send_telegram_message(chat_id, msg)
        finally:
            db.close()
        return {"ok": True}

    # Pillar 3: /goal commands
    if text.strip().startswith("/goal"):
        parts = text.strip().split(None, 2)
        subcmd = parts[1].lower() if len(parts) > 1 else "help"
        goal_arg = parts[2] if len(parts) > 2 else ""
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            if subcmd == "set" and goal_arg:
                result = create_goal(db, int(user.id), goal_arg)
                if result.get("ok"):
                    goal_obj = db.query(Goal).filter(Goal.id == result["goal_id"]).first()
                    if goal_obj:
                        identity = load_identity(db, int(user.id))
                        new_task_ids = decompose_goal_into_tasks(db, goal_obj, identity)
                        await send_telegram_message(
                            chat_id,
                            f"Goal #{result['goal_id']} created: {result['title']}\n"
                            f"Generated {len(new_task_ids)} tasks.",
                        )
                        for tid in new_task_ids:
                            enqueue_task(tid)
                else:
                    await send_telegram_message(chat_id, f"Goal error: {result.get('error')}")
            elif subcmd == "list":
                goals = list_goals(db, int(user.id))
                if goals:
                    lines = ["Active Goals:"]
                    for g in goals:
                        lines.append(
                            f"#{g['id']} [{g['status']}] {g['title']} ({g['progress_pct']}%)"
                        )
                    await send_telegram_message(chat_id, "\n".join(lines))
                else:
                    await send_telegram_message(chat_id, "No goals found.")
            elif subcmd == "status" and goal_arg:
                try:
                    gid = int(goal_arg)
                    goal_obj = (
                        db.query(Goal).filter(Goal.id == gid, Goal.owner_id == int(user.id)).first()
                    )
                    if goal_obj:
                        update_goal_progress(db, goal_obj)
                        task_ids = json.loads(goal_obj.task_ids_json or "[]")
                        await send_telegram_message(
                            chat_id,
                            f"Goal #{goal_obj.id}: {goal_obj.title}\n"
                            f"Status: {goal_obj.status}\n"
                            f"Progress: {goal_obj.progress_pct}%\n"
                            f"Tasks: {len(task_ids)}\n"
                            f"Priority: {goal_obj.priority}",
                        )
                    else:
                        await send_telegram_message(chat_id, f"Goal #{gid} not found.")
                except ValueError:
                    await send_telegram_message(chat_id, "Usage: /goal status <id>")
            elif subcmd in ("pause", "resume", "abandon") and goal_arg:
                try:
                    gid = int(goal_arg)
                    goal_obj = (
                        db.query(Goal).filter(Goal.id == gid, Goal.owner_id == int(user.id)).first()
                    )
                    if goal_obj:
                        new_status = {
                            "pause": "paused",
                            "resume": "active",
                            "abandon": "abandoned",
                        }[subcmd]
                        goal_obj.status = new_status
                        db.commit()
                        await send_telegram_message(chat_id, f"Goal #{gid} -> {new_status}")
                    else:
                        await send_telegram_message(chat_id, f"Goal #{gid} not found.")
                except ValueError:
                    await send_telegram_message(chat_id, f"Usage: /goal {subcmd} <id>")
            else:
                await send_telegram_message(
                    chat_id,
                    "Goal Commands:\n"
                    "/goal set <title> - Create a new goal\n"
                    "/goal list - List all goals\n"
                    "/goal status <id> - Goal details\n"
                    "/goal pause <id> - Pause a goal\n"
                    "/goal resume <id> - Resume a goal\n"
                    "/goal abandon <id> - Abandon a goal",
                )
        finally:
            db.close()
        return {"ok": True}

    if text.strip().startswith("/task"):
        parsed = parse_task_command_payload(text.strip())
        if not parsed:
            await send_telegram_message(chat_id, "Usage: /task <title> :: <goal>")
            return {"ok": True}

        title, goal = parsed
        db = SessionLocal()
        try:
            user = _resolve_identity_owner(db, chat_id, username)
            task, created_new = create_queued_task(db, user.id, title, goal)
            if created_new:
                enqueue_task(task.id)
                await send_telegram_message(
                    chat_id,
                    f"Task created: #{task.id}\nTitle: {task.title}\nStatus: {task.status}",
                )
            else:
                await send_telegram_message(
                    chat_id,
                    f"Duplicate task detected. Reusing existing task #{task.id} ({task.status}).",
                )
        finally:
            db.close()
        return {"ok": True}

    # --- Main agent flow ---
    owner_id = resolve_owner_id(chat_id, username)
    await dispatch_incoming_message(
        owner_id=owner_id,
        chat_id=chat_id,
        username=username,
        text=text,
        source="telegram",
        expect_response=False,
    )

    return {"ok": True}


class UiMeResponse(BaseModel):
    ok: bool
    owner_id: int | None = None
    username: str | None = None
    chat_id: str | None = None
    identity_summary: dict | None = None
    error: str | None = None


class UiTaskSummaryResponse(BaseModel):
    id: int
    title: str
    status: str
    created_at: str | None = None
    progress_done: int
    progress_total: int
    current_step: str | None = None


class UiTasksListResponse(BaseModel):
    ok: bool
    tasks: list[UiTaskSummaryResponse] = Field(default_factory=list)
    error: str | None = None


class UiTaskCreateRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str | None = None
    title: str
    goal: str


class UiTaskCreateResponse(BaseModel):
    ok: bool
    task_id: int | None = None
    created_new: bool = False
    status: str | None = None
    message: str | None = None
    error: str | None = None


class UiTaskDetailResponse(BaseModel):
    ok: bool
    task: UiTaskSummaryResponse | None = None
    detail_text: str | None = None
    plan: list[dict] = Field(default_factory=list)
    error: str | None = None


class UiTaskCancelRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str | None = None


class UiTaskCancelResponse(BaseModel):
    ok: bool
    status: str | None = None
    message: str | None = None
    error: str | None = None


class TaskResumeSnapshotRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str | None = None
    snapshot_id: int
    branch: bool = False
    strict: bool | None = None


class UiApprovalItemResponse(BaseModel):
    token: str
    tool_name: str
    source_type: str
    source_ref: str | None = None
    step_id: str | None = None
    created_at: str | None = None
    expires_at: str | None = None


class UiApprovalsPendingResponse(BaseModel):
    ok: bool
    approvals: list[UiApprovalItemResponse] = Field(default_factory=list)
    error: str | None = None


@router.get("/ui/me", response_model=UiMeResponse)
def ui_me_endpoint(
    chat_id: str = "",
    username: str = "api_user",
    agent_key: str | None = None,
    db: Session = Depends(get_db),
):
    try:
        user, owner_id, normalized_chat_id = resolve_ui_user_context(
            db, chat_id, username, agent_key=agent_key
        )
    except ValueError as exc:
        return UiMeResponse(ok=False, error=str(exc))

    identity = load_identity(db, owner_id)
    identity_summary = None
    if identity:
        identity_summary = {
            "agent_uuid": identity.get("agent_uuid"),
            "origin_statement": truncate_text(str(identity.get("origin_statement") or ""), 500),
            "core_values": list(identity.get("core_values") or []),
            "authority_bounds": dict(identity.get("authority_bounds") or {}),
        }

    return UiMeResponse(
        ok=True,
        owner_id=owner_id,
        username=user.username,
        chat_id=normalized_chat_id,
        identity_summary=identity_summary,
    )


@router.get("/ui/tasks", response_model=UiTasksListResponse)
def ui_tasks_endpoint(
    chat_id: str = "",
    username: str = "api_user",
    agent_key: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    try:
        _, owner_id, _ = resolve_ui_user_context(db, chat_id, username, agent_key=agent_key)
    except ValueError as exc:
        return UiTasksListResponse(ok=False, error=str(exc))

    rows = list_recent_tasks(db, owner_id, limit=clamp_int(limit, 1, 100, 20))
    payload = [UiTaskSummaryResponse(**serialize_task_summary(row)) for row in rows]
    return UiTasksListResponse(ok=True, tasks=payload)


@router.post("/ui/tasks", response_model=UiTaskCreateResponse)
def ui_task_create_endpoint(req: UiTaskCreateRequest, db: Session = Depends(get_db)):
    title = truncate_text(str(req.title or "").strip(), 140)
    goal = truncate_text(str(req.goal or "").strip(), 6000)
    if not title or not goal:
        return UiTaskCreateResponse(ok=False, error="Both title and goal are required.")

    try:
        _, owner_id, _ = resolve_ui_user_context(
            db, req.chat_id, req.username, agent_key=req.agent_key
        )
    except ValueError as exc:
        return UiTaskCreateResponse(ok=False, error=str(exc))

    task, created_new = create_queued_task(db, owner_id, title, goal)
    if created_new:
        enqueue_task(task.id)
        message = f"Task #{task.id} created and queued."
    else:
        message = f"Duplicate detected, reusing task #{task.id} ({task.status})."

    return UiTaskCreateResponse(
        ok=True,
        task_id=int(task.id),
        created_new=bool(created_new),
        status=task.status,
        message=message,
    )


@router.get("/ui/tasks/{task_id}", response_model=UiTaskDetailResponse)
def ui_task_detail_endpoint(
    task_id: int,
    chat_id: str = "",
    username: str = "api_user",
    agent_key: str | None = None,
    db: Session = Depends(get_db),
):
    try:
        _, owner_id, _ = resolve_ui_user_context(db, chat_id, username, agent_key=agent_key)
    except ValueError as exc:
        return UiTaskDetailResponse(ok=False, error=str(exc))

    task = get_user_task_by_id(db, owner_id, int(task_id))
    if not task:
        return UiTaskDetailResponse(ok=False, error=f"Task #{task_id} not found.")

    return UiTaskDetailResponse(
        ok=True,
        task=UiTaskSummaryResponse(**serialize_task_summary(task)),
        detail_text=format_task_details(task),
        plan=normalize_task_plan(task.plan),
    )


@router.post("/ui/tasks/{task_id}/cancel", response_model=UiTaskCancelResponse)
def ui_task_cancel_endpoint(task_id: int, req: UiTaskCancelRequest, db: Session = Depends(get_db)):
    try:
        _, owner_id, _ = resolve_ui_user_context(
            db, req.chat_id, req.username, agent_key=req.agent_key
        )
    except ValueError as exc:
        return UiTaskCancelResponse(ok=False, error=str(exc))

    task = get_user_task_by_id(db, owner_id, int(task_id))
    if not task:
        return UiTaskCancelResponse(ok=False, error=f"Task #{task_id} not found.")

    ok, message = cancel_task(db, task)
    return UiTaskCancelResponse(
        ok=bool(ok),
        status=task.status,
        message=message,
        error=None if ok else message,
    )


@router.get("/ops/tasks/{task_id}/checkpoints")
def task_checkpoint_list_endpoint(
    task_id: int,
    chat_id: str,
    username: str = "api_user",
    agent_key: str | None = None,
    limit: int = 25,
    db: Session = Depends(get_db),
    _ops=Depends(require_ops_auth),
):
    owner_id = resolve_owner_id(chat_id, username, agent_key)
    task = get_user_task_by_id(db, owner_id, int(task_id))
    if not task:
        return {"ok": False, "error": f"Task #{task_id} not found."}
    rows = (
        db.query(TaskCheckpointSnapshot)
        .filter(
            TaskCheckpointSnapshot.task_id == int(task.id),
            TaskCheckpointSnapshot.owner_id == int(owner_id),
        )
        .order_by(TaskCheckpointSnapshot.id.desc())
        .limit(clamp_int(limit, 1, 200, 25))
        .all()
    )
    return {
        "ok": True,
        "task_id": int(task.id),
        "status": task.status,
        "count": len(rows),
        "checkpoints": [
            {
                "id": int(row.id),
                "source": row.source,
                "task_status": row.task_status,
                "created_at": iso_datetime_or_none(row.created_at),
                "extra": _safe_json_dict(row.extra_json, {}),
                "replay_state": _safe_json_dict(
                    _safe_json_dict(row.extra_json, {}).get("replay_state"), {}
                ),
            }
            for row in rows
        ],
    }


@router.post("/ops/tasks/{task_id}/resume_latest")
def task_resume_latest_checkpoint_endpoint(
    task_id: int,
    chat_id: str,
    username: str = "api_user",
    agent_key: str | None = None,
    strict: bool | None = None,
    db: Session = Depends(get_db),
    _ops=Depends(require_ops_auth),
):
    owner_id = resolve_owner_id(chat_id, username, agent_key)
    task = get_user_task_by_id(db, owner_id, int(task_id))
    if not task:
        return {"ok": False, "error": f"Task #{task_id} not found."}
    snap = latest_task_checkpoint_snapshot(db, int(task.id))
    if not snap:
        return {"ok": False, "error": f"Task #{task_id} has no checkpoint snapshots."}
    strict_mode = TASK_CHECKPOINT_REPLAY_STRICT if strict is None else bool(strict)
    restored = restore_task_from_checkpoint_snapshot(db, task, snap, strict=strict_mode)
    if not restored:
        return {"ok": False, "error": "Latest checkpoint failed deterministic validation."}
    task.status = TASK_STATUS_QUEUED
    store_task_checkpoint_snapshot(
        db,
        task,
        "manual_resume_latest",
        extra={
            "from_snapshot_id": int(snap.id),
            "replay_mode": "strict" if strict_mode else "legacy",
        },
    )
    db.commit()
    enqueue_task(int(task.id))
    return {
        "ok": True,
        "task_id": int(task.id),
        "from_snapshot_id": int(snap.id),
        "status": task.status,
        "replay_mode": "strict" if strict_mode else "legacy",
        "message": f"Task #{task.id} resumed from latest checkpoint.",
    }


@router.post("/ops/tasks/{task_id}/resume_from_snapshot")
def task_resume_from_snapshot_endpoint(
    task_id: int,
    req: TaskResumeSnapshotRequest,
    db: Session = Depends(get_db),
    _ops=Depends(require_ops_auth),
):
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    task = get_user_task_by_id(db, owner_id, int(task_id))
    if not task:
        return {"ok": False, "error": f"Task #{task_id} not found."}
    snap = (
        db.query(TaskCheckpointSnapshot)
        .filter(
            TaskCheckpointSnapshot.id == int(req.snapshot_id),
            TaskCheckpointSnapshot.task_id == int(task.id),
            TaskCheckpointSnapshot.owner_id == int(owner_id),
        )
        .first()
    )
    if not snap:
        return {"ok": False, "error": f"Snapshot #{req.snapshot_id} not found for task #{task.id}."}
    strict_mode = TASK_CHECKPOINT_REPLAY_STRICT if req.strict is None else bool(req.strict)
    plan = normalize_task_plan(_safe_json_list(snap.plan_json, []))
    if not plan:
        return {"ok": False, "error": "Checkpoint plan is empty or invalid."}
    snap_extra = _safe_json_dict(snap.extra_json, {})
    replay_ok, replay_reason, _ = _validate_checkpoint_replay_state(
        task, plan, snap_extra, strict=strict_mode
    )
    if not replay_ok:
        RUNTIME_STATE["task_checkpoint_restore_failures"] = (
            int(RUNTIME_STATE.get("task_checkpoint_restore_failures", 0)) + 1
        )
        RUNTIME_STATE["task_checkpoint_restore_drift"] = (
            int(RUNTIME_STATE.get("task_checkpoint_restore_drift", 0)) + 1
        )
        return {
            "ok": False,
            "error": f"Checkpoint validation failed: {replay_reason or 'unknown'}",
        }

    if bool(req.branch):
        branched = Task(
            owner_id=int(task.owner_id),
            agent_uuid=str(task.agent_uuid),
            title=truncate_text(str(snap_extra.get("task_title") or task.title), 200),
            description=truncate_text(
                str(snap_extra.get("task_description") or task.description), 8000
            ),
            status=TASK_STATUS_QUEUED,
            plan=plan,
        )
        db.add(branched)
        db.flush()
        store_task_checkpoint_snapshot(
            db,
            branched,
            "manual_branch_resume",
            extra={
                "from_task_id": int(task.id),
                "from_snapshot_id": int(snap.id),
                "replay_mode": "strict" if strict_mode else "legacy",
            },
        )
        db.commit()
        enqueue_task(int(branched.id))
        return {
            "ok": True,
            "task_id": int(branched.id),
            "branched_from_task_id": int(task.id),
            "from_snapshot_id": int(snap.id),
            "status": branched.status,
            "replay_mode": "strict" if strict_mode else "legacy",
            "message": f"Created task #{branched.id} from checkpoint #{snap.id}.",
        }

    restored = restore_task_from_checkpoint_snapshot(db, task, snap, strict=strict_mode)
    if not restored:
        return {"ok": False, "error": "Checkpoint failed deterministic restore validation."}
    task.status = TASK_STATUS_QUEUED
    store_task_checkpoint_snapshot(
        db,
        task,
        "manual_resume_snapshot",
        extra={
            "from_snapshot_id": int(snap.id),
            "replay_mode": "strict" if strict_mode else "legacy",
        },
    )
    db.commit()
    enqueue_task(int(task.id))
    return {
        "ok": True,
        "task_id": int(task.id),
        "from_snapshot_id": int(snap.id),
        "status": task.status,
        "replay_mode": "strict" if strict_mode else "legacy",
        "message": f"Task #{task.id} resumed from checkpoint #{snap.id}.",
    }


@router.get("/ui/approvals/pending", response_model=UiApprovalsPendingResponse)
def ui_pending_approvals_endpoint(
    chat_id: str = "",
    username: str = "api_user",
    agent_key: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    try:
        _, owner_id, _ = resolve_ui_user_context(db, chat_id, username, agent_key=agent_key)
    except ValueError as exc:
        return UiApprovalsPendingResponse(ok=False, error=str(exc))

    approvals = list_pending_approvals_for_owner(db, owner_id, limit=limit)
    payload = [UiApprovalItemResponse(**item) for item in approvals]
    return UiApprovalsPendingResponse(ok=True, approvals=payload)


class IdentityLinkRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    target_chat_id: str
    target_username: str | None = None


@router.post("/identity/link")
def identity_link_endpoint(req: IdentityLinkRequest, db: Session = Depends(get_db)):
    root_owner, _, _ = resolve_root_ui_user_context(db, req.chat_id, req.username)
    target_chat = str(req.target_chat_id or "").strip()
    if not target_chat:
        return {"ok": False, "error": "target_chat_id is required."}
    _upsert_identity_link(
        db=db,
        canonical_owner_id=int(root_owner.id),
        linked_chat_id=target_chat,
        linked_username=req.target_username,
        scope_mode="linked_explicit",
    )
    return {
        "ok": True,
        "canonical_owner_id": int(root_owner.id),
        "linked_chat_id": target_chat,
        "scope_mode": "linked_explicit",
    }


@router.get("/identity/links")
def identity_links_endpoint(
    chat_id: str, username: str = "api_user", db: Session = Depends(get_db)
):
    root_owner, root_owner_id, _ = resolve_root_ui_user_context(db, chat_id, username)
    rows = (
        db.query(IdentityLink)
        .filter(IdentityLink.canonical_owner_id == int(root_owner_id))
        .order_by(IdentityLink.id.asc())
        .all()
    )
    return {
        "ok": True,
        "owner_id": int(root_owner.id),
        "scope_mode": IDENTITY_SCOPE_MODE,
        "links": [
            {
                "linked_chat_id": str(row.linked_chat_id),
                "linked_username": row.linked_username,
                "scope_mode": row.scope_mode,
                "created_at": iso_datetime_or_none(row.created_at),
            }
            for row in rows
        ],
    }


@router.get("/context/list")
def context_list_endpoint(
    chat_id: str,
    username: str = "api_user",
    agent_key: str | None = None,
    limit: int = 20,
):
    ctx = resolve_owner_context(chat_id, username, agent_key=agent_key)
    items = list_context_snapshots(ctx["owner_id"], limit=limit)
    return {"ok": True, "owner_id": ctx["owner_id"], "agent_key": ctx["agent_key"], "items": items}


@router.get("/context/detail")
def context_detail_endpoint(
    chat_id: str,
    snapshot_id: int,
    username: str = "api_user",
    agent_key: str | None = None,
):
    ctx = resolve_owner_context(chat_id, username, agent_key=agent_key)
    item = get_context_snapshot(ctx["owner_id"], snapshot_id)
    if not item:
        return {"ok": False, "error": f"Snapshot #{snapshot_id} not found."}
    return {"ok": True, "snapshot": item}


@router.get("/context/json")
def context_json_endpoint(
    chat_id: str,
    username: str = "api_user",
    agent_key: str | None = None,
    limit: int = 5,
):
    ctx = resolve_owner_context(chat_id, username, agent_key=agent_key)
    items = list_context_snapshots(ctx["owner_id"], limit=limit)
    detailed: list[dict] = []
    for row in items:
        item = get_context_snapshot(ctx["owner_id"], int(row.get("snapshot_id", 0)))
        if item:
            detailed.append(item)
    return {
        "ok": True,
        "owner_id": ctx["owner_id"],
        "agent_key": ctx["agent_key"],
        "count": len(detailed),
        "snapshots": detailed,
    }


class TeamAgentSpawnRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str
    display_name: str | None = None


class TeamAgentSendRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str
    message: str
    expect_response: bool = True


class TeamAgentStopRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str
    stop: bool = True


@router.post("/agents/spawn")
def team_agent_spawn_endpoint(req: TeamAgentSpawnRequest, db: Session = Depends(get_db)):
    root_owner, root_owner_id, _ = resolve_root_ui_user_context(db, req.chat_id, req.username)
    if not TEAM_MODE_ENABLED:
        return {"ok": False, "error": "Team mode is disabled."}
    key = normalize_agent_key(req.agent_key)
    if key == TEAM_AGENT_DEFAULT_KEY:
        return {
            "ok": False,
            "error": f"'{TEAM_AGENT_DEFAULT_KEY}' is reserved for the primary agent.",
        }
    if not team_spawn_policy_allows(TEAM_AGENT_DEFAULT_KEY, key):
        return {"ok": False, "error": f"Spawn policy blocked creation of '{key}'."}
    user = _ensure_team_agent_owner(db, root_owner, key, display_name=req.display_name)
    row, _ = get_team_agent_with_user(db, root_owner_id, key)
    if row is None:
        return {"ok": False, "error": "Failed to create team agent."}
    row.status = "active"
    row.last_seen_at = datetime.utcnow()
    if req.display_name:
        row.display_name = truncate_text(str(req.display_name), 80)
    db.commit()
    return {"ok": True, "agent": serialize_team_agent(row, user)}


@router.get("/agents/list")
def team_agent_list_endpoint(
    chat_id: str,
    username: str = "api_user",
    include_stopped: bool = True,
    db: Session = Depends(get_db),
):
    _, root_owner_id, _ = resolve_root_ui_user_context(db, chat_id, username)
    payload = list_team_agents_for_owner(db, root_owner_id, include_stopped=bool(include_stopped))
    return {"ok": True, "count": len(payload), "agents": payload}


@router.post("/agents/send")
async def team_agent_send_endpoint(req: TeamAgentSendRequest, db: Session = Depends(get_db)):
    _, agent_user, _, _ = resolve_team_agent_owner_for_request(
        db=db,
        chat_id=req.chat_id,
        username=req.username,
        agent_key=req.agent_key,
        create_if_missing=False,
        require_active=True,
    )
    text = truncate_text(str(req.message or "").strip(), 6000)
    if not text:
        return {"ok": False, "error": "message is required."}
    result = await dispatch_incoming_message(
        owner_id=int(agent_user.id),
        chat_id=req.chat_id,
        username=str(agent_user.username or req.username),
        text=text,
        source="api",
        expect_response=bool(req.expect_response),
    )
    return {
        "ok": bool(result.get("ok", False)),
        "agent_key": normalize_agent_key(req.agent_key),
        "owner_id": int(agent_user.id),
        **result,
    }


@router.get("/agents/log")
def team_agent_log_endpoint(
    chat_id: str,
    agent_key: str,
    username: str = "api_user",
    limit: int = 40,
    db: Session = Depends(get_db),
):
    _, agent_user, _, _ = resolve_team_agent_owner_for_request(
        db=db,
        chat_id=chat_id,
        username=username,
        agent_key=agent_key,
        create_if_missing=False,
        require_active=False,
    )
    rows = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.owner_id == int(agent_user.id))
        .order_by(ConversationMessage.id.desc())
        .limit(clamp_int(limit, 1, 200, 40))
        .all()
    )
    rows.reverse()
    items = []
    for row in rows:
        items.append(
            {
                "id": int(row.id),
                "role": row.role,
                "content": truncate_text(str(row.content or ""), 2400),
                "tool_call_id": row.tool_call_id,
                "created_at": iso_datetime_or_none(row.created_at),
            }
        )
    return {
        "ok": True,
        "agent_key": normalize_agent_key(agent_key),
        "count": len(items),
        "items": items,
    }


@router.post("/agents/stop")
def team_agent_stop_endpoint(req: TeamAgentStopRequest, db: Session = Depends(get_db)):
    root_owner, root_owner_id, _ = resolve_root_ui_user_context(db, req.chat_id, req.username)
    key = normalize_agent_key(req.agent_key)
    row, user = get_team_agent_with_user(db, root_owner_id, key)
    if row is None or user is None:
        return {"ok": False, "error": f"Agent '{key}' not found."}
    row.status = "stopped" if bool(req.stop) else "active"
    row.last_seen_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "agent": serialize_team_agent(row, user), "owner_id": int(root_owner.id)}


@router.get("/team/presence")
def team_presence_endpoint(chat_id: str, username: str = "api_user", db: Session = Depends(get_db)):
    root_owner, root_owner_id, _ = resolve_root_ui_user_context(db, chat_id, username)
    agents = list_team_agents_for_owner(db, root_owner_id, include_stopped=True)
    active = [row for row in agents if row.get("status") == "active"]
    return {
        "ok": True,
        "owner_id": int(root_owner.id),
        "team_mode_enabled": bool(TEAM_MODE_ENABLED),
        "active_agents": len(active),
        "total_agents": len(agents),
        "agents": agents,
    }


class TeamBroadcastRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    message: str
    include_main: bool = False


@router.post("/team/broadcast")
async def team_broadcast_endpoint(req: TeamBroadcastRequest, db: Session = Depends(get_db)):
    if not TEAM_BROADCAST_ENABLED:
        return {"ok": False, "error": "Team broadcast is disabled."}
    root_owner, root_owner_id, _ = resolve_root_ui_user_context(db, req.chat_id, req.username)
    message = truncate_text(str(req.message or "").strip(), 6000)
    if not message:
        return {"ok": False, "error": "message is required."}
    agents = list_team_agents_for_owner(db, root_owner_id, include_stopped=False)
    targets = list(agents)
    if req.include_main:
        targets.insert(
            0,
            {
                "agent_key": TEAM_AGENT_DEFAULT_KEY,
                "agent_owner_id": int(root_owner.id),
                "username": root_owner.username,
                "status": "active",
            },
        )
    responses = []
    for target in targets:
        if target.get("status") != "active":
            continue
        target_owner_id = int(target.get("agent_owner_id") or root_owner.id)
        result = await dispatch_incoming_message(
            owner_id=target_owner_id,
            chat_id=req.chat_id,
            username=str(target.get("username") or req.username),
            text=message,
            source="api",
            expect_response=True,
        )
        responses.append(
            {
                "agent_key": target.get("agent_key"),
                "owner_id": target_owner_id,
                "ok": bool(result.get("ok", False)),
                "response": truncate_text(str(result.get("response") or ""), 2000),
                "error": result.get("error"),
            }
        )
    RUNTIME_STATE["team_broadcasts_total"] = int(RUNTIME_STATE.get("team_broadcasts_total", 0)) + 1
    return {"ok": True, "count": len(responses), "responses": responses}


class HostExecGrantRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str | None = None
    node_name: str = "local"
    command_prefix: str
    ttl_minutes: int | None = None


@router.post("/ops/host_exec/grant")
def host_exec_grant_endpoint(req: HostExecGrantRequest, _ops=Depends(require_ops_auth)):
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    prefix = truncate_text(str(req.command_prefix or "").strip().lower(), 80)
    if not prefix:
        return {"ok": False, "error": "command_prefix is required."}
    return create_host_exec_grant(
        owner_id=owner_id,
        node_name=req.node_name,
        command_prefix=prefix,
        created_by="ops_api",
        ttl_minutes=req.ttl_minutes,
    )


@router.get("/ops/host_exec/grants")
def host_exec_grants_endpoint(
    chat_id: str,
    username: str = "api_user",
    agent_key: str | None = None,
    limit: int = 20,
    _ops=Depends(require_ops_auth),
):
    owner_id = resolve_owner_id(chat_id, username, agent_key)
    db = SessionLocal()
    try:
        rows = (
            db.query(HostExecGrant)
            .filter((HostExecGrant.owner_id == int(owner_id)) | (HostExecGrant.owner_id.is_(None)))
            .order_by(HostExecGrant.id.desc())
            .limit(clamp_int(limit, 1, 200, 20))
            .all()
        )
        items = [
            {
                "token": row.token,
                "owner_id": row.owner_id,
                "node_name": row.node_name,
                "command_prefix": row.command_prefix,
                "status": row.status,
                "expires_at": iso_datetime_or_none(row.expires_at),
                "consumed_at": iso_datetime_or_none(row.consumed_at),
                "created_at": iso_datetime_or_none(row.created_at),
            }
            for row in rows
        ]
        return {"ok": True, "count": len(items), "items": items}
    finally:
        db.close()


class MemoryVaultRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str | None = None
    message: str | None = None
    ref: str | None = None


@router.post("/vault/bootstrap")
def vault_bootstrap_endpoint(req: MemoryVaultRequest):
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    return memory_vault_bootstrap(owner_id)


@router.post("/vault/backup")
def vault_backup_endpoint(req: MemoryVaultRequest):
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    return memory_vault_backup(owner_id, message=str(req.message or "vault backup"))


@router.post("/vault/restore")
def vault_restore_endpoint(req: MemoryVaultRequest):
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    return memory_vault_restore(owner_id, ref=str(req.ref or "HEAD"))


class WorkflowProgramRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    name: str
    body: str


class WorkflowRunRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    name: str | None = None
    body: str | None = None


@router.post("/workflow/programs")
def workflow_program_upsert_endpoint(req: WorkflowProgramRequest, db: Session = Depends(get_db)):
    root_owner, root_owner_id, _ = resolve_root_ui_user_context(db, req.chat_id, req.username)
    name = truncate_text(str(req.name or "").strip().lower(), 80)
    if not name:
        return {"ok": False, "error": "name is required."}
    body = str(req.body or "")
    try:
        parse_workflow_program_text(body)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    row = (
        db.query(WorkflowProgram)
        .filter(
            WorkflowProgram.owner_id == int(root_owner_id),
            WorkflowProgram.name == name,
        )
        .first()
    )
    if row:
        row.body_text = body
    else:
        row = WorkflowProgram(owner_id=int(root_owner_id), name=name, body_text=body)
        db.add(row)
    db.commit()
    RUNTIME_STATE["workflow_programs_total"] = int(
        db.query(WorkflowProgram).filter(WorkflowProgram.owner_id == int(root_owner_id)).count()
    )
    return {"ok": True, "owner_id": int(root_owner.id), "name": name}


@router.get("/workflow/programs")
def workflow_program_list_endpoint(
    chat_id: str, username: str = "api_user", db: Session = Depends(get_db)
):
    _, root_owner_id, _ = resolve_root_ui_user_context(db, chat_id, username)
    rows = (
        db.query(WorkflowProgram)
        .filter(WorkflowProgram.owner_id == int(root_owner_id))
        .order_by(WorkflowProgram.id.asc())
        .all()
    )
    return {
        "ok": True,
        "count": len(rows),
        "programs": [
            {
                "name": row.name,
                "created_at": iso_datetime_or_none(row.created_at),
                "updated_at": iso_datetime_or_none(row.updated_at),
                "preview": truncate_text(row.body_text or "", 300),
            }
            for row in rows
        ],
    }


@router.post("/workflow/run")
async def workflow_run_endpoint(req: WorkflowRunRequest, db: Session = Depends(get_db)):
    root_owner, root_owner_id, _ = resolve_root_ui_user_context(db, req.chat_id, req.username)
    body = str(req.body or "").strip()
    if not body:
        name = truncate_text(str(req.name or "").strip().lower(), 80)
        row = (
            db.query(WorkflowProgram)
            .filter(
                WorkflowProgram.owner_id == int(root_owner_id),
                WorkflowProgram.name == name,
            )
            .first()
        )
        if not row:
            return {"ok": False, "error": "Workflow program not found."}
        body = row.body_text or ""
    try:
        steps = parse_workflow_program_text(body)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    events: list[dict] = []
    event_no = 0
    v2_used = False
    variables: dict[str, str] = {
        "owner_id": str(root_owner.id),
        "chat_id": str(req.chat_id),
        "username": str(req.username or "api_user"),
    }

    def next_event_no() -> int:
        nonlocal event_no
        event_no += 1
        return event_no

    async def run_steps(step_list: list[dict], depth: int = 0):
        nonlocal v2_used
        if depth > 8:
            raise ValueError("Workflow nesting depth is too high.")
        for step in step_list:
            kind = str(step.get("kind") or "").strip().lower()
            if kind == "set":
                v2_used = True
                key = str(step.get("name") or "").strip()
                value = _workflow_render_template(str(step.get("value") or ""), variables)
                variables[key] = value
                events.append(
                    {
                        "step": next_event_no(),
                        "kind": "set",
                        "name": key,
                        "value": truncate_text(value, 240),
                        "ok": True,
                    }
                )
                continue
            if kind == "if":
                v2_used = True
                condition = str(step.get("condition") or "")
                try:
                    matched = bool(_workflow_eval_condition(condition, variables))
                except Exception as exc:
                    events.append(
                        {
                            "step": next_event_no(),
                            "kind": "if",
                            "condition": condition,
                            "ok": False,
                            "error": str(exc),
                        }
                    )
                    continue
                events.append(
                    {
                        "step": next_event_no(),
                        "kind": "if",
                        "condition": condition,
                        "matched": matched,
                        "ok": True,
                    }
                )
                if matched:
                    await run_steps(_safe_json_list(step.get("steps"), []), depth=depth + 1)
                continue
            if kind == "loop":
                v2_used = True
                iterations = clamp_int(step.get("count"), 1, WORKFLOW_LOOP_MAX_ITERATIONS, 1)
                events.append(
                    {
                        "step": next_event_no(),
                        "kind": "loop",
                        "iterations": int(iterations),
                        "ok": True,
                    }
                )
                for idx in range(iterations):
                    variables["loop_index"] = str(idx + 1)
                    variables["loop_count"] = str(iterations)
                    await run_steps(_safe_json_list(step.get("steps"), []), depth=depth + 1)
                variables.pop("loop_index", None)
                variables.pop("loop_count", None)
                continue
            if kind == "sleep":
                seconds = float(step.get("seconds") or 0.0)
                await asyncio.sleep(seconds)
                events.append(
                    {"step": next_event_no(), "kind": "sleep", "seconds": seconds, "ok": True}
                )
                continue
            if kind == "task":
                key = normalize_agent_key(
                    _workflow_render_template(str(step.get("agent_key") or ""), variables)
                )
                title = _workflow_render_template(str(step.get("title") or ""), variables)
                goal = _workflow_render_template(str(step.get("goal") or ""), variables)
                _, owner_user, _, _ = resolve_team_agent_owner_for_request(
                    db=db,
                    chat_id=req.chat_id,
                    username=req.username,
                    agent_key=key,
                    create_if_missing=True,
                    require_active=True,
                )
                task, created_new = create_queued_task(
                    db,
                    int(owner_user.id),
                    truncate_text(title, 140),
                    truncate_text(goal, 6000),
                )
                if created_new:
                    enqueue_task(int(task.id))
                events.append(
                    {
                        "step": next_event_no(),
                        "kind": "task",
                        "agent_key": key,
                        "task_id": int(task.id),
                        "created_new": bool(created_new),
                        "ok": True,
                    }
                )
                continue
            if kind in {"send", "broadcast"}:
                message = _workflow_render_template(str(step.get("message") or ""), variables)
                if kind == "broadcast":
                    team_rows = list_team_agents_for_owner(
                        db, int(root_owner_id), include_stopped=False
                    )
                    targets = [normalize_agent_key(row.get("agent_key")) for row in team_rows]
                    if not targets:
                        targets = [TEAM_AGENT_DEFAULT_KEY]
                else:
                    targets = [
                        normalize_agent_key(
                            _workflow_render_template(str(step.get("agent_key") or ""), variables)
                        )
                    ]
                for target_key in targets:
                    _, agent_user, _, _ = resolve_team_agent_owner_for_request(
                        db=db,
                        chat_id=req.chat_id,
                        username=req.username,
                        agent_key=target_key,
                        create_if_missing=True,
                        require_active=True,
                    )
                    result = await dispatch_incoming_message(
                        owner_id=int(agent_user.id),
                        chat_id=req.chat_id,
                        username=str(agent_user.username or req.username),
                        text=truncate_text(message, 4000),
                        source="api",
                        expect_response=True,
                    )
                    events.append(
                        {
                            "step": next_event_no(),
                            "kind": kind,
                            "agent_key": target_key,
                            "ok": bool(result.get("ok", False)),
                            "response": truncate_text(str(result.get("response") or ""), 1200),
                            "error": result.get("error"),
                        }
                    )
                continue
            events.append(
                {"step": next_event_no(), "kind": kind, "ok": False, "error": "Unsupported step"}
            )

    try:
        await run_steps(steps, depth=0)
    except Exception as exc:
        return {"ok": False, "error": truncate_text(str(exc), 240), "events": events}

    RUNTIME_STATE["workflow_runs_total"] = int(RUNTIME_STATE.get("workflow_runs_total", 0)) + 1
    if v2_used:
        RUNTIME_STATE["workflow_v2_runs"] = int(RUNTIME_STATE.get("workflow_v2_runs", 0)) + 1
    return {
        "ok": True,
        "owner_id": int(root_owner.id),
        "steps": int(_count_workflow_actions(steps)),
        "workflow_v2_used": bool(v2_used),
        "events": events,
    }


# --- Direct API endpoint (for testing without Telegram) ---
class ChatRequest(BaseModel):
    chat_id: str
    message: str
    username: str = "api_user"
    agent_key: str | None = None


@router.post("/chat")
async def chat_endpoint(req: ChatRequest):
    req_payload = req.model_dump()
    ok_req, err_req = protocol_validate_payload("chat.request", req_payload, direction="request")
    if not ok_req:
        return {"ok": False, "error": f"Protocol validation failed: {err_req}"}
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    result = await dispatch_incoming_message(
        owner_id=owner_id,
        chat_id=req.chat_id,
        username=req.username,
        text=req.message,
        source="api",
        expect_response=True,
    )
    if result.get("ok"):
        response_payload = {"ok": True, "response": result.get("response", "")}
        protocol_validate_payload("chat.response", response_payload, direction="response")
        return response_payload
    response_payload = {"ok": False, "error": result.get("error", "Unknown error")}
    protocol_validate_payload("chat.response", response_payload, direction="response")
    return response_payload


class ApprovalDecisionRequest(BaseModel):
    chat_id: str
    token: str
    approve: bool = True
    username: str = "api_user"
    agent_key: str | None = None
    reason: str = ""


@router.post("/approval/decision")
async def approval_decision_endpoint(req: ApprovalDecisionRequest):
    req_payload = req.model_dump()
    ok_req, err_req = protocol_validate_payload(
        "approval.decision.request", req_payload, direction="request"
    )
    if not ok_req:
        return {"ok": False, "error": f"Protocol validation failed: {err_req}"}
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    result = approval_manager_decide_token(
        owner_id=owner_id,
        token=req.token,
        approve=bool(req.approve),
        reason=req.reason,
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "Failed to process approval decision.")}

    token_owner_id = int(result.get("owner_id") or owner_id)
    if result.get("status") == "approved":
        payload = _safe_json_dict(result.get("resume_payload"), {})
        kind = str(payload.get("kind") or "")
        if kind == "task_step":
            task_id = int(payload.get("task_id") or 0)
            step_id = str(payload.get("step_id") or "") or None
            ok, msg = unpause_task_after_approval(
                owner_id=token_owner_id, task_id=task_id, step_id=step_id
            )
            return {"ok": ok, "status": result.get("status"), "message": msg}
        if kind == "chat_message":
            user_message = str(payload.get("user_message") or "").strip()
            if user_message:
                await dispatch_incoming_message(
                    owner_id=token_owner_id,
                    chat_id=req.chat_id,
                    username=req.username,
                    text=user_message,
                    source="api",
                    expect_response=False,
                )
                return {"ok": True, "status": result.get("status"), "resumed": "chat_message"}
    return {"ok": True, "status": result.get("status"), "token": result.get("token")}


class CronCreateRequest(BaseModel):
    chat_id: str
    name: str
    message: str
    interval_seconds: int = 300
    lane: str = "cron"
    username: str = "api_user"
    agent_key: str | None = None


class QueueModeRequest(BaseModel):
    chat_id: str
    username: str = "api_user"
    agent_key: str | None = None
    mode: str


@router.post("/ops/queue/mode")
def queue_mode_set_endpoint(req: QueueModeRequest, _ops=Depends(require_ops_auth)):
    ok_req, err_req = protocol_validate_payload(
        "queue.mode.request", req.model_dump(), direction="request"
    )
    if not ok_req:
        return {"ok": False, "error": f"Protocol validation failed: {err_req}"}
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    normalized = set_owner_queue_mode(owner_id=int(owner_id), mode=req.mode)
    payload = {"ok": True, "owner_id": int(owner_id), "mode": normalized}
    protocol_validate_payload("queue.mode.response", payload, direction="response")
    return payload


@router.get("/ops/queue/mode")
def queue_mode_get_endpoint(
    chat_id: str,
    username: str = "api_user",
    agent_key: str | None = None,
    _ops=Depends(require_ops_auth),
):
    owner_id = resolve_owner_id(chat_id, username, agent_key)
    payload = {
        "ok": True,
        "owner_id": int(owner_id),
        "mode": effective_command_queue_mode(owner_id),
    }
    protocol_validate_payload("queue.mode.response", payload, direction="response")
    return payload


@router.post("/cron/jobs")
def cron_create_endpoint(req: CronCreateRequest, _ops=Depends(require_ops_auth)):
    owner_id = resolve_owner_id(req.chat_id, req.username, req.agent_key)
    result = tool_schedule_job(
        owner_id=owner_id,
        name=req.name,
        message=req.message,
        interval_seconds=req.interval_seconds,
        lane=req.lane,
    )
    return result


@router.get("/cron/jobs")
def cron_list_endpoint(
    chat_id: str,
    username: str = "api_user",
    agent_key: str | None = None,
    include_disabled: bool = False,
    limit: int = 20,
    _ops=Depends(require_ops_auth),
):
    owner_id = resolve_owner_id(chat_id, username, agent_key)
    return tool_list_scheduled_jobs(
        owner_id=owner_id, include_disabled=include_disabled, limit=limit
    )


@router.post("/cron/jobs/{job_id}/disable")
def cron_disable_endpoint(
    job_id: int,
    chat_id: str,
    username: str = "api_user",
    agent_key: str | None = None,
    _ops=Depends(require_ops_auth),
):
    owner_id = resolve_owner_id(chat_id, username, agent_key)
    return tool_disable_scheduled_job(owner_id=owner_id, job_id=job_id)


@router.get("/ui", include_in_schema=False)
@router.get("/ui/", include_in_schema=False)
def ui_root():
    _, _, ready = ui_dist_ready()
    if not ready:
        return ui_not_built_response()
    entry = resolve_ui_asset_path("")
    if entry is None:
        return ui_not_built_response()
    return FileResponse(str(entry))


@router.get("/ui/{path:path}", include_in_schema=False)
def ui_assets(path: str):
    _, _, ready = ui_dist_ready()
    if not ready:
        return ui_not_built_response()

    asset = resolve_ui_asset_path(path)
    if asset is None:
        raise HTTPException(status_code=404, detail="UI asset not found.")
    return FileResponse(str(asset))


# ============================================================================
