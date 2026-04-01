"""Backward-compatibility shim — moved to ``services.memory.consolidator``.

All public symbols are re-exported so existing imports keep working.
"""
from __future__ import annotations

# ruff: noqa: F401
from .memory.consolidator import (
    consolidate_research_notes,
    consolidate_improvement_notes,
    consolidate_episodic_memories,
    run_full_consolidation,
    tool_consolidate_memory,
)
