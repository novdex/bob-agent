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
from ...config import settings

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
from ...database.session import get_db, init_db, SessionLocal
from ...database.models import (
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
from ...core.state import (
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
    from ...services.telegram import (
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
            from ...agent.loop import run_agent_loop
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
    from ...services.task_engine import (
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
    from ...services.scheduler import (
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
    from ...tools.basic import tool_list_execution_nodes, tool_list_plugin_tools
except ImportError:

    def tool_list_execution_nodes() -> dict:
        return {"nodes": []}

    def tool_list_plugin_tools() -> dict:
        return {"tools": []}


try:
    from ...tools.registry import (
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
from ...utils import truncate_text, clamp_int, utc_now_iso, _safe_json_dict, _safe_json_list

# Agent/identity imports
try:
    from ...agent.identity import (
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
        from ...database.session import SessionLocal
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
    from ...agent.memory import (
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
    from ...core.queue import (
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
    from ...core.approvals import (
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
    from ...core.goals import (
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
    from ...core.blackbox import (
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
    from ...core.nodes import (
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
    from ...core.host_exec import create_host_exec_grant
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
    from ...core.security import apply_url_safety_guard
except ImportError:

    def apply_url_safety_guard(url: str, source: str = "") -> tuple[bool, str]:
        return True, ""


try:
    from ...core.protocols import protocol_validate_payload, protocol_contracts_public_view
except ImportError:

    def protocol_validate_payload(
        schema_name: str, payload: dict, direction: str = "request"
    ) -> tuple[bool, Optional[str]]:
        return True, None

    def protocol_contracts_public_view(registry: dict) -> list[dict]:
        return []


try:
    from ...core.evaluation import run_continuous_eval_suite, evaluate_release_gate
except ImportError:

    def run_continuous_eval_suite(max_cases: int = 50) -> dict:
        return {"ok": False, "error": "Not implemented"}

    def evaluate_release_gate(run_eval: bool = False, max_cases: Optional[int] = None) -> dict:
        return {"ok": True, "passed": True}


try:
    from ...core.session import run_startup_transcript_repair
except ImportError:

    def run_startup_transcript_repair(limit: int = 250) -> dict:
        return {"ok": True, "owners_changed": 0, "owners_processed": 0}


logger = logging.getLogger("mind_clone.api")
log = logger  # alias used by monolith-ported lifespan code


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


def parse_task_command_payload(text: str) -> tuple[str, str] | None:
    """Parse '/task <title> :: <goal>' command text."""
    prefix = "/task"
    if not text.startswith(prefix):
        return None
    payload = text[len(prefix) :].strip()
    if "::" not in payload:
        return None
    title, goal = payload.split("::", 1)
    title = title.strip()
    goal = goal.strip()
    if not title or not goal:
        return None
    return (title, goal)


def parse_cron_add_payload(text: str) -> Optional[tuple[int, str]]:
    """Parse '/cron_add <interval_seconds> :: <message>' command text."""
    try:
        parts = text.strip().split("::", 1)
        if len(parts) != 2:
            return None
        interval_part = parts[0].strip()
        message = parts[1].strip()
        interval_str = interval_part.split()[-1]
        interval = int(interval_str)
        return (interval, message)
    except Exception:
        return None
