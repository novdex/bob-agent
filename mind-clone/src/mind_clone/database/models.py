"""
Database models for Mind Clone Agent.

SQLAlchemy ORM models for users, conversations, tasks, memory, and more.
"""

from __future__ import annotations

from datetime import datetime
import uuid
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Text, LargeBinary, Boolean, Float, func
)
from sqlalchemy.ext.mutable import MutableList, MutableDict
from sqlalchemy.types import JSON
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    """User entity representing a human owner."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    telegram_chat_id = Column(String, unique=True, index=True, nullable=True)
    meta_json = Column(Text, nullable=True, default=None)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TeamAgent(Base):
    """Team agent for multi-agent mode."""
    __tablename__ = "team_agents"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    agent_owner_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True, nullable=False)
    agent_key = Column(String, index=True, nullable=False)
    display_name = Column(String, nullable=False, default="agent")
    workspace_root = Column(String, nullable=False)
    status = Column(String, index=True, nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)


class IdentityLink(Base):
    """Links multiple chat IDs to a canonical owner identity."""
    __tablename__ = "identity_links"

    id = Column(Integer, primary_key=True, index=True)
    canonical_owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    linked_chat_id = Column(String, unique=True, index=True, nullable=False)
    linked_username = Column(String, index=True, nullable=True)
    scope_mode = Column(String, index=True, nullable=False, default="linked_explicit")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HostExecGrant(Base):
    """Grants for host command execution."""
    __tablename__ = "host_exec_grants"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    node_name = Column(String, index=True, nullable=False, default="local")
    command_prefix = Column(String, nullable=False, default="")
    status = Column(String, index=True, nullable=False, default="active")
    created_by = Column(String, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WorkflowProgram(Base):
    """Stored workflow programs."""
    __tablename__ = "workflow_programs"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    name = Column(String, index=True, nullable=False)
    body_text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SchemaMigration(Base):
    """Schema migration tracking."""
    __tablename__ = "schema_migrations"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(Integer, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    checksum = Column(String, nullable=True)
    applied_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class NodeRegistration(Base):
    """Remote execution node registrations."""
    __tablename__ = "node_registrations"

    id = Column(Integer, primary_key=True, index=True)
    node_name = Column(String, unique=True, index=True, nullable=False)
    base_url = Column(String, nullable=False)
    auth_token = Column(String, nullable=True)
    capabilities_json = Column(Text, nullable=False, default="[]")
    enabled = Column(Integer, nullable=False, default=1)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class NodeLease(Base):
    """Node capability leases."""
    __tablename__ = "node_leases"

    id = Column(Integer, primary_key=True, index=True)
    lease_token = Column(String, unique=True, index=True, nullable=False)
    node_name = Column(String, index=True, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    capability = Column(String, index=True, nullable=False, default="general")
    status = Column(String, index=True, nullable=False, default="active")
    expires_at = Column(DateTime(timezone=True), index=True, nullable=False)
    released_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IdentityKernel(Base):
    """Core identity for each agent owner."""
    __tablename__ = "identity_kernels"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True, nullable=False)
    agent_uuid = Column(String, unique=True, index=True, nullable=False)
    origin_statement = Column(Text, nullable=False)
    core_values = Column(MutableList.as_mutable(JSON), nullable=False)
    authority_bounds = Column(MutableDict.as_mutable(JSON), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ConversationMessage(Base):
    """Persistent conversation memory per user."""
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    role = Column(String, nullable=False)  # "user", "assistant", "tool"
    content = Column(Text, nullable=True)
    tool_call_id = Column(String, nullable=True)
    tool_calls_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ConversationSummary(Base):
    """Compacted episodic summaries of older conversation chunks."""
    __tablename__ = "conversation_summaries"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    start_message_id = Column(Integer, nullable=False)
    end_message_id = Column(Integer, nullable=False)
    summary = Column(Text, nullable=False)
    key_points_json = Column(Text, nullable=False, default="[]")
    open_loops_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Task(Base):
    """Autonomous task tracking."""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, index=True, nullable=False)
    agent_uuid = Column(String, index=True, nullable=False, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    status = Column(String, index=True, nullable=False, default="open")
    plan = Column(MutableList.as_mutable(JSON), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TaskDeadLetter(Base):
    """Failed task records for debugging."""
    __tablename__ = "task_dead_letters"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, index=True, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    title = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    snapshot_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TaskArtifact(Base):
    """Artifacts from completed task steps."""
    __tablename__ = "task_artifacts"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    task_id = Column(Integer, index=True, nullable=False)
    step_id = Column(String, index=True, nullable=False)
    node_title = Column(String, nullable=False)
    task_title = Column(String, nullable=False)
    task_goal = Column(Text, nullable=False)
    status = Column(String, index=True, nullable=False)
    outcome_summary = Column(Text, nullable=False)
    tool_names_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ApprovalRequest(Base):
    """Pending approval requests for sensitive operations."""
    __tablename__ = "approval_requests"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    token = Column(String, unique=True, index=True, nullable=False)
    source_type = Column(String, index=True, nullable=False)
    source_ref = Column(String, nullable=True)
    step_id = Column(String, nullable=True)
    tool_name = Column(String, index=True, nullable=False)
    tool_args_json = Column(Text, nullable=False, default="{}")
    resume_payload_json = Column(Text, nullable=False, default="{}")
    status = Column(String, index=True, nullable=False, default="pending")
    decision_reason = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ScheduledJob(Base):
    """Cron-like scheduled jobs."""
    __tablename__ = "scheduled_jobs"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    lane = Column(String, nullable=False, default="cron")
    interval_seconds = Column(Integer, nullable=False, default=300)
    enabled = Column(Boolean, nullable=False, default=True)
    run_count = Column(Integer, nullable=False, default=0)
    run_at_time = Column(String, nullable=True)
    next_run_at = Column(DateTime(timezone=True), index=True, nullable=False)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TaskCheckpointSnapshot(Base):
    """Deterministic task checkpoint snapshots."""
    __tablename__ = "task_checkpoint_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, index=True, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    task_status = Column(String, index=True, nullable=False)
    source = Column(String, index=True, nullable=False, default="runtime")
    plan_json = Column(Text, nullable=False, default="[]")
    extra_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UsageLedger(Base):
    """Usage and cost tracking."""
    __tablename__ = "usage_ledger"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    task_id = Column(Integer, index=True, nullable=True)
    session_id = Column(String, index=True, nullable=True)
    source_type = Column(String, index=True, nullable=False, default="system")
    event_type = Column(String, index=True, nullable=False)
    model_name = Column(String, index=True, nullable=True)
    tool_name = Column(String, index=True, nullable=True)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    estimated_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost_usd = Column(String, nullable=False, default="0")
    status = Column(String, index=True, nullable=False, default="ok")
    detail_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ResearchNote(Base):
    """Research notes with sources and tags."""
    __tablename__ = "research_notes"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    topic = Column(String, index=True, nullable=False)
    summary = Column(Text, nullable=False)
    sources_json = Column(Text, nullable=False, default="[]")
    tags_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ActionForecast(Base):
    """World model action forecasts."""
    __tablename__ = "action_forecasts"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    context_type = Column(String, index=True, nullable=False, default="task_step")
    context_ref = Column(String, index=True, nullable=True)
    action_summary = Column(Text, nullable=False)
    pattern_tag = Column(String, index=True, nullable=True)
    predicted_outcome = Column(Text, nullable=False)
    predicted_risks_json = Column(Text, nullable=False, default="[]")
    confidence = Column(Integer, nullable=False, default=50)
    status = Column(String, index=True, nullable=False, default="pending")
    observed_outcome = Column(Text, nullable=True)
    observed_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class SelfImprovementNote(Base):
    """Self-improvement notes extracted from execution."""
    __tablename__ = "self_improvement_notes"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    actions_json = Column(Text, nullable=False, default="[]")
    evidence_json = Column(Text, nullable=False, default="{}")
    priority = Column(String, index=True, nullable=False, default="medium")
    status = Column(String, index=True, nullable=False, default="open")
    importance = Column(Float, nullable=False, default=1.0)   # Ebbinghaus weight
    recall_count = Column(Integer, nullable=False, default=0)
    last_recalled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Goal(Base):
    """High-level goals for autonomous planning."""
    __tablename__ = "goals"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    success_criteria = Column(Text, nullable=True)
    status = Column(String, index=True, nullable=False, default="active")
    progress_pct = Column(Integer, nullable=False, default=0)
    priority = Column(String, nullable=False, default="medium")
    deadline = Column(DateTime(timezone=True), nullable=True)
    task_ids_json = Column(Text, nullable=False, default="[]")
    milestones_json = Column(Text, nullable=False, default="[]")
    notes_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class EpisodicMemory(Base):
    """Episodic memory of past situations and outcomes."""
    __tablename__ = "episodic_memories"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    situation = Column(Text, nullable=False)
    action_taken = Column(Text, nullable=False)
    outcome = Column(String, index=True, nullable=False, default="success")
    outcome_detail = Column(Text, nullable=True)
    tools_used_json = Column(Text, nullable=False, default="[]")
    source_type = Column(String, index=True, nullable=False, default="chat")
    source_ref = Column(String, nullable=True)
    importance = Column(Float, nullable=False, default=1.0)   # Ebbinghaus weight (0.0–1.0)
    recall_count = Column(Integer, nullable=False, default=0)  # how many times recalled
    last_recalled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ToolPerformanceLog(Base):
    """Performance tracking for tools."""
    __tablename__ = "tool_performance_logs"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    tool_name = Column(String, index=True, nullable=False)
    source_type = Column(String, index=True, nullable=False, default="chat")
    success = Column(Integer, nullable=False, default=1)
    duration_ms = Column(Integer, nullable=False, default=0)
    error_category = Column(String, index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class GeneratedTool(Base):
    """Custom tools generated by the agent."""
    __tablename__ = "generated_tools"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    tool_name = Column(String, unique=True, index=True, nullable=False)
    description = Column(Text, nullable=False)
    parameters_json = Column(Text, nullable=False, default="{}")
    code = Column(Text, nullable=False)
    requirements = Column(Text, nullable=True)
    enabled = Column(Integer, nullable=False, default=1)
    test_passed = Column(Integer, nullable=False, default=0)
    usage_count = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CapabilityActivation(Base):
    """Dormant capability activations."""
    __tablename__ = "capability_activations"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    capability = Column(String, index=True, nullable=False)
    state = Column(String, index=True, nullable=False, default="active")
    trigger_text = Column(Text, nullable=True)
    reason = Column(Text, nullable=False)
    score = Column(Integer, nullable=False, default=0)
    activated_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ExecutionEvent(Base):
    """Blackbox execution events."""
    __tablename__ = "execution_events"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    session_id = Column(String, index=True, nullable=False)
    source_type = Column(String, index=True, nullable=False)
    source_ref = Column(String, index=True, nullable=True)
    event_type = Column(String, index=True, nullable=False)
    payload_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MemoryLink(Base):
    """Graph edges linking memory nodes together (A-MEM / MAGMA style).

    Connects any memory node (ResearchNote, EpisodicMemory, SelfImprovementNote, SkillProfile)
    to another. Enables Zettelkasten-style knowledge graph traversal.
    """
    __tablename__ = "memory_links"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    # Source node
    src_type = Column(String, index=True, nullable=False)   # research_note | episodic | improvement | skill
    src_id = Column(Integer, index=True, nullable=False)
    # Target node
    tgt_type = Column(String, index=True, nullable=False)
    tgt_id = Column(Integer, index=True, nullable=False)
    # Relationship
    relation = Column(String, index=True, nullable=False, default="related")  # related | supports | contradicts | evolved_from | caused_by
    weight = Column(Float, nullable=False, default=1.0)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MemoryVector(Base):
    """Vector embeddings for semantic memory search."""
    __tablename__ = "memory_vectors"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    memory_type = Column(String, index=True, nullable=False)
    ref_id = Column(Integer, nullable=True)
    text_preview = Column(String(200), nullable=True)
    embedding = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OpsAuditEvent(Base):
    """Audit events for sensitive operations."""
    __tablename__ = "ops_audit_events"

    id = Column(Integer, primary_key=True, index=True)
    actor_role = Column(String, index=True, nullable=True)
    actor_ref = Column(String, nullable=True)
    action = Column(String, index=True, nullable=False)
    target = Column(String, nullable=True)
    status = Column(String, index=True, nullable=False, default="ok")
    detail_json = Column(Text, nullable=False, default="{}")
    prev_hash = Column(String, nullable=True)
    event_hash = Column(String, index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SkillProfile(Base):
    """Reusable skill definitions with versioning."""
    __tablename__ = "skill_profiles"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    skill_key = Column(String, index=True, nullable=False)
    title = Column(String, nullable=False)
    intent = Column(Text, nullable=True)
    intent_hash = Column(String, index=True, nullable=True)
    trigger_hints_json = Column(Text, nullable=False, default="[]")
    status = Column(String, index=True, nullable=False, default="active")
    active_version = Column(Integer, nullable=False, default=1)
    latest_version = Column(Integer, nullable=False, default=1)
    source_type = Column(String, nullable=False, default="manual")
    auto_created = Column(Boolean, nullable=False, default=False)
    usage_count = Column(Integer, nullable=False, default=0)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SkillVersion(Base):
    """Immutable skill version snapshots."""
    __tablename__ = "skill_versions"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    skill_id = Column(Integer, ForeignKey("skill_profiles.id"), index=True, nullable=False)
    version = Column(Integer, nullable=False)
    body_text = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=False, default="{}")
    artifact_path = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ExperimentLog(Base):
    """Karpathy-style self-improvement experiment audit trail."""
    __tablename__ = "experiment_logs"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    hypothesis_title = Column(String, nullable=False)
    target_file = Column(String, nullable=True)
    score_before = Column(Float, nullable=False, default=0.0)
    score_after = Column(Float, nullable=False, default=0.0)
    improved = Column(Boolean, nullable=False, default=False)
    committed = Column(Boolean, nullable=False, default=False)
    reverted = Column(Boolean, nullable=False, default=False)
    tests_passed = Column(Boolean, nullable=False, default=False)
    error_msg = Column(Text, nullable=True)
    hypothesis_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SkillRun(Base):
    """Skill execution audit trail."""
    __tablename__ = "skill_runs"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    skill_id = Column(Integer, ForeignKey("skill_profiles.id"), index=True, nullable=False)
    skill_version = Column(Integer, nullable=False)
    session_id = Column(String, index=True, nullable=True)
    source_type = Column(String, index=True, nullable=False, default="chat")
    status = Column(String, index=True, nullable=False, default="invoked")
    message_preview = Column(Text, nullable=True)
    output_preview = Column(Text, nullable=True)
    error_preview = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# Export all models
__all__ = [
    "Base",
    "User",
    "TeamAgent",
    "IdentityLink",
    "HostExecGrant",
    "WorkflowProgram",
    "SchemaMigration",
    "NodeRegistration",
    "NodeLease",
    "IdentityKernel",
    "ConversationMessage",
    "ConversationSummary",
    "Task",
    "TaskDeadLetter",
    "TaskArtifact",
    "ApprovalRequest",
    "ScheduledJob",
    "TaskCheckpointSnapshot",
    "UsageLedger",
    "ResearchNote",
    "ActionForecast",
    "SelfImprovementNote",
    "Goal",
    "EpisodicMemory",
    "ToolPerformanceLog",
    "GeneratedTool",
    "CapabilityActivation",
    "ExecutionEvent",
    "MemoryVector",
    "OpsAuditEvent",
    "MemoryLink",
    "ExperimentLog",
    "SkillProfile",
    "SkillVersion",
    "SkillRun",
]
