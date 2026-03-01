"""
Knowledge base tool functions.

Thin wrappers around the CodebaseIndex engine in ``core.knowledge``.
Tool functions live here (tools/); the engine lives in core/.

Pillar: Memory, World Understanding
"""

from __future__ import annotations

import os
import pathlib
from typing import Any, Dict

from ..core.knowledge import CodebaseIndex, _INDEX_CACHE


def tool_index_codebase(args: dict) -> dict:
    """Index a project directory for knowledge retrieval."""
    path = str(args.get("path", "")).strip()
    if not path:
        return {"ok": False, "error": "path is required"}

    idx = CodebaseIndex(path)
    result = idx.scan()
    if result.get("ok"):
        saved = idx.save()
        result["saved_to"] = saved
        result["summary"] = idx.get_summary()
    return result


def tool_query_knowledge(args: dict) -> dict:
    """Query the codebase knowledge base."""
    query = str(args.get("query", "")).strip()
    if not query:
        return {"ok": False, "error": "query is required"}

    path = str(args.get("path", "")).strip()

    # Try cache first
    if path and path in _INDEX_CACHE:
        results = _INDEX_CACHE[path].query(query)
        return {"ok": True, "results": results, "source": "cache"}

    # Try any cached index
    for root, idx in _INDEX_CACHE.items():
        results = idx.query(query)
        if results:
            return {"ok": True, "results": results, "source": root}

    return {"ok": False, "error": "No codebase indexed. Use index_codebase first."}


def tool_knowledge_summary(args: dict) -> dict:
    """Get project overview from the knowledge base."""
    path = str(args.get("path", "")).strip()

    if path and path in _INDEX_CACHE:
        return {"ok": True, **_INDEX_CACHE[path].get_summary()}

    # Try any cached index
    for root, idx in _INDEX_CACHE.items():
        return {"ok": True, **idx.get_summary()}

    # Try loading from disk
    if path:
        name = pathlib.Path(path).name
        persist_path = f"persist/knowledge/{name}_index.json"
        if os.path.exists(persist_path):
            idx = CodebaseIndex(path)
            if idx.load(persist_path):
                return {"ok": True, **idx.get_summary()}

    return {"ok": False, "error": "No codebase indexed. Use index_codebase first."}
