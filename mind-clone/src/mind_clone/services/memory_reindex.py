"""Backward-compatibility shim — moved to ``services.memory.reindex``.

All public symbols are re-exported so existing imports keep working.
"""
from __future__ import annotations

# ruff: noqa: F401
from .memory.reindex import reindex_owner_memory_vectors
