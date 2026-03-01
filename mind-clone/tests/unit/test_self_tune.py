"""
Tests for Self-Tuning Performance Engine (maps to Vending-Bench 2).

Covers: queue mode tuning, session budget tuning, worker scaling,
        budget mode tuning, master entry point, hysteresis counters.
"""

import pytest
from unittest.mock import patch, MagicMock

from mind_clone.core.self_tune import (
    st_tune_queue_mode,
    st_tune_session_budget,
    st_tune_workers,
    st_tune_budget_mode,
    st_self_tune,
)
from mind_clone.core.state import RUNTIME_STATE
import mind_clone.core.self_tune as _st_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_runtime_keys():
    """Clear all self-tune related keys from RUNTIME_STATE."""
    keys_to_clear = [
        "command_queue_enqueued", "command_queue_processed",
        "command_queue_mode", "command_queue_size",
        "command_queue_worker_alive_count",
        "session_compaction_by_chars",
        "budget_runs_degraded", "budget_governor_mode",
        "heartbeat_ticks_total",
        "st_queue_mode_switches", "st_session_budget_adjustments",
        "st_current_session_soft_budget", "st_current_session_hard_budget",
        "st_worker_scale_events", "st_current_worker_count",
        "st_budget_mode_switches", "st_tunes_total", "st_last_tune_at",
        "st_last_action",
    ]
    for k in keys_to_clear:
        RUNTIME_STATE.pop(k, None)


def _reset_hysteresis():
    """Reset module-level hysteresis counters."""
    _st_mod._st_prev_hard_clears = 0
    _st_mod._st_zero_backlog_ticks = 0
    _st_mod._st_zero_hard_clear_ticks = 0
    _st_mod._st_zero_queue_ticks = 0
    _st_mod._st_zero_degraded_ticks = 0
    _st_mod._st_prev_degraded = 0


# ---------------------------------------------------------------------------
# Tuner 1: Queue mode
# ---------------------------------------------------------------------------

class TestTuneQueueMode:
    """Maps to Vending-Bench — tests that Bob auto-adapts queue mode."""

    def setup_method(self):
        _reset_runtime_keys()
        _reset_hysteresis()

    def test_no_backlog_no_change(self):
        RUNTIME_STATE["command_queue_enqueued"] = 5
        RUNTIME_STATE["command_queue_processed"] = 5
        RUNTIME_STATE["command_queue_mode"] = "on"
        actions = st_tune_queue_mode()
        assert actions == []
        assert RUNTIME_STATE["command_queue_mode"] == "on"

    def test_backlog_below_threshold_no_change(self):
        RUNTIME_STATE["command_queue_enqueued"] = 15
        RUNTIME_STATE["command_queue_processed"] = 10
        RUNTIME_STATE["command_queue_mode"] = "on"
        actions = st_tune_queue_mode()
        assert actions == []

    def test_backlog_over_threshold_switches_to_auto(self):
        RUNTIME_STATE["command_queue_enqueued"] = 20
        RUNTIME_STATE["command_queue_processed"] = 5
        RUNTIME_STATE["command_queue_mode"] = "on"
        actions = st_tune_queue_mode()
        assert len(actions) == 1
        assert "on->auto" in actions[0]
        assert RUNTIME_STATE["command_queue_mode"] == "auto"
        assert int(RUNTIME_STATE.get("st_queue_mode_switches", 0)) == 1

    def test_already_auto_no_switch(self):
        RUNTIME_STATE["command_queue_enqueued"] = 20
        RUNTIME_STATE["command_queue_processed"] = 5
        RUNTIME_STATE["command_queue_mode"] = "auto"
        actions = st_tune_queue_mode()
        assert actions == []

    def test_effective_threshold_minimum_10(self):
        """Even if config says 3, effective threshold is max(10, 3) = 10."""
        RUNTIME_STATE["command_queue_enqueued"] = 12
        RUNTIME_STATE["command_queue_processed"] = 0
        RUNTIME_STATE["command_queue_mode"] = "on"
        actions = st_tune_queue_mode()
        assert len(actions) == 1
        assert RUNTIME_STATE["command_queue_mode"] == "auto"

    def test_zero_backlog_increments_counter(self):
        RUNTIME_STATE["command_queue_enqueued"] = 0
        RUNTIME_STATE["command_queue_processed"] = 0
        RUNTIME_STATE["command_queue_mode"] = "on"
        st_tune_queue_mode()
        assert _st_mod._st_zero_backlog_ticks == 1
        st_tune_queue_mode()
        assert _st_mod._st_zero_backlog_ticks == 2


# ---------------------------------------------------------------------------
# Tuner 2: Session budget
# ---------------------------------------------------------------------------

class TestTuneSessionBudget:
    """Tests context budget auto-adjustment (maps to Context-Bench)."""

    def setup_method(self):
        _reset_runtime_keys()
        _reset_hysteresis()

    @patch("mind_clone.core.self_tune._cfg")
    def test_high_compaction_raises_budget(self, mock_cfg):
        mock_cfg.SESSION_SOFT_TRIM_CHAR_BUDGET = 42000
        mock_cfg.SESSION_HARD_CLEAR_CHAR_BUDGET = 50000
        mock_cfg.SELF_TUNE_SESSION_BUDGET_MAX = 80000
        # hasattr check
        type(mock_cfg).SESSION_SOFT_TRIM_CHAR_BUDGET = 42000
        type(mock_cfg).SESSION_HARD_CLEAR_CHAR_BUDGET = 50000

        # First call establishes baseline
        RUNTIME_STATE["session_compaction_by_chars"] = 0
        st_tune_session_budget()

        # Second call with delta >= threshold (5)
        RUNTIME_STATE["session_compaction_by_chars"] = 10
        actions = st_tune_session_budget()
        assert len(actions) >= 1
        assert "raised" in actions[0]

    def test_zero_compaction_no_immediate_change(self):
        RUNTIME_STATE["session_compaction_by_chars"] = 0
        actions = st_tune_session_budget()
        assert actions == []

    def test_hysteresis_counter_increments_on_zero_delta(self):
        RUNTIME_STATE["session_compaction_by_chars"] = 0
        _st_mod._st_prev_hard_clears = 0  # delta = 0
        st_tune_session_budget()
        assert _st_mod._st_zero_hard_clear_ticks == 1

    @patch("mind_clone.core.self_tune._cfg")
    def test_stable_10_ticks_lowers_budget(self, mock_cfg):
        mock_cfg.SESSION_SOFT_TRIM_CHAR_BUDGET = 50000
        mock_cfg.SESSION_HARD_CLEAR_CHAR_BUDGET = 58000
        mock_cfg.SELF_TUNE_SESSION_BUDGET_MIN = 20000
        type(mock_cfg).SESSION_SOFT_TRIM_CHAR_BUDGET = 50000
        type(mock_cfg).SESSION_HARD_CLEAR_CHAR_BUDGET = 58000

        RUNTIME_STATE["session_compaction_by_chars"] = 0
        _st_mod._st_prev_hard_clears = 0
        _st_mod._st_zero_hard_clear_ticks = 10  # At threshold

        actions = st_tune_session_budget()
        assert any("lowered" in a for a in actions)


# ---------------------------------------------------------------------------
# Tuner 3: Worker scaling
# ---------------------------------------------------------------------------

class TestTuneWorkers:
    """Tests queue worker auto-scaling."""

    def setup_method(self):
        _reset_runtime_keys()
        _reset_hysteresis()

    @patch("mind_clone.core.self_tune.command_queue_enabled", return_value=False)
    def test_queue_disabled_returns_empty(self, _):
        actions = st_tune_workers()
        assert actions == []

    @patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True)
    @patch("mind_clone.core.self_tune._cfg")
    def test_scale_up_when_queue_backlogged(self, mock_cfg, _):
        mock_cfg.COMMAND_QUEUE_WORKER_COUNT = 2
        mock_cfg.SELF_TUNE_WORKER_MAX = 6
        RUNTIME_STATE["command_queue_size"] = 10
        RUNTIME_STATE["command_queue_worker_alive_count"] = 2

        actions = st_tune_workers()
        assert len(actions) == 1
        assert "scaled" in actions[0]
        assert mock_cfg.COMMAND_QUEUE_WORKER_COUNT == 3

    @patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True)
    @patch("mind_clone.core.self_tune._cfg")
    def test_no_scale_up_at_max(self, mock_cfg, _):
        mock_cfg.COMMAND_QUEUE_WORKER_COUNT = 6
        mock_cfg.SELF_TUNE_WORKER_MAX = 6
        RUNTIME_STATE["command_queue_size"] = 10
        RUNTIME_STATE["command_queue_worker_alive_count"] = 6

        actions = st_tune_workers()
        assert actions == []

    @patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True)
    @patch("mind_clone.core.self_tune._cfg")
    def test_scale_down_after_10_idle_ticks(self, mock_cfg, _):
        mock_cfg.COMMAND_QUEUE_WORKER_COUNT = 4
        RUNTIME_STATE["command_queue_size"] = 0
        RUNTIME_STATE["command_queue_worker_alive_count"] = 4
        _st_mod._st_zero_queue_ticks = 10

        actions = st_tune_workers()
        assert len(actions) == 1
        assert "idle" in actions[0]
        assert mock_cfg.COMMAND_QUEUE_WORKER_COUNT == 3

    @patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True)
    @patch("mind_clone.core.self_tune._cfg")
    def test_no_scale_below_2(self, mock_cfg, _):
        mock_cfg.COMMAND_QUEUE_WORKER_COUNT = 2
        RUNTIME_STATE["command_queue_size"] = 0
        RUNTIME_STATE["command_queue_worker_alive_count"] = 2
        _st_mod._st_zero_queue_ticks = 10

        actions = st_tune_workers()
        assert actions == []  # Already at minimum

    @patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True)
    def test_zero_queue_increments_counter(self, _):
        RUNTIME_STATE["command_queue_size"] = 0
        RUNTIME_STATE["command_queue_worker_alive_count"] = 2
        st_tune_workers()
        assert _st_mod._st_zero_queue_ticks == 1


# ---------------------------------------------------------------------------
# Tuner 4: Budget mode
# ---------------------------------------------------------------------------

class TestTuneBudgetMode:
    """Tests budget governor auto-loosening/tightening."""

    def setup_method(self):
        _reset_runtime_keys()
        _reset_hysteresis()

    @patch("mind_clone.core.self_tune._cfg")
    def test_high_degradation_loosens_budget(self, mock_cfg):
        RUNTIME_STATE["budget_runs_degraded"] = 5
        RUNTIME_STATE["budget_governor_mode"] = "degrade"
        _st_mod._st_prev_degraded = 0  # delta = 5 > 3

        actions = st_tune_budget_mode()
        assert len(actions) == 1
        assert "degrade->warn" in actions[0]
        assert mock_cfg.BUDGET_GOVERNOR_MODE == "warn"
        assert RUNTIME_STATE["budget_governor_mode"] == "warn"

    @patch("mind_clone.core.self_tune._cfg")
    def test_already_warn_no_double_loosen(self, mock_cfg):
        RUNTIME_STATE["budget_runs_degraded"] = 5
        RUNTIME_STATE["budget_governor_mode"] = "warn"
        _st_mod._st_prev_degraded = 0

        actions = st_tune_budget_mode()
        assert actions == []

    @patch("mind_clone.core.self_tune._cfg")
    def test_stable_20_ticks_tightens_budget(self, mock_cfg):
        RUNTIME_STATE["budget_runs_degraded"] = 0
        RUNTIME_STATE["budget_governor_mode"] = "warn"
        _st_mod._st_prev_degraded = 0
        _st_mod._st_zero_degraded_ticks = 20

        actions = st_tune_budget_mode()
        assert len(actions) == 1
        assert "warn->degrade" in actions[0]
        assert mock_cfg.BUDGET_GOVERNOR_MODE == "degrade"

    def test_zero_delta_increments_counter(self):
        RUNTIME_STATE["budget_runs_degraded"] = 0
        _st_mod._st_prev_degraded = 0
        st_tune_budget_mode()
        assert _st_mod._st_zero_degraded_ticks == 1

    def test_nonzero_delta_below_threshold_resets_counter(self):
        RUNTIME_STATE["budget_runs_degraded"] = 2
        RUNTIME_STATE["budget_governor_mode"] = "degrade"
        _st_mod._st_prev_degraded = 0
        _st_mod._st_zero_degraded_ticks = 15

        st_tune_budget_mode()
        assert _st_mod._st_zero_degraded_ticks == 0


# ---------------------------------------------------------------------------
# Master entry point
# ---------------------------------------------------------------------------

class TestSelfTuneEntryPoint:
    """Tests the st_self_tune() master function."""

    def setup_method(self):
        _reset_runtime_keys()
        _reset_hysteresis()

    @patch("mind_clone.core.self_tune.SELF_TUNE_ENABLED", False)
    def test_disabled_exits_immediately(self):
        RUNTIME_STATE["heartbeat_ticks_total"] = 2
        st_self_tune()
        assert RUNTIME_STATE.get("st_tunes_total") is None

    @patch("mind_clone.core.self_tune.SELF_TUNE_ENABLED", True)
    @patch("mind_clone.core.self_tune.SELF_TUNE_INTERVAL_TICKS", 2)
    def test_wrong_tick_skips(self):
        RUNTIME_STATE["heartbeat_ticks_total"] = 3  # 3 % 2 != 0
        st_self_tune()
        assert RUNTIME_STATE.get("st_tunes_total") is None

    @patch("mind_clone.core.self_tune.SELF_TUNE_ENABLED", True)
    @patch("mind_clone.core.self_tune.SELF_TUNE_INTERVAL_TICKS", 2)
    def test_tick_zero_skips(self):
        RUNTIME_STATE["heartbeat_ticks_total"] = 0
        st_self_tune()
        assert RUNTIME_STATE.get("st_tunes_total") is None

    @patch("mind_clone.core.self_tune.SELF_TUNE_ENABLED", True)
    @patch("mind_clone.core.self_tune.SELF_TUNE_INTERVAL_TICKS", 2)
    @patch("mind_clone.core.self_tune.st_tune_queue_mode", return_value=[])
    @patch("mind_clone.core.self_tune.st_tune_session_budget", return_value=[])
    @patch("mind_clone.core.self_tune.st_tune_workers", return_value=[])
    @patch("mind_clone.core.self_tune.st_tune_budget_mode", return_value=[])
    def test_correct_tick_runs_all_tuners(self, *mocks):
        RUNTIME_STATE["heartbeat_ticks_total"] = 4  # 4 % 2 == 0
        st_self_tune()
        assert int(RUNTIME_STATE.get("st_tunes_total", 0)) == 1
        assert RUNTIME_STATE.get("st_last_tune_at") is not None
        for mock in mocks:
            mock.assert_called_once()

    @patch("mind_clone.core.self_tune.SELF_TUNE_ENABLED", True)
    @patch("mind_clone.core.self_tune.SELF_TUNE_INTERVAL_TICKS", 2)
    @patch("mind_clone.core.self_tune.st_tune_queue_mode", return_value=["action_a"])
    @patch("mind_clone.core.self_tune.st_tune_session_budget", return_value=["action_b"])
    @patch("mind_clone.core.self_tune.st_tune_workers", return_value=[])
    @patch("mind_clone.core.self_tune.st_tune_budget_mode", return_value=[])
    def test_actions_aggregated_in_last_action(self, *_):
        RUNTIME_STATE["heartbeat_ticks_total"] = 2
        st_self_tune()
        last_action = RUNTIME_STATE.get("st_last_action", "")
        assert "action_a" in last_action
        assert "action_b" in last_action

    @patch("mind_clone.core.self_tune.SELF_TUNE_ENABLED", True)
    @patch("mind_clone.core.self_tune.SELF_TUNE_INTERVAL_TICKS", 2)
    @patch("mind_clone.core.self_tune.st_tune_queue_mode", side_effect=Exception("boom"))
    def test_exception_in_tuner_does_not_crash(self, _):
        RUNTIME_STATE["heartbeat_ticks_total"] = 2
        st_self_tune()  # Should not raise
        assert int(RUNTIME_STATE.get("st_tunes_total", 0)) == 1
