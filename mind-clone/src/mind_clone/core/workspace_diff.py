"""
Workspace diff utilities.
"""
from typing import Dict, Any, List

def compute_workspace_diff(owner_id: int, since: str = None) -> Dict[str, Any]:
    """Compute diff of workspace changes."""
    return {"files_changed": [], "lines_added": 0, "lines_removed": 0}

def approve_workspace_diff(owner_id: int, diff_id: str) -> bool:
    """Approve a workspace diff."""
    return True

def reject_workspace_diff(owner_id: int, diff_id: str) -> bool:
    """Reject a workspace diff."""
    return True

def list_pending_diffs(owner_id: int = None) -> List[Dict[str, Any]]:
    """List pending workspace diffs."""
    return []

def evaluate_workspace_diff_gate(owner_id: int) -> Dict[str, Any]:
    """Evaluate workspace diff gate for an owner."""
    return {"ok": True, "needs_approval": False}

__all__ = ["compute_workspace_diff", "approve_workspace_diff", "reject_workspace_diff", "list_pending_diffs", "evaluate_workspace_diff_gate"]
