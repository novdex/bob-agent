"""
SSE streaming endpoint for real-time LLM responses.

POST /api/stream streams tokens as Server-Sent Events so clients see
responses in real-time instead of waiting 30-120s for full completion.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Generator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...config import settings
from ...agent.llm import call_llm_stream
from ...agent.memory import (
    prepare_messages_for_llm,
    save_user_message,
    save_assistant_message,
    trim_context_window,
)
from ...agent.identity import load_identity
from ...agent.loop import build_system_prompt, _sanitize_tool_pairs
from ...database.session import SessionLocal
from ...core.state import RUNTIME_STATE

logger = logging.getLogger("mind_clone.api.stream")

router = APIRouter()


class StreamRequest(BaseModel):
    """Request body for the streaming endpoint."""
    message: str = Field(..., min_length=1, max_length=32000)
    owner_id: int = Field(default=1, ge=1)
    model: str | None = Field(default=None)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=131072)


def _sse_event(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _generate_sse_stream(
    owner_id: int,
    user_message: str,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Generator[str, None, None]:
    """Build context and stream LLM response as SSE events."""
    stream_start = time.monotonic()
    db = SessionLocal()
    try:
        save_user_message(db, owner_id, user_message)

        identity = load_identity(db, owner_id)
        system_prompt = build_system_prompt(identity)

        messages = prepare_messages_for_llm(
            db, owner_id, recent_limit=settings.conversation_history_limit,
        )
        messages = _sanitize_tool_pairs(messages)

        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = system_prompt
        else:
            messages.insert(0, {"role": "system", "content": system_prompt})

        try:
            messages = trim_context_window(
                messages, max_chars=settings.session_soft_trim_char_budget,
            )
        except Exception:
            pass
        messages = _sanitize_tool_pairs(messages)

        full_response = ""
        token_count = 0

        for chunk in call_llm_stream(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            if chunk.get("error"):
                yield _sse_event({"token": "", "done": True, "error": chunk["error"]})
                return

            if not chunk.get("done"):
                token_count += 1
                yield _sse_event({"token": chunk.get("token", ""), "done": False})
            else:
                full_response = chunk.get("full_response", "")
                elapsed_ms = int((time.monotonic() - stream_start) * 1000)
                yield _sse_event({
                    "token": "",
                    "done": True,
                    "full_response": full_response,
                    "tokens_streamed": token_count,
                    "elapsed_ms": elapsed_ms,
                })

        if full_response:
            save_assistant_message(db, owner_id, full_response)
            RUNTIME_STATE["stream_requests_total"] = (
                int(RUNTIME_STATE.get("stream_requests_total", 0)) + 1
            )

    except Exception as exc:
        logger.error("SSE stream error: %s: %s", type(exc).__name__, str(exc)[:300])
        yield _sse_event({
            "token": "", "done": True,
            "error": f"Stream error: {type(exc).__name__}: {str(exc)[:200]}",
        })
    finally:
        db.close()


@router.post("/api/stream")
async def stream_chat(req: StreamRequest):
    """Stream LLM response as Server-Sent Events.

    Progress: ``{"token": "Hello", "done": false}``
    Final: ``{"token": "", "done": true, "full_response": "...", "tokens_streamed": N, "elapsed_ms": N}``
    Error: ``{"token": "", "done": true, "error": "..."}``
    """
    return StreamingResponse(
        _generate_sse_stream(
            owner_id=req.owner_id,
            user_message=req.message,
            model=req.model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
