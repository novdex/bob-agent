"""
On-the-fly Tool Creation — Live-SWE-agent style.

KEY INSIGHT: Instead of waiting for the nightly experiment loop,
Bob builds new tools the moment he discovers he can't do something.

When Bob hits a capability wall mid-task:
1. Detects the gap ("I don't have a tool for X")
2. Immediately synthesizes a Python tool function
3. Tests it
4. Adds it to his tool library permanently
5. Uses it right now to complete the task

This means Bob improves DURING a task, not just at night.
Live-SWE-agent achieved 77.4% on SWE-bench (beats all models) using this.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger("mind_clone.services.tool_forge")

_GAP_PHRASES = [
    "i don't have a tool",
    "no tool available",
    "i cannot",
    "i lack the capability",
    "not currently able to",
    "i'm unable to",
    "there is no tool",
    "i don't have access to",
]

_FORGE_PROMPT = """You are creating a Python tool function for an AI agent.

The agent needs to: {capability_needed}

Write a Python function called `tool_main` that:
- Takes args: dict as input
- Returns dict with at least 'ok': bool
- Is self-contained (imports inside function body)
- Uses only standard library + requests/httpx if needed
- Handles errors gracefully with try/except

Example structure:
def tool_main(args: dict) -> dict:
    try:
        # your implementation
        result = do_something(args.get('param', ''))
        return {{'ok': True, 'result': result}}
    except Exception as e:
        return {{'ok': False, 'error': str(e)[:200]}}

Write ONLY the function, no explanations."""


def detect_capability_gap(response_text: str) -> Optional[str]:
    """Detect if Bob's response indicates a capability gap."""
    resp_lower = response_text.lower()
    for phrase in _GAP_PHRASES:
        if phrase in resp_lower:
            # Extract what capability is needed
            idx = resp_lower.find(phrase)
            context = response_text[max(0, idx-20):idx+200]
            return context.strip()
    return None


def forge_tool(
    capability_description: str,
    tool_name: str,
    owner_id: int = 1,
) -> dict:
    """Synthesize, test and register a new tool on the fly."""
    from ..agent.llm import call_llm
    from ..tools.custom import tool_create_tool

    # Generate tool code
    prompt = [{
        "role": "user",
        "content": _FORGE_PROMPT.format(capability_needed=capability_description[:300]),
    }]

    try:
        result = call_llm(prompt, temperature=0.2)
        code = ""
        if isinstance(result, dict) and result.get("ok"):
            code = result.get("content", "")
            choices = result.get("choices", [])
            if choices:
                code = choices[0].get("message", {}).get("content", code)
        elif isinstance(result, str):
            code = result

        # Clean code block fences
        code = code.strip()
        if code.startswith("```"):
            lines = code.split("\n")
            code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        code = code.strip()

        if not code or "def tool_main" not in code:
            return {"ok": False, "error": "LLM did not generate valid tool code"}

        # Register via create_tool
        r = tool_create_tool({
            "_owner_id": owner_id,
            "tool_name": tool_name,
            "description": capability_description[:200],
            "code": code,
            "parameters": json.dumps({
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "Input for the tool"}
                },
                "required": [],
            }),
            "test_args": json.dumps({}),
        })

        if r.get("ok"):
            logger.info("TOOL_FORGED name=%s", tool_name)
            return {
                "ok": True,
                "tool_name": tool_name,
                "message": f"Tool '{tool_name}' created and registered. You can now use it.",
            }
        return {"ok": False, "error": f"Tool registration failed: {r.get('error', '?')}"}

    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_forge_tool(args: dict) -> dict:
    """Tool: Synthesize and register a new capability on the fly when Bob can't do something."""
    owner_id = int(args.get("_owner_id", 1))
    capability = str(args.get("capability", "")).strip()
    name = str(args.get("tool_name", "")).strip()

    if not capability:
        return {"ok": False, "error": "capability description is required"}
    if not name:
        import re
        name = re.sub(r"[^a-z0-9_]", "_", capability.lower())[:40]

    return forge_tool(capability, name, owner_id)
