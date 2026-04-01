"""Memory services package — consolidator, graph, ebbinghaus, export, reindex.

Re-exports all public symbols from sub-modules so that existing imports
like ``from mind_clone.services.memory.consolidator import ...`` work,
and the old ``from mind_clone.services.memory_consolidator import ...``
paths continue to work via shim modules at the old locations.
"""

from __future__ import annotations

import logging

_log = logging.getLogger("mind_clone.services.memory")

# -- Consolidator ----------------------------------------------------------
try:
    from .consolidator import (
        consolidate_research_notes,
        consolidate_improvement_notes,
        consolidate_episodic_memories,
        run_full_consolidation,
        tool_consolidate_memory,
    )
except ImportError as _e:
    _log.warning("memory.consolidator unavailable: %s", _e)

# -- Graph -----------------------------------------------------------------
try:
    from .graph import (
        link_memories,
        get_links,
        auto_link,
        graph_search,
        prune_context_for_prompt,
        NODE_TYPES,
        RELATION_TYPES,
    )
except ImportError as _e:
    _log.warning("memory.graph unavailable: %s", _e)

# -- Ebbinghaus ------------------------------------------------------------
try:
    from .ebbinghaus import (
        decay_memories,
        boost_memory,
        prune_faded_memories,
        get_important_memories,
        run_daily_memory_maintenance,
    )
except ImportError as _e:
    _log.warning("memory.ebbinghaus unavailable: %s", _e)

# -- Export ----------------------------------------------------------------
try:
    from .export import (
        build_memory_export_payload,
        export_as_markdown,
        export_as_json,
    )
except ImportError as _e:
    _log.warning("memory.export unavailable: %s", _e)

# -- Reindex ---------------------------------------------------------------
try:
    from .reindex import reindex_owner_memory_vectors
except ImportError as _e:
    _log.warning("memory.reindex unavailable: %s", _e)

__all__ = [
    # consolidator
    "consolidate_research_notes",
    "consolidate_improvement_notes",
    "consolidate_episodic_memories",
    "run_full_consolidation",
    "tool_consolidate_memory",
    # graph
    "link_memories",
    "get_links",
    "auto_link",
    "graph_search",
    "prune_context_for_prompt",
    "NODE_TYPES",
    "RELATION_TYPES",
    # ebbinghaus
    "decay_memories",
    "boost_memory",
    "prune_faded_memories",
    "get_important_memories",
    "run_daily_memory_maintenance",
    # export
    "build_memory_export_payload",
    "export_as_markdown",
    "export_as_json",
    # reindex
    "reindex_owner_memory_vectors",
]
