"""
Tree of Thoughts — branch multiple reasoning paths before acting.

Instead of committing to the first idea, Bob generates 3 different
approaches to a problem, evaluates each, and picks the best one.

Based on: Tree of Thoughts (Yao et al., Princeton/Google, 2023)
Proven: significantly outperforms linear chain-of-thought on complex problems.

Architecture:
1. Generate 3 different approaches to the task
2. Evaluate each: pros, cons, likelihood of success
3. Pick the highest-scoring approach
4. Proceed with that plan

Only activates on genuinely hard problems (ambiguous, multi-solution tasks).
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("mind_clone.services.tree_of_thoughts")

_TOT_KEYWORDS = {
    "best way", "how should i", "what approach", "strategy",
    "options", "alternatives", "decide", "choose", "which is better",
    "compare", "tradeoff", "pros and cons", "recommend",
}

_TOT_PROMPT = """Generate 3 different approaches to solve this problem.
For each approach give: name, key steps (2-3), and likelihood of success (high/medium/low).

Problem: {problem}

Format exactly like this:
APPROACH 1: [Name]
Steps: [step1] → [step2] → [step3]
Success: [high/medium/low]
Why: [one sentence]

APPROACH 2: [Name]
Steps: ...
Success: ...
Why: ...

APPROACH 3: [Name]
Steps: ...
Success: ...
Why: ..."""

_PICK_PROMPT = """Given these 3 approaches to solve a problem, pick the best one.

Problem: {problem}

Approaches:
{approaches}

Which approach is best and why? Reply with:
BEST: [Approach number and name]
REASON: [One sentence why]
PROCEED: [Restate the chosen approach's steps as the execution plan]"""


def needs_tree_of_thoughts(message: str) -> bool:
    """Check if this problem benefits from multi-path reasoning."""
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in _TOT_KEYWORDS)


def generate_thought_branches(problem: str) -> Optional[str]:
    """Generate 3 solution branches for a problem."""
    from ..agent.llm import call_llm
    prompt = [{"role": "user", "content": _TOT_PROMPT.format(problem=problem[:400])}]
    try:
        result = call_llm(prompt, temperature=0.7)
        content = ""
        if isinstance(result, dict) and result.get("ok"):
            content = result.get("content", "")
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", content)
        elif isinstance(result, str):
            content = result
        if content and "APPROACH" in content:
            return content.strip()[:1500]
    except Exception as e:
        logger.debug("TOT_BRANCHES_FAIL: %s", str(e)[:80])
    return None


def pick_best_thought(problem: str, branches: str) -> Optional[str]:
    """Pick the best approach from the branches."""
    from ..agent.llm import call_llm
    prompt = [{"role": "user", "content": _PICK_PROMPT.format(
        problem=problem[:300], approaches=branches[:1000]
    )}]
    try:
        result = call_llm(prompt, temperature=0.2)
        content = ""
        if isinstance(result, dict) and result.get("ok"):
            content = result.get("content", "")
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", content)
        elif isinstance(result, str):
            content = result
        if content and "BEST:" in content:
            return content.strip()[:800]
    except Exception as e:
        logger.debug("TOT_PICK_FAIL: %s", str(e)[:80])
    return None


def get_tot_block(user_message: str) -> str:
    """Return Tree of Thoughts best path as a string block."""
    if not needs_tree_of_thoughts(user_message):
        return ""
    branches = generate_thought_branches(user_message)
    if not branches:
        return ""
    best = pick_best_thought(user_message, branches)
    if not best:
        return ""
    return "[TREE OF THOUGHTS] Multiple approaches were evaluated. Proceed with the best one:\n\n" + best


def inject_tot_context(user_message: str, messages: list) -> bool:
    """Run Tree of Thoughts and inject best approach into messages.

    Returns True if injected.
    """
    if not needs_tree_of_thoughts(user_message):
        return False

    branches = generate_thought_branches(user_message)
    if not branches:
        return False

    best = pick_best_thought(user_message, branches)
    if not best:
        return False

    messages.append({
        "role": "system",
        "content": (
            "[TREE OF THOUGHTS] Multiple approaches were evaluated. "
            "Proceed with the best one:\n\n" + best
        ),
    })
    logger.info("TOT_INJECTED task=%s", user_message[:60])
    return True
