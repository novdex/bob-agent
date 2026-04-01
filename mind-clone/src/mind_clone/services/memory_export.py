"""Backward-compatibility shim — moved to ``services.memory.export``.

All public symbols are re-exported so existing imports keep working.
"""
from __future__ import annotations

# ruff: noqa: F401
from .memory.export import (
    build_memory_export_payload,
    export_as_markdown,
    export_as_json,
)
