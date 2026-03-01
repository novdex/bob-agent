"""
MCP (Model Context Protocol) server endpoints.

Exposes Bob's capabilities as MCP-compatible tools that other agents
can discover and use via JSON-RPC 2.0.

Pillar: Communication, Tool Mastery
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/mcp", tags=["mcp"])
logger = logging.getLogger("mind_clone.api.mcp")

# ---------------------------------------------------------------------------
# JSON-RPC models
# ---------------------------------------------------------------------------

class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: dict = Field(default_factory=dict)
    id: Optional[Union[int, str]] = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    result: Optional[dict] = None
    error: Optional[dict] = None
    id: Optional[Union[int, str]] = None


# JSON-RPC error codes
ERR_INVALID_REQUEST = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL = -32603


def _error_response(code: int, message: str, req_id: Any = None) -> dict:
    return {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": req_id}


def _success_response(result: dict, req_id: Any = None) -> dict:
    return {"jsonrpc": "2.0", "result": result, "id": req_id}


# ---------------------------------------------------------------------------
# MCP tool definitions
# ---------------------------------------------------------------------------

MCP_TOOLS: List[dict] = [
    {
        "name": "bob_chat",
        "description": "Send a message to Bob and get a response. Bob is a sovereign AI agent with 77+ tools.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The message to send to Bob"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "bob_search_memory",
        "description": "Search Bob's semantic memory for relevant information.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "top_k": {"type": "integer", "description": "Number of results", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "bob_execute_tool",
        "description": "Execute any of Bob's 77+ tools by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "Name of the tool to execute"},
                "arguments": {"type": "object", "description": "Tool arguments"},
            },
            "required": ["tool_name"],
        },
    },
    {
        "name": "bob_status",
        "description": "Get Bob's runtime status and metrics.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "bob_index_project",
        "description": "Index a codebase for Bob's persistent knowledge base.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the project directory"},
            },
            "required": ["path"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def _handle_chat(params: dict) -> dict:
    """Handle bob_chat tool call."""
    message = str(params.get("arguments", {}).get("message", "")).strip()
    if not message:
        return {"content": [{"type": "text", "text": "Error: message is required"}], "isError": True}

    try:
        from ...agent.loop import run_agent_loop
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, run_agent_loop, 1, message)
        return {"content": [{"type": "text", "text": response}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"Error: {str(exc)[:500]}"}], "isError": True}


async def _handle_search_memory(params: dict) -> dict:
    """Handle bob_search_memory tool call."""
    args = params.get("arguments", {})
    query = str(args.get("query", "")).strip()
    if not query:
        return {"content": [{"type": "text", "text": "Error: query is required"}], "isError": True}

    try:
        from ...tools.registry import execute_tool
        result = execute_tool("semantic_memory_search", {"query": query, "top_k": args.get("top_k", 5)})
        import json
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"Error: {str(exc)[:500]}"}], "isError": True}


async def _handle_execute_tool(params: dict) -> dict:
    """Handle bob_execute_tool tool call."""
    args = params.get("arguments", {})
    tool_name = str(args.get("tool_name", "")).strip()
    if not tool_name:
        return {"content": [{"type": "text", "text": "Error: tool_name is required"}], "isError": True}

    try:
        from ...tools.registry import execute_tool, TOOL_DISPATCH
        if tool_name not in TOOL_DISPATCH:
            return {"content": [{"type": "text", "text": f"Error: Unknown tool '{tool_name}'"}], "isError": True}

        tool_args = args.get("arguments", {})
        result = execute_tool(tool_name, tool_args)
        import json
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)[:8000]}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"Error: {str(exc)[:500]}"}], "isError": True}


async def _handle_status(params: dict) -> dict:
    """Handle bob_status tool call."""
    try:
        from ...core.state import RUNTIME_STATE
        # Return safe subset of metrics
        safe_keys = [k for k in RUNTIME_STATE if not any(
            secret in k.lower() for secret in ("key", "token", "secret", "password")
        )]
        status = {k: RUNTIME_STATE[k] for k in safe_keys[:50]}
        import json
        return {"content": [{"type": "text", "text": json.dumps(status, default=str)}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"Error: {str(exc)[:500]}"}], "isError": True}


async def _handle_index_project(params: dict) -> dict:
    """Handle bob_index_project tool call."""
    args = params.get("arguments", {})
    path = str(args.get("path", "")).strip()
    if not path:
        return {"content": [{"type": "text", "text": "Error: path is required"}], "isError": True}

    try:
        from ...tools.registry import execute_tool
        result = execute_tool("codebase_structure", {"path": path})
        import json
        return {"content": [{"type": "text", "text": json.dumps(result, default=str)[:8000]}]}
    except Exception as exc:
        return {"content": [{"type": "text", "text": f"Error: {str(exc)[:500]}"}], "isError": True}


_TOOL_HANDLERS = {
    "bob_chat": _handle_chat,
    "bob_search_memory": _handle_search_memory,
    "bob_execute_tool": _handle_execute_tool,
    "bob_status": _handle_status,
    "bob_index_project": _handle_index_project,
}


# ---------------------------------------------------------------------------
# JSON-RPC method dispatch
# ---------------------------------------------------------------------------

async def _handle_initialize(req: JsonRpcRequest) -> dict:
    return _success_response({
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": "bob-agent", "version": "1.0.0"},
    }, req.id)


async def _handle_tools_list(req: JsonRpcRequest) -> dict:
    return _success_response({"tools": MCP_TOOLS}, req.id)


async def _handle_tools_call(req: JsonRpcRequest) -> dict:
    tool_name = req.params.get("name", "")
    handler = _TOOL_HANDLERS.get(tool_name)
    if not handler:
        return _error_response(ERR_INVALID_PARAMS, f"Unknown tool: {tool_name}", req.id)

    try:
        result = await handler(req.params)
        return _success_response(result, req.id)
    except Exception as exc:
        logger.error("MCP_TOOL_CALL_ERROR tool=%s error=%s", tool_name, str(exc)[:200])
        return _error_response(ERR_INTERNAL, str(exc)[:500], req.id)


_METHOD_HANDLERS = {
    "initialize": _handle_initialize,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
}


# ---------------------------------------------------------------------------
# FastAPI endpoints
# ---------------------------------------------------------------------------

@router.post("")
async def mcp_endpoint(request: JsonRpcRequest) -> dict:
    """Main MCP JSON-RPC 2.0 endpoint."""
    logger.info("MCP_REQUEST method=%s id=%s", request.method, request.id)

    handler = _METHOD_HANDLERS.get(request.method)
    if not handler:
        return _error_response(ERR_METHOD_NOT_FOUND, f"Method not found: {request.method}", request.id)

    try:
        return await handler(request)
    except Exception as exc:
        logger.error("MCP_ERROR method=%s error=%s", request.method, str(exc)[:200])
        return _error_response(ERR_INTERNAL, str(exc)[:500], request.id)


@router.get("/health")
async def mcp_health():
    """MCP server health check."""
    return {"ok": True, "server": "bob-agent", "protocol": "mcp-2024-11-05"}
