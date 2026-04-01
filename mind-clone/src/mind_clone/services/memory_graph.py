"""Backward-compatibility shim — moved to ``services.memory.graph``.

All public symbols are re-exported so existing imports keep working.
"""
from __future__ import annotations

# ruff: noqa: F401
from .memory.graph import (
    link_memories,
    get_links,
    auto_link,
    graph_search,
    prune_context_for_prompt,
    NODE_TYPES,
    RELATION_TYPES,
)
