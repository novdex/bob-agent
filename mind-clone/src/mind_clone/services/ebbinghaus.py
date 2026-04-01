"""Backward-compatibility shim — moved to ``services.memory.ebbinghaus``.

All public symbols are re-exported so existing imports keep working.
"""
from __future__ import annotations

# ruff: noqa: F401
from .memory.ebbinghaus import (
    decay_memories,
    boost_memory,
    prune_faded_memories,
    get_important_memories,
    run_daily_memory_maintenance,
)
