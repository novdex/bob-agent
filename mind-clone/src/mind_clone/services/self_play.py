"""
Self-Play — Bob debates itself to improve responses.

Bob generates a response, then plays devil's advocate against it,
then writes a final improved version. Meta AI technique (used in CICERO).

Only on complex analytical questions — not simple tasks.
"""
from __future__ import annotations
import logging
logger = logging.getLogger("mind_clone.services.self_play")

_DEBATE_KEYWORDS = {"is it", "should i", "what do you think", "opinion", "evaluate",
                    "assess", "worth it", "better or worse", "pros and cons"}


def needs_self_play(message: str) -> bool:
    msg = message.lower()
    return any(k in msg for k in _DEBATE_KEYWORDS) and len(message.split()) > 6


def self_play_improve(user_message: str, initial_response: str) -> str:
    """Generate a devil's advocate critique then improved final response."""
    from ..agent.llm import call_llm
    if not needs_self_play(user_message):
        return initial_response

    # Devil's advocate
    critique_prompt = [{"role": "user", "content":
        f"Play devil's advocate against this response. Find the strongest counterarguments.\n"
        f"Question: {user_message[:200]}\nResponse: {initial_response[:600]}\n"
        f"List 2 strongest counterpoints. Be brief."}]
    try:
        r = call_llm(critique_prompt, temperature=0.5)
        critique = ""
        if isinstance(r, dict) and r.get("ok"):
            critique = r.get("content", "")
            choices = r.get("choices", [])
            if choices:
                critique = choices[0].get("message", {}).get("content", critique)
        if not critique or len(critique) < 20:
            return initial_response

        # Final balanced response
        final_prompt = [{"role": "user", "content":
            f"Write a final balanced response that addresses these counterpoints.\n"
            f"Original answer: {initial_response[:400]}\nCounterpoints: {critique[:300]}\n"
            f"Write a nuanced, complete response. Keep it concise."}]
        r2 = call_llm(final_prompt, temperature=0.4)
        final = ""
        if isinstance(r2, dict) and r2.get("ok"):
            final = r2.get("content", "")
            choices = r2.get("choices", [])
            if choices:
                final = choices[0].get("message", {}).get("content", final)
        if final and len(final) > 50:
            logger.info("SELF_PLAY_IMPROVED task=%s", user_message[:50])
            return final.strip()
    except Exception as e:
        logger.debug("SELF_PLAY_FAIL: %s", str(e)[:80])
    return initial_response
