"""
IDE integration API routes for VS Code / Cursor extension support.

Endpoints:
    POST /api/ide/complete    — Code completion (send code context, get suggestions)
    POST /api/ide/explain     — Explain selected code
    POST /api/ide/refactor    — Refactor code with instructions
    POST /api/ide/fix         — Fix errors in code
    POST /api/ide/test        — Generate tests for code
    POST /api/ide/chat        — General chat with file context
    GET  /api/ide/status      — IDE connection health check
    GET  /api/ide/models      — List available models
"""

from __future__ import annotations

import json
import logging
import time
from typing import Dict, List, Optional, Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...config import settings
from ...agent.llm import call_llm, get_available_models, get_provider_status
from ...core.state import RUNTIME_STATE, increment_runtime_state

logger = logging.getLogger("mind_clone.api.ide")

router = APIRouter(prefix="/api/ide", tags=["ide"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class IDECodeContext(BaseModel):
    """Code context from the IDE."""
    file_path: str = Field(..., description="Absolute path to the file")
    language: str = Field(default="python", description="Programming language")
    code: str = Field(..., description="The code or selection")
    cursor_line: int = Field(default=0, description="Cursor line number")
    cursor_column: int = Field(default=0, description="Cursor column number")
    surrounding_code: str = Field(default="", description="Code around the cursor (broader context)")
    project_root: str = Field(default="", description="Project root directory")


class IDECompleteRequest(BaseModel):
    """Code completion request."""
    context: IDECodeContext
    prefix: str = Field(default="", description="Text before cursor on current line")
    max_suggestions: int = Field(default=3, ge=1, le=10)
    owner_id: int = Field(default=1, ge=1)


class IDEExplainRequest(BaseModel):
    """Code explanation request."""
    context: IDECodeContext
    detail_level: str = Field(default="medium", description="brief | medium | detailed")
    owner_id: int = Field(default=1, ge=1)


class IDERefactorRequest(BaseModel):
    """Code refactoring request."""
    context: IDECodeContext
    instruction: str = Field(..., min_length=1, description="What to refactor and how")
    owner_id: int = Field(default=1, ge=1)


class IDEFixRequest(BaseModel):
    """Code fix request."""
    context: IDECodeContext
    error_message: str = Field(default="", description="Error/diagnostic message")
    diagnostics: List[Dict[str, Any]] = Field(default_factory=list, description="LSP diagnostics")
    owner_id: int = Field(default=1, ge=1)


class IDETestRequest(BaseModel):
    """Test generation request."""
    context: IDECodeContext
    framework: str = Field(default="pytest", description="Test framework (pytest, unittest, jest, etc.)")
    owner_id: int = Field(default=1, ge=1)


class IDEChatRequest(BaseModel):
    """Chat with file context."""
    message: str = Field(..., min_length=1, max_length=32000)
    context: Optional[IDECodeContext] = None
    owner_id: int = Field(default=1, ge=1)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _call_ide_llm(
    system: str,
    user: str,
    owner_id: int = 1,
) -> Dict[str, Any]:
    """Call LLM with IDE-specific system prompt. Returns result dict."""
    start = time.monotonic()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    result = call_llm(messages, max_tokens=4096)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    increment_runtime_state("ide_requests_total")

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "LLM call failed")}

    return {
        "ok": True,
        "content": result.get("content", ""),
        "provider": result.get("provider", "unknown"),
        "elapsed_ms": elapsed_ms,
        "usage": result.get("usage", {}),
    }


def _format_code_context(ctx: IDECodeContext) -> str:
    """Format code context for the LLM prompt."""
    parts = [f"File: {ctx.file_path}", f"Language: {ctx.language}"]
    if ctx.cursor_line:
        parts.append(f"Cursor: line {ctx.cursor_line}, col {ctx.cursor_column}")
    parts.append(f"\n```{ctx.language}\n{ctx.code}\n```")
    if ctx.surrounding_code:
        parts.append(f"\nSurrounding context:\n```{ctx.language}\n{ctx.surrounding_code}\n```")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
async def ide_status():
    """IDE connection health check."""
    return {
        "ok": True,
        "agent": "Bob (Mind Clone)",
        "version": "1.0",
        "providers": get_provider_status(),
        "models": get_available_models(),
        "ide_requests_total": RUNTIME_STATE.get("ide_requests_total", 0),
    }


@router.get("/models")
async def ide_models():
    """List available LLM models."""
    return {
        "models": get_available_models(),
        "providers": get_provider_status(),
    }


@router.post("/complete")
async def ide_complete(req: IDECompleteRequest):
    """Generate code completions."""
    ctx_str = _format_code_context(req.context)
    system = f"""You are an expert code completion engine. Given code context, provide {req.max_suggestions} completion suggestion(s).
Return ONLY code — no explanations, no markdown fences. One suggestion per line, separated by ---."""

    user = f"""{ctx_str}

Complete the code at the cursor position. Prefix on current line: `{req.prefix}`
Provide {req.max_suggestions} suggestion(s):"""

    result = _call_ide_llm(system, user, req.owner_id)
    if not result["ok"]:
        return result

    # Parse suggestions
    raw = result["content"]
    suggestions = [s.strip() for s in raw.split("---") if s.strip()]
    if not suggestions:
        suggestions = [raw.strip()]

    return {
        "ok": True,
        "suggestions": suggestions[:req.max_suggestions],
        "provider": result.get("provider"),
        "elapsed_ms": result.get("elapsed_ms"),
    }


@router.post("/explain")
async def ide_explain(req: IDEExplainRequest):
    """Explain selected code."""
    ctx_str = _format_code_context(req.context)
    detail_map = {
        "brief": "Give a 1-2 sentence summary.",
        "medium": "Explain what this code does, its purpose, and key logic.",
        "detailed": "Give a thorough explanation including purpose, algorithm, edge cases, complexity, and potential issues.",
    }
    detail_instruction = detail_map.get(req.detail_level, detail_map["medium"])

    system = f"You are an expert code explainer. {detail_instruction}"
    user = f"Explain this code:\n\n{ctx_str}"

    result = _call_ide_llm(system, user, req.owner_id)
    return result


@router.post("/refactor")
async def ide_refactor(req: IDERefactorRequest):
    """Refactor code according to instructions."""
    ctx_str = _format_code_context(req.context)

    system = """You are an expert code refactoring engine. Given code and instructions, return the refactored code.
Return ONLY the refactored code in a single code block. No explanations before or after."""

    user = f"""Refactor this code:

{ctx_str}

Instruction: {req.instruction}

Return the refactored code:"""

    result = _call_ide_llm(system, user, req.owner_id)
    if not result["ok"]:
        return result

    # Extract code from response (strip markdown fences if present)
    content = result["content"]
    if "```" in content:
        parts = content.split("```")
        if len(parts) >= 3:
            code_block = parts[1]
            # Remove language identifier from first line
            lines = code_block.split("\n", 1)
            if len(lines) > 1:
                content = lines[1]
            else:
                content = code_block

    return {
        "ok": True,
        "refactored_code": content.strip(),
        "provider": result.get("provider"),
        "elapsed_ms": result.get("elapsed_ms"),
    }


@router.post("/fix")
async def ide_fix(req: IDEFixRequest):
    """Fix errors in code."""
    ctx_str = _format_code_context(req.context)

    diagnostics_str = ""
    if req.error_message:
        diagnostics_str += f"\nError message: {req.error_message}"
    if req.diagnostics:
        diagnostics_str += f"\nDiagnostics: {json.dumps(req.diagnostics[:5], indent=2)}"

    system = """You are an expert code debugger. Given code with errors, return the fixed code.
Return ONLY the fixed code in a single code block, followed by a brief explanation of what you fixed."""

    user = f"""Fix the errors in this code:

{ctx_str}
{diagnostics_str}

Return the fixed code:"""

    result = _call_ide_llm(system, user, req.owner_id)
    if not result["ok"]:
        return result

    content = result["content"]
    fixed_code = content
    explanation = ""

    # Split code and explanation
    if "```" in content:
        parts = content.split("```")
        if len(parts) >= 3:
            code_block = parts[1]
            lines = code_block.split("\n", 1)
            fixed_code = lines[1] if len(lines) > 1 else code_block
            # Everything after the code block is the explanation
            explanation = "```".join(parts[2:]).strip()

    return {
        "ok": True,
        "fixed_code": fixed_code.strip(),
        "explanation": explanation,
        "provider": result.get("provider"),
        "elapsed_ms": result.get("elapsed_ms"),
    }


@router.post("/test")
async def ide_generate_test(req: IDETestRequest):
    """Generate tests for code."""
    ctx_str = _format_code_context(req.context)

    system = f"""You are an expert test writer. Generate comprehensive tests using {req.framework}.
Cover: happy path, edge cases, error handling. Return ONLY the test code in a single code block."""

    user = f"""Write tests for this code:

{ctx_str}

Generate {req.framework} tests:"""

    result = _call_ide_llm(system, user, req.owner_id)
    if not result["ok"]:
        return result

    content = result["content"]
    if "```" in content:
        parts = content.split("```")
        if len(parts) >= 3:
            code_block = parts[1]
            lines = code_block.split("\n", 1)
            content = lines[1] if len(lines) > 1 else code_block

    return {
        "ok": True,
        "test_code": content.strip(),
        "framework": req.framework,
        "provider": result.get("provider"),
        "elapsed_ms": result.get("elapsed_ms"),
    }


@router.post("/chat")
async def ide_chat(req: IDEChatRequest):
    """General chat with optional file context."""
    system = "You are Bob, an AI coding assistant integrated into the IDE. Help the developer with their code questions. Be concise and practical."

    user = req.message
    if req.context:
        ctx_str = _format_code_context(req.context)
        user = f"Context:\n{ctx_str}\n\nQuestion: {req.message}"

    result = _call_ide_llm(system, user, req.owner_id)
    return result
