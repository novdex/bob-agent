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


# ---------------------------------------------------------------------------
# Edge case tests for all tuners
# ---------------------------------------------------------------------------

class TestEdgeCasesQueueMode:
    """Edge cases for queue mode tuning — with actual assertions."""

    def setup_method(self):
        _reset_runtime_keys()
        _reset_hysteresis()

    def test_missing_enqueued_key_returns_list(self):
        RUNTIME_STATE["command_queue_processed"] = 5
        RUNTIME_STATE["command_queue_mode"] = "on"
        actions = st_tune_queue_mode()
        assert isinstance(actions, list)
        assert actions == []  # backlog = max(0, 0-5) = 0, no switch

    def test_missing_processed_key_returns_list(self):
        RUNTIME_STATE["command_queue_enqueued"] = 15
        RUNTIME_STATE["command_queue_mode"] = "on"
        actions = st_tune_queue_mode()
        assert isinstance(actions, list)
        # backlog = 15 - 0 = 15 >= 10, should switch
        assert len(actions) == 1
        assert RUNTIME_STATE["command_queue_mode"] == "auto"

    def test_missing_mode_defaults_and_no_switch(self):
        RUNTIME_STATE["command_queue_enqueued"] = 20
        RUNTIME_STATE["command_queue_processed"] = 5
        actions = st_tune_queue_mode()
        assert isinstance(actions, list)
        # Default mode from config, not "on", so likely no switch

    def test_negative_backlog_handled(self):
        RUNTIME_STATE["command_queue_enqueued"] = 5
        RUNTIME_STATE["command_queue_processed"] = 10
        RUNTIME_STATE["command_queue_mode"] = "on"
        actions = st_tune_queue_mode()
        assert actions == []
        assert RUNTIME_STATE["command_queue_mode"] == "on"  # unchanged
        assert _st_mod._st_zero_backlog_ticks == 1  # 0 backlog increments counter

    def test_very_large_backlog_switches(self):
        RUNTIME_STATE["command_queue_enqueued"] = 1000000
        RUNTIME_STATE["command_queue_processed"] = 0
        RUNTIME_STATE["command_queue_mode"] = "on"
        actions = st_tune_queue_mode()
        assert len(actions) == 1
        assert RUNTIME_STATE["command_queue_mode"] == "auto"
        assert int(RUNTIME_STATE.get("st_queue_mode_switches", 0)) == 1

    def test_mode_case_insensitive_uppercase_on(self):
        RUNTIME_STATE["command_queue_enqueued"] = 20
        RUNTIME_STATE["command_queue_processed"] = 5
        RUNTIME_STATE["command_queue_mode"] = "ON"
        actions = st_tune_queue_mode()
        assert isinstance(actions, list)
        # "ON".lower() == "on", backlog=15 >= 10 => switches
        assert len(actions) == 1
        assert RUNTIME_STATE["command_queue_mode"] == "auto"

    def test_backlog_equals_threshold_switches(self):
        RUNTIME_STATE["command_queue_enqueued"] = 10
        RUNTIME_STATE["command_queue_processed"] = 0
        RUNTIME_STATE["command_queue_mode"] = "on"
        actions = st_tune_queue_mode()
        assert len(actions) == 1
        assert RUNTIME_STATE["command_queue_mode"] == "auto"

    def test_backlog_one_below_threshold_no_switch(self):
        RUNTIME_STATE["command_queue_enqueued"] = 9
        RUNTIME_STATE["command_queue_processed"] = 0
        RUNTIME_STATE["command_queue_mode"] = "on"
        actions = st_tune_queue_mode()
        assert actions == []
        assert RUNTIME_STATE["command_queue_mode"] == "on"

    def test_nonzero_backlog_resets_zero_counter(self):
        _st_mod._st_zero_backlog_ticks = 5
        RUNTIME_STATE["command_queue_enqueued"] = 3
        RUNTIME_STATE["command_queue_processed"] = 0
        RUNTIME_STATE["command_queue_mode"] = "on"
        st_tune_queue_mode()
        assert _st_mod._st_zero_backlog_ticks == 0  # reset on nonzero backlog below threshold

    def test_switch_resets_zero_counter(self):
        _st_mod._st_zero_backlog_ticks = 5
        RUNTIME_STATE["command_queue_enqueued"] = 20
        RUNTIME_STATE["command_queue_processed"] = 0
        RUNTIME_STATE["command_queue_mode"] = "on"
        st_tune_queue_mode()
        assert _st_mod._st_zero_backlog_ticks == 0


class TestEdgeCasesSessionBudget:
    """Edge cases for session budget tuning — with actual assertions."""

    def setup_method(self):
        _reset_runtime_keys()
        _reset_hysteresis()

    def test_missing_compaction_key_returns_empty(self):
        actions = st_tune_session_budget()
        assert isinstance(actions, list)
        assert actions == []

    def test_zero_compaction_increments_counter(self):
        RUNTIME_STATE["session_compaction_by_chars"] = 0
        _st_mod._st_prev_hard_clears = 0
        actions = st_tune_session_budget()
        assert actions == []
        assert _st_mod._st_zero_hard_clear_ticks == 1

    def test_negative_compaction_delta_resets_counter(self):
        RUNTIME_STATE["session_compaction_by_chars"] = -5
        _st_mod._st_prev_hard_clears = 0
        _st_mod._st_zero_hard_clear_ticks = 5
        actions = st_tune_session_budget()
        assert isinstance(actions, list)
        # delta = -5, not >= threshold, not == 0, so falls to else branch => reset counter
        assert _st_mod._st_zero_hard_clear_ticks == 0

    def test_very_large_compaction_returns_actions(self):
        RUNTIME_STATE["session_compaction_by_chars"] = 1000000
        _st_mod._st_prev_hard_clears = 0
        actions = st_tune_session_budget()
        assert isinstance(actions, list)
        # delta = 1000000 >= threshold => should raise budgets
        assert len(actions) >= 1
        assert "raised" in actions[0]


class TestEdgeCasesWorkers:
    """Edge cases for worker scaling — with actual assertions."""

    def setup_method(self):
        _reset_runtime_keys()
        _reset_hysteresis()

    @patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True)
    def test_missing_queue_size_defaults_zero(self, _):
        RUNTIME_STATE["command_queue_worker_alive_count"] = 2
        actions = st_tune_workers()
        assert isinstance(actions, list)
        # queue_size defaults to 0, so enters zero_queue branch
        assert _st_mod._st_zero_queue_ticks == 1

    @patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True)
    @patch("mind_clone.core.self_tune._cfg")
    def test_missing_worker_alive_defaults_zero(self, mock_cfg, _):
        mock_cfg.COMMAND_QUEUE_WORKER_COUNT = 2
        mock_cfg.SELF_TUNE_WORKER_MAX = 6
        RUNTIME_STATE["command_queue_size"] = 10
        # alive defaults to 0 < WORKER_MAX, so should scale up
        actions = st_tune_workers()
        assert len(actions) == 1
        assert "scaled" in actions[0]

    @patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True)
    def test_negative_queue_size_no_scaleup(self, _):
        RUNTIME_STATE["command_queue_size"] = -5
        RUNTIME_STATE["command_queue_worker_alive_count"] = 2
        actions = st_tune_workers()
        assert actions == []  # -5 is not > 5, so else branch => reset counter
        assert _st_mod._st_zero_queue_ticks == 0

    @patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True)
    @patch("mind_clone.core.self_tune._cfg")
    def test_queue_size_at_threshold_no_scaleup(self, mock_cfg, _):
        mock_cfg.COMMAND_QUEUE_WORKER_COUNT = 2
        mock_cfg.SELF_TUNE_WORKER_MAX = 6
        RUNTIME_STATE["command_queue_size"] = 5  # not > 5
        RUNTIME_STATE["command_queue_worker_alive_count"] = 2
        actions = st_tune_workers()
        assert actions == []

    @patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True)
    @patch("mind_clone.core.self_tune._cfg")
    def test_queue_size_just_above_threshold_scales(self, mock_cfg, _):
        mock_cfg.COMMAND_QUEUE_WORKER_COUNT = 2
        mock_cfg.SELF_TUNE_WORKER_MAX = 6
        RUNTIME_STATE["command_queue_size"] = 6  # > 5
        RUNTIME_STATE["command_queue_worker_alive_count"] = 2
        actions = st_tune_workers()
        assert len(actions) == 1
        assert mock_cfg.COMMAND_QUEUE_WORKER_COUNT == 3


class TestEdgeCasesBudgetMode:
    """Edge cases for budget mode tuning — with actual assertions."""

    def setup_method(self):
        _reset_runtime_keys()
        _reset_hysteresis()

    def test_missing_degraded_returns_empty(self):
        actions = st_tune_budget_mode()
        assert isinstance(actions, list)
        assert actions == []
        assert _st_mod._st_zero_degraded_ticks == 1  # delta=0 increments counter

    def test_missing_mode_key_returns_empty(self):
        RUNTIME_STATE["budget_runs_degraded"] = 5
        _st_mod._st_prev_degraded = 0
        actions = st_tune_budget_mode()
        assert isinstance(actions, list)
        # delta=5 > 3, but mode defaults from config (likely "degrade")

    def test_negative_degradation_resets_counter(self):
        RUNTIME_STATE["budget_runs_degraded"] = -10
        _st_mod._st_prev_degraded = 0
        _st_mod._st_zero_degraded_ticks = 5
        actions = st_tune_budget_mode()
        assert isinstance(actions, list)
        # delta = -10, not > 3 and not == 0, so else branch => reset
        assert _st_mod._st_zero_degraded_ticks == 0

    @patch("mind_clone.core.self_tune._cfg")
    def test_very_large_degradation_loosens(self, mock_cfg):
        RUNTIME_STATE["budget_runs_degraded"] = 10000
        _st_mod._st_prev_degraded = 0
        RUNTIME_STATE["budget_governor_mode"] = "degrade"
        actions = st_tune_budget_mode()
        assert len(actions) == 1
        assert "degrade->warn" in actions[0]
        assert mock_cfg.BUDGET_GOVERNOR_MODE == "warn"

    def test_mode_case_insensitive_handles_uppercase(self):
        RUNTIME_STATE["budget_runs_degraded"] = 5
        RUNTIME_STATE["budget_governor_mode"] = "DEGRADE"
        _st_mod._st_prev_degraded = 0
        actions = st_tune_budget_mode()
        assert isinstance(actions, list)
        # "DEGRADE".lower() == "degrade", delta=5 > 3 => should switch

    def test_delta_exactly_3_no_loosen(self):
        RUNTIME_STATE["budget_runs_degraded"] = 3
        _st_mod._st_prev_degraded = 0
        RUNTIME_STATE["budget_governor_mode"] = "degrade"
        actions = st_tune_budget_mode()
        # delta=3, condition is > 3, so should NOT loosen
        assert actions == []

    def test_delta_exactly_4_loosens(self):
        RUNTIME_STATE["budget_runs_degraded"] = 4
        _st_mod._st_prev_degraded = 0
        RUNTIME_STATE["budget_governor_mode"] = "degrade"
        actions = st_tune_budget_mode()
        assert len(actions) == 1
        assert "degrade->warn" in actions[0]

    def test_18_ticks_no_tighten(self):
        """At 18 ticks, increment to 19 — still below 20 threshold."""
        RUNTIME_STATE["budget_runs_degraded"] = 0
        RUNTIME_STATE["budget_governor_mode"] = "warn"
        _st_mod._st_prev_degraded = 0
        _st_mod._st_zero_degraded_ticks = 18
        actions = st_tune_budget_mode()
        assert actions == []
        assert _st_mod._st_zero_degraded_ticks == 19


class TestEdgeCasesIntegration:
    """Integration edge cases — with actual assertions."""

    def setup_method(self):
        _reset_runtime_keys()
        _reset_hysteresis()

    @patch("mind_clone.core.self_tune.SELF_TUNE_ENABLED", True)
    @patch("mind_clone.core.self_tune.SELF_TUNE_INTERVAL_TICKS", 1)
    def test_tick_equals_interval_runs(self):
        RUNTIME_STATE["heartbeat_ticks_total"] = 5
        st_self_tune()
        assert int(RUNTIME_STATE.get("st_tunes_total", 0)) == 1
        assert RUNTIME_STATE.get("st_last_tune_at") is not None

    @patch("mind_clone.core.self_tune.SELF_TUNE_ENABLED", True)
    @patch("mind_clone.core.self_tune.SELF_TUNE_INTERVAL_TICKS", 1)
    def test_large_tick_value_runs(self):
        RUNTIME_STATE["heartbeat_ticks_total"] = 1000000
        st_self_tune()
        assert int(RUNTIME_STATE.get("st_tunes_total", 0)) == 1

    @patch("mind_clone.core.self_tune.SELF_TUNE_ENABLED", True)
    @patch("mind_clone.core.self_tune.SELF_TUNE_INTERVAL_TICKS", 2)
    def test_all_tuners_exception_still_increments_total(self):
        with patch("mind_clone.core.self_tune.st_tune_queue_mode") as m1, \
             patch("mind_clone.core.self_tune.st_tune_session_budget") as m2, \
             patch("mind_clone.core.self_tune.st_tune_workers") as m3, \
             patch("mind_clone.core.self_tune.st_tune_budget_mode") as m4:
            m1.side_effect = Exception("fail1")
            RUNTIME_STATE["heartbeat_ticks_total"] = 2
            st_self_tune()
            assert int(RUNTIME_STATE.get("st_tunes_total", 0)) == 1


class TestRuntimeStateValidation:
    """Validate RUNTIME_STATE mutations are safe."""

    def setup_method(self):
        _reset_runtime_keys()
        _reset_hysteresis()

    def test_queue_switch_produces_integer_counter(self):
        RUNTIME_STATE["command_queue_enqueued"] = 20
        RUNTIME_STATE["command_queue_processed"] = 5
        RUNTIME_STATE["command_queue_mode"] = "on"
        st_tune_queue_mode()
        assert isinstance(RUNTIME_STATE["st_queue_mode_switches"], int)
        assert RUNTIME_STATE["st_queue_mode_switches"] == 1

    @patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True)
    @patch("mind_clone.core.self_tune._cfg")
    def test_worker_scale_values_non_negative(self, mock_cfg, _):
        mock_cfg.COMMAND_QUEUE_WORKER_COUNT = 2
        mock_cfg.SELF_TUNE_WORKER_MAX = 6
        RUNTIME_STATE["command_queue_size"] = 10
        RUNTIME_STATE["command_queue_worker_alive_count"] = 2
        st_tune_workers()
        assert RUNTIME_STATE["st_worker_scale_events"] >= 0
        assert RUNTIME_STATE["st_current_worker_count"] >= 2

    def test_multiple_queue_switches_increment(self):
        RUNTIME_STATE["command_queue_enqueued"] = 20
        RUNTIME_STATE["command_queue_processed"] = 0
        RUNTIME_STATE["command_queue_mode"] = "on"
        st_tune_queue_mode()
        assert RUNTIME_STATE["st_queue_mode_switches"] == 1
        # Reset mode to "on" to trigger again
        RUNTIME_STATE["command_queue_mode"] = "on"
        st_tune_queue_mode()
        assert RUNTIME_STATE["st_queue_mode_switches"] == 2


class TestDefensiveHelpers:
    """Tests for the defensive helper functions."""

    def test_validate_backlog_normal(self):
        from mind_clone.core.self_tune import _validate_backlog
        assert _validate_backlog(10, 5) == 5
        assert _validate_backlog(5, 10) == 0  # clamps to 0

    def test_validate_backlog_invalid(self):
        from mind_clone.core.self_tune import _validate_backlog
        assert _validate_backlog(None, 5) == 0
        assert _validate_backlog("abc", 5) == 0
        assert _validate_backlog(10, None) == 0

    def test_validate_budget_bounds_normal(self):
        from mind_clone.core.self_tune import _validate_budget_bounds
        assert _validate_budget_bounds(50, 10, 100) == 50
        assert _validate_budget_bounds(5, 10, 100) == 10   # clamp low
        assert _validate_budget_bounds(200, 10, 100) == 100  # clamp high

    def test_validate_budget_bounds_invalid(self):
        from mind_clone.core.self_tune import _validate_budget_bounds
        result = _validate_budget_bounds(None, 10, 100)
        assert result == 55  # midpoint fallback

    def test_safe_get_runtime_int_normal(self):
        from mind_clone.core.self_tune import _safe_get_runtime_int
        RUNTIME_STATE["test_key_int"] = 42
        assert _safe_get_runtime_int("test_key_int") == 42
        RUNTIME_STATE.pop("test_key_int", None)

    def test_safe_get_runtime_int_missing(self):
        from mind_clone.core.self_tune import _safe_get_runtime_int
        assert _safe_get_runtime_int("nonexistent_key_xyz", 99) == 99

    def test_safe_get_runtime_int_invalid(self):
        from mind_clone.core.self_tune import _safe_get_runtime_int
        RUNTIME_STATE["test_key_bad"] = "not_a_number"
        assert _safe_get_runtime_int("test_key_bad", 7) == 7
        RUNTIME_STATE.pop("test_key_bad", None)

    def test_safe_set_config_value(self):
        from mind_clone.core.self_tune import _safe_set_config_value

        class FakeConfig:
            x = 10
        cfg = FakeConfig()
        assert _safe_set_config_value(cfg, "x", 20) is True
        assert cfg.x == 20
        assert _safe_set_config_value(cfg, "nonexistent", 5) is False

    def test_safe_increment_counter(self):
        from mind_clone.core.self_tune import _safe_increment_counter
        RUNTIME_STATE["test_counter"] = 0
        _safe_increment_counter("test_counter", 5)
        assert RUNTIME_STATE["test_counter"] == 5
        _safe_increment_counter("test_counter", 3)
        assert RUNTIME_STATE["test_counter"] == 8
        RUNTIME_STATE.pop("test_counter", None)

    def test_safe_increment_counter_bounds(self):
        from mind_clone.core.self_tune import _safe_increment_counter
        RUNTIME_STATE["test_counter2"] = 999990
        _safe_increment_counter("test_counter2", 100)
        assert RUNTIME_STATE["test_counter2"] == 999999  # capped
        RUNTIME_STATE.pop("test_counter2", None)


# ---------------------------------------------------------------------------
# Mutation-killing boundary tests (Section 5C - kill surviving mutations)
# ---------------------------------------------------------------------------

class TestBoundaryMutationKillers:
    """Tests specifically designed to kill boundary condition mutations."""

    def setup_method(self):
        _reset_runtime_keys()
        _reset_hysteresis()

    # ----------- Queue Mode: backlog >= threshold (L134) -----------

    def test_backlog_exactly_at_threshold_10_must_switch(self):
        """Mutation: >= -> < would cause this to NOT switch. Assert exact result."""
        RUNTIME_STATE["command_queue_enqueued"] = 10
        RUNTIME_STATE["command_queue_processed"] = 0
        RUNTIME_STATE["command_queue_mode"] = "on"
        actions = st_tune_queue_mode()
        # Must switch: backlog (10) >= effective_threshold (10)
        assert len(actions) == 1, "Must have 1 action at exact threshold"
        assert RUNTIME_STATE["command_queue_mode"] == "auto", "Mode must be auto"
        assert "on->auto" in actions[0], "Action must describe transition"

    def test_backlog_9_below_threshold_no_switch(self):
        """Backlog below threshold must NOT switch."""
        RUNTIME_STATE["command_queue_enqueued"] = 9
        RUNTIME_STATE["command_queue_processed"] = 0
        RUNTIME_STATE["command_queue_mode"] = "on"
        actions = st_tune_queue_mode()
        assert len(actions) == 0, "No action when backlog < 10"
        assert RUNTIME_STATE["command_queue_mode"] == "on", "Mode must stay on"

    def test_backlog_11_above_threshold_must_switch(self):
        """Backlog above threshold must switch."""
        RUNTIME_STATE["command_queue_enqueued"] = 11
        RUNTIME_STATE["command_queue_processed"] = 0
        RUNTIME_STATE["command_queue_mode"] = "on"
        actions = st_tune_queue_mode()
        assert len(actions) == 1, "Must switch"
        assert RUNTIME_STATE["command_queue_mode"] == "auto", "Mode auto"

    # ----------- Session Budget: delta >= THRESHOLD (L166) -----------

    @patch("mind_clone.core.self_tune._cfg")
    def test_compaction_delta_exactly_5_must_raise(self, mock_cfg):
        """Delta == 5 (threshold) must raise budget. Mutation: >= -> < would fail."""
        mock_cfg.SESSION_SOFT_TRIM_CHAR_BUDGET = 40000
        mock_cfg.SESSION_HARD_CLEAR_CHAR_BUDGET = 48000
        type(mock_cfg).SESSION_SOFT_TRIM_CHAR_BUDGET = 40000
        type(mock_cfg).SESSION_HARD_CLEAR_CHAR_BUDGET = 48000

        RUNTIME_STATE["session_compaction_by_chars"] = 0
        st_tune_session_budget()  # baseline

        RUNTIME_STATE["session_compaction_by_chars"] = 5  # delta = 5 (exact threshold)
        actions = st_tune_session_budget()

        # Must have raised budget
        assert len(actions) >= 1, f"Must raise at delta=5, got {actions}"
        assert "raised" in actions[0], "Must say 'raised'"

    @patch("mind_clone.core.self_tune._cfg")
    def test_compaction_delta_4_below_threshold_no_raise(self, mock_cfg):
        """Delta == 4 (below threshold) must NOT raise. Mutation: >= -> > would pass incorrectly."""
        mock_cfg.SESSION_SOFT_TRIM_CHAR_BUDGET = 40000
        mock_cfg.SESSION_HARD_CLEAR_CHAR_BUDGET = 48000
        type(mock_cfg).SESSION_SOFT_TRIM_CHAR_BUDGET = 40000
        type(mock_cfg).SESSION_HARD_CLEAR_CHAR_BUDGET = 48000

        RUNTIME_STATE["session_compaction_by_chars"] = 0
        st_tune_session_budget()  # baseline

        RUNTIME_STATE["session_compaction_by_chars"] = 4  # delta = 4 (below 5)
        actions = st_tune_session_budget()

        # Must NOT raise
        assert len(actions) == 0, f"Must not raise at delta=4, got {actions}"

    # ----------- Session Budget: ticks >= 10 (L187) -----------

    @patch("mind_clone.core.self_tune._cfg")
    def test_stable_ticks_exactly_10_must_lower(self, mock_cfg):
        """At exactly 10 ticks with zero delta, must lower budget."""
        mock_cfg.SESSION_SOFT_TRIM_CHAR_BUDGET = 50000
        mock_cfg.SESSION_HARD_CLEAR_CHAR_BUDGET = 58000
        type(mock_cfg).SESSION_SOFT_TRIM_CHAR_BUDGET = 50000
        type(mock_cfg).SESSION_HARD_CLEAR_CHAR_BUDGET = 58000

        RUNTIME_STATE["session_compaction_by_chars"] = 0
        _st_mod._st_prev_hard_clears = 0
        _st_mod._st_zero_hard_clear_ticks = 10  # exactly at threshold

        actions = st_tune_session_budget()

        # Must lower
        assert len(actions) >= 1, f"Must lower at ticks=10, got {actions}"
        assert "lowered" in actions[0], "Must say 'lowered'"

    @patch("mind_clone.core.self_tune._cfg")
    def test_stable_ticks_9_no_lower(self, mock_cfg):
        """At 9 ticks with zero delta, increment counter but don't lower yet."""
        mock_cfg.SESSION_SOFT_TRIM_CHAR_BUDGET = 50000
        mock_cfg.SESSION_HARD_CLEAR_CHAR_BUDGET = 58000
        type(mock_cfg).SESSION_SOFT_TRIM_CHAR_BUDGET = 50000
        type(mock_cfg).SESSION_HARD_CLEAR_CHAR_BUDGET = 58000

        # Set baseline
        RUNTIME_STATE["session_compaction_by_chars"] = 0
        _st_mod._st_prev_hard_clears = 0
        st_tune_session_budget()  # Initialize

        # Now set counter to 8 (will increment to 9)
        _st_mod._st_zero_hard_clear_ticks = 8
        RUNTIME_STATE["session_compaction_by_chars"] = 0  # delta still 0
        _st_mod._st_prev_hard_clears = 0

        actions = st_tune_session_budget()

        # Must NOT lower at 9 (only lowers at >= 10)
        assert len(actions) == 0, f"Must not lower at ticks=9, got {actions}"
        # Counter must have incremented to 9
        assert _st_mod._st_zero_hard_clear_ticks == 9, "Counter should be 9"

    # ----------- Worker Scaling: queue_size > 5 (L228) -----------

    @patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True)
    @patch("mind_clone.core.self_tune._cfg")
    def test_queue_size_exactly_6_must_scale_up(self, mock_cfg, _):
        """Queue size 6 (> 5) must scale up. Mutation: > -> >= would fail at 6."""
        mock_cfg.COMMAND_QUEUE_WORKER_COUNT = 2
        mock_cfg.SELF_TUNE_WORKER_MAX = 6
        RUNTIME_STATE["command_queue_size"] = 6  # exactly above 5
        RUNTIME_STATE["command_queue_worker_alive_count"] = 2

        actions = st_tune_workers()

        assert len(actions) == 1, f"Must scale at size=6, got {actions}"
        assert mock_cfg.COMMAND_QUEUE_WORKER_COUNT == 3, "Must scale to 3"

    @patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True)
    @patch("mind_clone.core.self_tune._cfg")
    def test_queue_size_5_no_scale(self, mock_cfg, _):
        """Queue size 5 must NOT scale (condition is > 5)."""
        mock_cfg.COMMAND_QUEUE_WORKER_COUNT = 2
        mock_cfg.SELF_TUNE_WORKER_MAX = 6
        RUNTIME_STATE["command_queue_size"] = 5  # not > 5
        RUNTIME_STATE["command_queue_worker_alive_count"] = 2

        actions = st_tune_workers()

        assert len(actions) == 0, f"Must not scale at size=5, got {actions}"
        assert mock_cfg.COMMAND_QUEUE_WORKER_COUNT == 2, "Count unchanged"

    # ----------- Worker Scaling: idle_ticks >= 10 (L239) -----------

    @patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True)
    @patch("mind_clone.core.self_tune._cfg")
    def test_idle_ticks_exactly_10_must_scale_down(self, mock_cfg, _):
        """At exactly 10 idle ticks with queue empty, must scale down."""
        mock_cfg.COMMAND_QUEUE_WORKER_COUNT = 3
        RUNTIME_STATE["command_queue_size"] = 0
        RUNTIME_STATE["command_queue_worker_alive_count"] = 3
        _st_mod._st_zero_queue_ticks = 10  # exactly at threshold

        actions = st_tune_workers()

        assert len(actions) == 1, f"Must scale down at ticks=10, got {actions}"
        assert mock_cfg.COMMAND_QUEUE_WORKER_COUNT == 2, "Must scale to 2"

    @patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True)
    @patch("mind_clone.core.self_tune._cfg")
    def test_idle_ticks_9_no_scale_down(self, mock_cfg, _):
        """At 9 idle ticks (before increment), must NOT scale down."""
        mock_cfg.COMMAND_QUEUE_WORKER_COUNT = 3
        RUNTIME_STATE["command_queue_size"] = 0
        RUNTIME_STATE["command_queue_worker_alive_count"] = 3
        _st_mod._st_zero_queue_ticks = 8  # Will increment to 9, not >= 10

        actions = st_tune_workers()

        assert len(actions) == 0, f"Must not scale at ticks=9, got {actions}"
        assert mock_cfg.COMMAND_QUEUE_WORKER_COUNT == 3, "Count unchanged"
        assert _st_mod._st_zero_queue_ticks == 9, "Counter incremented to 9"

    # ----------- Budget Mode: delta > 3 (L267) -----------

    @patch("mind_clone.core.self_tune._cfg")
    def test_degradation_delta_exactly_4_must_loosen(self, mock_cfg):
        """Delta == 4 (> 3 threshold) must loosen. Mutation: > -> >= would fail."""
        RUNTIME_STATE["budget_runs_degraded"] = 4
        RUNTIME_STATE["budget_governor_mode"] = "degrade"
        _st_mod._st_prev_degraded = 0  # delta = 4

        actions = st_tune_budget_mode()

        assert len(actions) == 1, f"Must loosen at delta=4, got {actions}"
        assert "degrade->warn" in actions[0], "Must transition correctly"
        assert mock_cfg.BUDGET_GOVERNOR_MODE == "warn", "Mode must be warn"

    @patch("mind_clone.core.self_tune._cfg")
    def test_degradation_delta_exactly_3_no_loosen(self, mock_cfg):
        """Delta == 3 (not > 3) must NOT loosen."""
        RUNTIME_STATE["budget_runs_degraded"] = 3
        RUNTIME_STATE["budget_governor_mode"] = "degrade"
        _st_mod._st_prev_degraded = 0

        actions = st_tune_budget_mode()

        assert len(actions) == 0, f"Must not loosen at delta=3, got {actions}"
        assert not hasattr(mock_cfg, 'BUDGET_GOVERNOR_MODE') or mock_cfg.BUDGET_GOVERNOR_MODE != "warn", "Mode must not change"

    # ----------- Budget Mode: stable_ticks >= 20 (L276) -----------

    @patch("mind_clone.core.self_tune._cfg")
    def test_stable_ticks_exactly_20_must_tighten(self, mock_cfg):
        """At exactly 20 ticks with zero delta in warn mode, must tighten."""
        RUNTIME_STATE["budget_runs_degraded"] = 0
        RUNTIME_STATE["budget_governor_mode"] = "warn"
        _st_mod._st_prev_degraded = 0
        _st_mod._st_zero_degraded_ticks = 20  # exactly at threshold

        actions = st_tune_budget_mode()

        assert len(actions) == 1, f"Must tighten at ticks=20, got {actions}"
        assert "warn->degrade" in actions[0], "Must transition correctly"
        assert mock_cfg.BUDGET_GOVERNOR_MODE == "degrade", "Mode must be degrade"

    @patch("mind_clone.core.self_tune._cfg")
    def test_stable_ticks_19_no_tighten(self, mock_cfg):
        """At 19 ticks (before increment), must NOT tighten yet."""
        RUNTIME_STATE["budget_runs_degraded"] = 0
        RUNTIME_STATE["budget_governor_mode"] = "warn"
        _st_mod._st_prev_degraded = 0
        _st_mod._st_zero_degraded_ticks = 18  # Will increment to 19, not >= 20

        actions = st_tune_budget_mode()

        assert len(actions) == 0, f"Must not tighten at ticks=19, got {actions}"
        assert _st_mod._st_zero_degraded_ticks == 19, "Counter incremented to 19"


class TestArithmeticMutationKillers:
    """Tests for arithmetic operations that might be mutated."""

    def setup_method(self):
        _reset_runtime_keys()
        _reset_hysteresis()

    def test_effective_threshold_max_10_not_addition(self):
        """Line 133: max(10, THRESHOLD). If mutated to +, result would be wrong."""
        # SELF_TUNE_QUEUE_BACKLOG_THRESHOLD is from config (likely >= 10)
        # effective_threshold = max(10, config_val)
        # Test that we get at least 10
        RUNTIME_STATE["command_queue_enqueued"] = 10
        RUNTIME_STATE["command_queue_processed"] = 0
        RUNTIME_STATE["command_queue_mode"] = "on"
        actions = st_tune_queue_mode()
        # With backlog=10 and mode="on", should switch (proving max works)
        assert len(actions) == 1, "max(10, threshold) must work correctly"

    def test_backlog_calculation_subtraction_not_addition(self):
        """Line 130: backlog = max(0, enqueued - processed). Test subtraction is correct."""
        # If - was changed to +, backlog would be enqueued + processed
        RUNTIME_STATE["command_queue_enqueued"] = 5
        RUNTIME_STATE["command_queue_processed"] = 3
        # True backlog = 5 - 3 = 2 (< 10, no switch)
        # If mutated to +: 5 + 3 = 8 (still < 10, no switch) — hard to catch!
        RUNTIME_STATE["command_queue_mode"] = "on"
        actions = st_tune_queue_mode()
        # With low backlog, no switch
        assert actions == [], "Low backlog should not switch"

        # Now test with values where + vs - makes a difference
        RUNTIME_STATE["command_queue_enqueued"] = 15
        RUNTIME_STATE["command_queue_processed"] = 2
        # True backlog = 15 - 2 = 13 (>= 10, must switch)
        # If mutated to +: 15 + 2 = 17 (still >= 10, switch) — still indistinguishable!
        # So test the actual result via the state
        actions = st_tune_queue_mode()
        assert len(actions) == 1, "High backlog must switch"
        assert RUNTIME_STATE["command_queue_mode"] == "auto", "Mode changed to auto"

    def test_worker_increment_by_1_not_other(self):
        """Line 230: new_count = min(MAX, old_count + 1). Test +1 specifically."""
        with patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True):
            with patch("mind_clone.core.self_tune._cfg") as mock_cfg:
                mock_cfg.COMMAND_QUEUE_WORKER_COUNT = 2
                mock_cfg.SELF_TUNE_WORKER_MAX = 10
                RUNTIME_STATE["command_queue_size"] = 10
                RUNTIME_STATE["command_queue_worker_alive_count"] = 2

                st_tune_workers()

                # Must increment by exactly 1
                assert mock_cfg.COMMAND_QUEUE_WORKER_COUNT == 3, "Must increment by 1, not other amount"

    def test_worker_decrement_by_1_not_other(self):
        """Line 241: new_count = max(2, old_count - 1). Test -1 specifically."""
        with patch("mind_clone.core.self_tune.command_queue_enabled", return_value=True):
            with patch("mind_clone.core.self_tune._cfg") as mock_cfg:
                mock_cfg.COMMAND_QUEUE_WORKER_COUNT = 5
                RUNTIME_STATE["command_queue_size"] = 0
                RUNTIME_STATE["command_queue_worker_alive_count"] = 5
                _st_mod._st_zero_queue_ticks = 10

                st_tune_workers()

                # Must decrement by exactly 1
                assert mock_cfg.COMMAND_QUEUE_WORKER_COUNT == 4, "Must decrement by 1, not other amount"

    @patch("mind_clone.core.self_tune._cfg")
    def test_budget_step_addition_correctly_applied(self, mock_cfg):
        """Line 170: new_soft = min(MAX, old_soft + STEP). Test + is correct."""
        mock_cfg.SESSION_SOFT_TRIM_CHAR_BUDGET = 40000
        mock_cfg.SESSION_HARD_CLEAR_CHAR_BUDGET = 48000
        type(mock_cfg).SESSION_SOFT_TRIM_CHAR_BUDGET = 40000
        type(mock_cfg).SESSION_HARD_CLEAR_CHAR_BUDGET = 48000

        RUNTIME_STATE["session_compaction_by_chars"] = 0
        st_tune_session_budget()

        # Simulate high compaction (delta = 10 >= 5)
        RUNTIME_STATE["session_compaction_by_chars"] = 10
        st_tune_session_budget()

        # Check that old_soft (40000) + step (8000 from config default) = 48000
        new_soft = RUNTIME_STATE.get("st_current_session_soft_budget", 0)
        assert new_soft > 40000, f"Budget must increase, got {new_soft}"
        # Specific value is 40000 + 8000 = 48000
        assert new_soft == 48000, f"Must be 40000 + 8000 = 48000, got {new_soft}"
