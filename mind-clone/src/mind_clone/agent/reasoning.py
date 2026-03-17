"""Reasoning Engine - structured multi-step reasoning. Pillar: Reasoning."""
from __future__ import annotations
import logging
from typing import Optional
from ..core.state import increment_runtime_state, set_runtime_state_value
logger = logging.getLogger("mind_clone.agent.reasoning")
STRATEGIES = ("direct", "chain_of_thought", "decompose", "analogy", "debate")

def select_reasoning_strategy(user_message: str) -> str:
    if not user_message: return "direct"
    m, wc = user_message.lower(), len(user_message.split())
    if any(s in m for s in ("step by step","break down","analyze","compare","evaluate")): return "decompose"
    if any(s in m for s in ("why","how does","explain","calculate","predict")) and wc >= 5: return "chain_of_thought"
    if "like" in m and ("similar" in m or "analogy" in m): return "analogy"
    return "decompose" if wc >= 30 else "direct"

def build_reasoning_prefix(strategy: str, user_message: str) -> Optional[str]:
    if strategy == "direct": return None
    return {"chain_of_thought":"[REASONING: CoT] Think step-by-step.","decompose":"[REASONING: Decompose] Break into sub-problems.","analogy":"[REASONING: Analogy] Find familiar analogy.","debate":"[REASONING: Debate] Consider multiple perspectives."}.get(strategy)

def track_reasoning_metrics(strategy: str, depth: int = 1) -> None:
    increment_runtime_state("reasoning_chains_total")
    set_runtime_state_value("reasoning_last_strategy", strategy)
    from ..core.state import RUNTIME_STATE, RUNTIME_STATE_LOCK
    with RUNTIME_STATE_LOCK:
        total = RUNTIME_STATE.get("reasoning_chains_total", 1)
        old = RUNTIME_STATE.get("reasoning_avg_depth", 0.0)
        RUNTIME_STATE["reasoning_avg_depth"] = round(old + (depth - old) / max(total, 1), 2)
