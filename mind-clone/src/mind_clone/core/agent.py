"""
Agent functions re-exported for backward compatibility.
"""

from ..agent.loop import run_agent_loop as run_agent_loop_with_new_session

__all__ = ["run_agent_loop_with_new_session"]
