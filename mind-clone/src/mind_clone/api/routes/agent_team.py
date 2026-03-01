"""
API routes for the autonomous agent team.

POST /agent/run     — Launch agent team on a task
GET  /agent/status  — Check agent team status
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ._shared import require_ops_auth

logger = logging.getLogger("mind_clone.api.agent_team")

router = APIRouter(prefix="/agent", tags=["agent-team"])


class AgentRunRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=2000,
                      description="Description of the code change to make")


class AgentRunResponse(BaseModel):
    ok: bool
    summary: str = ""
    error: str = ""
    branch: str = ""
    duration_s: float = 0.0
    llm_stats: dict = {}


class AgentStatusResponse(BaseModel):
    ok: bool = True
    status: str = "idle"
    current_task: str = ""
    last_result: dict = {}


@router.post("/run", response_model=AgentRunResponse)
def agent_run(req: AgentRunRequest, _ops=Depends(require_ops_auth)):
    """Launch the autonomous agent team to modify the codebase."""
    from ...tools.agent_team import tool_agent_team_run
    result = tool_agent_team_run({"task": req.task})
    return AgentRunResponse(**result)


@router.get("/status", response_model=AgentStatusResponse)
def agent_status(_ops=Depends(require_ops_auth)):
    """Check the current status of the agent team."""
    from ...tools.agent_team import tool_agent_team_status
    result = tool_agent_team_status({})
    return AgentStatusResponse(**result)
