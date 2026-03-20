"""
ReAct + Reflection — structured observe/reason/act/reflect cycle.

After completing any multi-step task, Bob reflects:
- What did I observe?
- What did I reason?
- What did I do?
- What would I do differently?

Stored as episodic memory with high importance.
Based on ReAct (Yao et al., 2022) + reflection loop.
"""
from __future__ import annotations
import json
import logging
import threading
from ..database.session import SessionLocal
from ..database.models import EpisodicMemory
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.react_reflect")


def reflect_after_task(
    owner_id: int,
    user_message: str,
    final_response: str,
    tool_calls_made: list,
) -> None:
    """Generate and store a ReAct reflection after a multi-step task."""
    if len(tool_calls_made) < 2:
        return  # Only reflect on multi-step tasks

    def _run():
        try:
            from ..agent.llm import call_llm
            tools_summary = ", ".join(str(t) for t in tool_calls_made[:5])
            prompt = [{"role": "user", "content":
                f"Write a brief ReAct reflection for this completed task.\n"
                f"Task: {user_message[:200]}\n"
                f"Tools used: {tools_summary}\n"
                f"Result: {final_response[:200]}\n\n"
                f"Format:\n"
                f"OBSERVE: [what I noticed]\n"
                f"REASON: [my reasoning]\n"
                f"ACT: [what I did]\n"
                f"REFLECT: [what I'd do better next time]\n"
                f"Keep each line to 1 sentence."}]
            result = call_llm(prompt, temperature=0.2)
            reflection = ""
            if isinstance(result, dict) and result.get("ok"):
                reflection = result.get("content", "")
                choices = result.get("choices", [])
                if choices:
                    reflection = choices[0].get("message", {}).get("content", reflection)
            elif isinstance(result, str):
                reflection = result

            if not reflection or len(reflection) < 30:
                return

            # Save as high-importance episodic memory
            db = SessionLocal()
            try:
                ep = EpisodicMemory(
                    owner_id=owner_id,
                    situation=truncate_text(user_message, 200),
                    action_taken=truncate_text(f"Used tools: {tools_summary}", 200),
                    outcome="success",
                    outcome_detail=truncate_text(reflection, 500),
                    tools_used_json=json.dumps(tool_calls_made[:5]),
                    source_type="react_reflect",
                    importance=0.8,  # High importance — structured reflection
                )
                db.add(ep); db.commit()
                logger.info("REACT_REFLECT_SAVED owner=%d", owner_id)
            finally:
                db.close()
        except Exception as e:
            logger.debug("REACT_REFLECT_FAIL: %s", str(e)[:80])

    threading.Thread(target=_run, daemon=True).start()
