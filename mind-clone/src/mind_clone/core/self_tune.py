"""
Self-Tuning Performance Engine (Section 5C).

Makes Bob detect and fix his own performance problems automatically.
Feature-flagged with SELF_TUNE_ENABLED (default: True).

Four auto-tuners run every ~90s via heartbeat:
  Queue   - st_tune_queue_mode    - Switches queue on->auto when backlog builds
  Session - st_tune_session_budget - Raises/lowers context char budgets
  Workers - st_tune_workers       - Scales queue workers up/down
  Budget  - st_tune_budget_mode   - Loosens budget governor when too many runs degraded

Serves Pillar 3 (Autonomy), Pillar 4 (Learning), Pillar 6 (Self-Awareness).
"""

from __future__ import annotations

import logging

from ..config import (
    SELF_TUNE_ENABLED,
    SELF_TUNE_INTERVAL_TICKS,
    SELF_TUNE_QUEUE_BACKLOG_THRESHOLD,
    SELF_TUNE_HARD_CLEAR_RATE_THRESHOLD,
    SELF_TUNE_SESSION_BUDGET_STEP,
    SELF_TUNE_SESSION_BUDGET_MAX,
    SELF_TUNE_SESSION_BUDGET_MIN,
    SELF_TUNE_WORKER_MAX,
    COMMAND_QUEUE_MODE,
    COMMAND_QUEUE_WORKER_COUNT,
    BUDGET_GOVERNOR_MODE,
)
from ..core.state import RUNTIME_STATE
from ..core.queue import command_queue_enabled
from ..utils import utc_now_iso

log = logging.getLogger("mind_clone")

# ---------------------------------------------------------------------------
# Mutable module-level config that the tuners adjust at runtime.
# Imported by name from config.py then mutated here.
# ---------------------------------------------------------------------------
import mind_clone.config as _cfg

# ---------------------------------------------------------------------------
# Module state - consecutive-tick counters for hysteresis
# ---------------------------------------------------------------------------
_st_prev_hard_clears: int = 0       # snapshot for compaction rate detection
_st_zero_backlog_ticks: int = 0     # consecutive ticks with zero backlog
_st_zero_hard_clear_ticks: int = 0  # consecutive ticks with zero compaction increase
_st_zero_queue_ticks: int = 0       # consecutive ticks with empty queue
_st_zero_degraded_ticks: int = 0    # consecutive ticks with zero degradation increase
_st_prev_degraded: int = 0          # snapshot for rate detection


# ---------------------------------------------------------------------------
# Tuner 1: Queue mode
# ---------------------------------------------------------------------------

def st_tune_queue_mode() -> list[str]:
    """Tune queue mode based on backlog. Switch to 'auto' if backlog builds up."""
    global _st_zero_backlog_ticks
    actions: list[str] = []
    enqueued = int(RUNTIME_STATE.get("command_queue_enqueued", 0))
    processed = int(RUNTIME_STATE.get("command_queue_processed", 0))
    backlog = max(0, enqueued - processed)
    current_mode = str(RUNTIME_STATE.get("command_queue_mode", COMMAND_QUEUE_MODE)).lower()

    effective_threshold = max(10, SELF_TUNE_QUEUE_BACKLOG_THRESHOLD)
    if backlog >= effective_threshold and current_mode == "on":
        RUNTIME_STATE["command_queue_mode"] = "auto"
        RUNTIME_STATE["st_queue_mode_switches"] = int(RUNTIME_STATE.get("st_queue_mode_switches", 0)) + 1
        _st_zero_backlog_ticks = 0
        actions.append(f"queue_mode on->auto (backlog={backlog})")
        log.info("ST_QUEUE_MODE on->auto backlog=%d threshold=%d", backlog, effective_threshold)
    elif backlog == 0:
        _st_zero_backlog_ticks += 1
    else:
        _st_zero_backlog_ticks = 0

    return actions


# ---------------------------------------------------------------------------
# Tuner 2: Session budget
# ---------------------------------------------------------------------------

def st_tune_session_budget() -> list[str]:
    """Tune session char budgets based on compaction rate.

    With the OpenClaw-style unified context manager, hard clears no longer
    occur.  Instead we track ``session_compaction_by_chars`` - when compaction
    fires frequently, we raise budgets to reduce LLM summarisation cost.
    """
    global _st_prev_hard_clears, _st_zero_hard_clear_ticks
    actions: list[str] = []
    # Monitor compaction events (replaces old hard clear monitoring)
    current_hard_clears = int(RUNTIME_STATE.get("session_compaction_by_chars", 0))
    delta = current_hard_clears - _st_prev_hard_clears
    _st_prev_hard_clears = current_hard_clears

    if delta >= SELF_TUNE_HARD_CLEAR_RATE_THRESHOLD:
        _st_zero_hard_clear_ticks = 0
        old_soft = _cfg.SESSION_SOFT_TRIM_CHAR_BUDGET if hasattr(_cfg, "SESSION_SOFT_TRIM_CHAR_BUDGET") else _cfg.settings.session_soft_trim_char_budget
        old_hard = _cfg.SESSION_HARD_CLEAR_CHAR_BUDGET if hasattr(_cfg, "SESSION_HARD_CLEAR_CHAR_BUDGET") else old_soft + 8000
        new_soft = min(SELF_TUNE_SESSION_BUDGET_MAX, old_soft + SELF_TUNE_SESSION_BUDGET_STEP)
        new_hard = min(SELF_TUNE_SESSION_BUDGET_MAX - 8000, old_hard + SELF_TUNE_SESSION_BUDGET_STEP)
        if new_soft != old_soft or new_hard != old_hard:
            if hasattr(_cfg, "SESSION_SOFT_TRIM_CHAR_BUDGET"):
                _cfg.SESSION_SOFT_TRIM_CHAR_BUDGET = new_soft
            if hasattr(_cfg, "SESSION_HARD_CLEAR_CHAR_BUDGET"):
                _cfg.SESSION_HARD_CLEAR_CHAR_BUDGET = new_hard
            RUNTIME_STATE["st_current_session_soft_budget"] = new_soft
            RUNTIME_STATE["st_current_session_hard_budget"] = new_hard
            RUNTIME_STATE["st_session_budget_adjustments"] = int(RUNTIME_STATE.get("st_session_budget_adjustments", 0)) + 1
            actions.append(f"session_budget raised soft={old_soft}->{new_soft} hard={old_hard}->{new_hard}")
            log.info(
                "ST_SESSION_BUDGET_RAISE soft=%d->%d hard=%d->%d delta_clears=%d",
                old_soft, new_soft, old_hard, new_hard, delta,
            )
    elif delta == 0:
        _st_zero_hard_clear_ticks += 1
        if _st_zero_hard_clear_ticks >= 10:
            old_soft = _cfg.SESSION_SOFT_TRIM_CHAR_BUDGET if hasattr(_cfg, "SESSION_SOFT_TRIM_CHAR_BUDGET") else _cfg.settings.session_soft_trim_char_budget
            old_hard = _cfg.SESSION_HARD_CLEAR_CHAR_BUDGET if hasattr(_cfg, "SESSION_HARD_CLEAR_CHAR_BUDGET") else old_soft + 8000
            new_soft = max(SELF_TUNE_SESSION_BUDGET_MIN, old_soft - SELF_TUNE_SESSION_BUDGET_STEP)
            new_hard = max(SELF_TUNE_SESSION_BUDGET_MIN, old_hard - SELF_TUNE_SESSION_BUDGET_STEP)
            if new_soft != old_soft or new_hard != old_hard:
                if hasattr(_cfg, "SESSION_SOFT_TRIM_CHAR_BUDGET"):
                    _cfg.SESSION_SOFT_TRIM_CHAR_BUDGET = new_soft
                if hasattr(_cfg, "SESSION_HARD_CLEAR_CHAR_BUDGET"):
                    _cfg.SESSION_HARD_CLEAR_CHAR_BUDGET = new_hard
                RUNTIME_STATE["st_current_session_soft_budget"] = new_soft
                RUNTIME_STATE["st_current_session_hard_budget"] = new_hard
                RUNTIME_STATE["st_session_budget_adjustments"] = int(RUNTIME_STATE.get("st_session_budget_adjustments", 0)) + 1
                _st_zero_hard_clear_ticks = 0
                actions.append(f"session_budget lowered soft={old_soft}->{new_soft} hard={old_hard}->{new_hard}")
                log.info(
                    "ST_SESSION_BUDGET_LOWER soft=%d->%d hard=%d->%d stable_ticks=10",
                    old_soft, new_soft, old_hard, new_hard,
                )
    else:
        _st_zero_hard_clear_ticks = 0

    return actions


# ---------------------------------------------------------------------------
# Tuner 3: Worker scaling
# ---------------------------------------------------------------------------

def st_tune_workers() -> list[str]:
    """Scale queue workers up/down based on queue depth."""
    global _st_zero_queue_ticks
    actions: list[str] = []
    if not command_queue_enabled():
        return actions

    queue_size = int(RUNTIME_STATE.get("command_queue_size", 0))
    alive = int(RUNTIME_STATE.get("command_queue_worker_alive_count", 0))

    current_worker_count = _cfg.COMMAND_QUEUE_WORKER_COUNT

    if queue_size > 5 and alive < SELF_TUNE_WORKER_MAX:
        old_count = current_worker_count
        new_count = min(SELF_TUNE_WORKER_MAX, old_count + 1)
        _cfg.COMMAND_QUEUE_WORKER_COUNT = new_count
        RUNTIME_STATE["st_current_worker_count"] = new_count
        RUNTIME_STATE["st_worker_scale_events"] = int(RUNTIME_STATE.get("st_worker_scale_events", 0)) + 1
        _st_zero_queue_ticks = 0
        actions.append(f"workers scaled {old_count}->{new_count} (queue_size={queue_size})")
        log.info("ST_WORKER_SCALE_UP %d->%d queue_size=%d", old_count, new_count, queue_size)
    elif queue_size == 0:
        _st_zero_queue_ticks += 1
        if _st_zero_queue_ticks >= 10 and current_worker_count > 2:
            old_count = current_worker_count
            new_count = max(2, old_count - 1)
            _cfg.COMMAND_QUEUE_WORKER_COUNT = new_count
            RUNTIME_STATE["st_current_worker_count"] = new_count
            RUNTIME_STATE["st_worker_scale_events"] = int(RUNTIME_STATE.get("st_worker_scale_events", 0)) + 1
            _st_zero_queue_ticks = 0
            actions.append(f"workers scaled {old_count}->{new_count} (idle)")
            log.info("ST_WORKER_SCALE_DOWN %d->%d idle_ticks=10", old_count, new_count)
    else:
        _st_zero_queue_ticks = 0

    return actions


# ---------------------------------------------------------------------------
# Tuner 4: Budget mode
# ---------------------------------------------------------------------------

def st_tune_budget_mode() -> list[str]:
    """Loosen budget governor when too many runs get degraded."""
    global _st_prev_degraded, _st_zero_degraded_ticks
    actions: list[str] = []
    current_degraded = int(RUNTIME_STATE.get("budget_runs_degraded", 0))
    delta = current_degraded - _st_prev_degraded
    _st_prev_degraded = current_degraded
    current_mode = str(RUNTIME_STATE.get("budget_governor_mode", BUDGET_GOVERNOR_MODE)).lower()

    if delta > 3 and current_mode == "degrade":
        _cfg.BUDGET_GOVERNOR_MODE = "warn"
        RUNTIME_STATE["budget_governor_mode"] = "warn"
        RUNTIME_STATE["st_budget_mode_switches"] = int(RUNTIME_STATE.get("st_budget_mode_switches", 0)) + 1
        _st_zero_degraded_ticks = 0
        actions.append(f"budget_mode degrade->warn (degraded_delta={delta})")
        log.info("ST_BUDGET_MODE degrade->warn degraded_delta=%d", delta)
    elif delta == 0:
        _st_zero_degraded_ticks += 1
        if _st_zero_degraded_ticks >= 20 and current_mode == "warn":
            _cfg.BUDGET_GOVERNOR_MODE = "degrade"
            RUNTIME_STATE["budget_governor_mode"] = "degrade"
            RUNTIME_STATE["st_budget_mode_switches"] = int(RUNTIME_STATE.get("st_budget_mode_switches", 0)) + 1
            _st_zero_degraded_ticks = 0
            actions.append("budget_mode warn->degrade (stable 20 ticks)")
            log.info("ST_BUDGET_MODE warn->degrade stable_ticks=20")
    else:
        _st_zero_degraded_ticks = 0

    return actions


# ---------------------------------------------------------------------------
# Master entry point (called from heartbeat)
# ---------------------------------------------------------------------------

def st_self_tune() -> None:
    """Section 5C: Self-Tuning Performance Engine. Called from heartbeat."""
    if not SELF_TUNE_ENABLED:
        return
    tick = int(RUNTIME_STATE.get("heartbeat_ticks_total", 0))
    if tick == 0 or tick % SELF_TUNE_INTERVAL_TICKS != 0:
        return

    actions: list[str] = []
    try:
        actions += st_tune_queue_mode()
        actions += st_tune_session_budget()
        actions += st_tune_workers()
        actions += st_tune_budget_mode()
    except Exception as e:
        log.debug("ST_SELF_TUNE_ERROR: %s", e)

    RUNTIME_STATE["st_tunes_total"] = int(RUNTIME_STATE.get("st_tunes_total", 0)) + 1
    RUNTIME_STATE["st_last_tune_at"] = utc_now_iso()
    if actions:
        RUNTIME_STATE["st_last_action"] = "; ".join(actions)
