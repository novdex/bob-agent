"""
DeerFlow-style Deep Multi-Agent Research Pipeline.

Orchestrates a pipeline of specialised LLM agents:
  Planner -> Researcher (parallel) -> Writer -> Reviewer
with optional revision loop to guarantee quality.

Each agent is a focused call_llm invocation with a role-specific
system prompt.  Researcher agents run in parallel via
ThreadPoolExecutor to minimise wall-clock time.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from ..agent.llm import call_llm
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.deep_research")

# ---------------------------------------------------------------------------
# Internal agent helpers
# ---------------------------------------------------------------------------

_PLANNER_SYSTEM = (
    "You are a research planner. Given a topic, break it into 3-5 specific, "
    "non-overlapping research questions that together provide comprehensive "
    "coverage. Respond ONLY with a JSON array of question strings, e.g. "
    '["question 1", "question 2", ...]'
)

_WRITER_SYSTEM = (
    "You are a research writer. Given research findings for several questions, "
    "synthesize them into a single comprehensive, well-structured report. "
    "Use clear headings, bullet points where appropriate, and cite sources "
    "where available. Write in a clear, factual tone."
)

_REVIEWER_SYSTEM = (
    "You are a research reviewer. Evaluate the report for:\n"
    "1. Accuracy — are claims supported by the provided sources?\n"
    "2. Completeness — are all research questions adequately addressed?\n"
    "3. Clarity — is the writing clear and well-organised?\n"
    "4. Quality — overall quality of the report.\n\n"
    "Respond ONLY with a JSON object: "
    '{"score": <int 1-10>, "feedback": "<specific improvement suggestions>"}'
)


def _run_planner(topic: str) -> List[str]:
    """Use the PLANNER agent to decompose *topic* into research questions.

    Returns:
        List of 3-5 research question strings.
    """
    messages = [
        {"role": "system", "content": _PLANNER_SYSTEM},
        {"role": "user", "content": f"Topic: {topic}"},
    ]
    result = call_llm(messages, temperature=0.4)
    content = result.get("content", "") if result.get("ok") else ""

    # Parse JSON array from response
    try:
        # Handle markdown code fences if present
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        questions = json.loads(cleaned)
        if isinstance(questions, list) and len(questions) >= 1:
            return questions[:5]
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Planner returned non-JSON; falling back to split.")

    # Fallback: split on newlines
    lines = [ln.strip().lstrip("0123456789.-) ") for ln in content.splitlines() if ln.strip()]
    return lines[:5] if lines else [topic]


def _research_question(question: str) -> Dict[str, Any]:
    """Use the RESEARCHER agent: search web for *question*, return findings.

    Returns:
        Dict with keys: question, snippets (list), sources (list).
    """
    from ..tools.basic import tool_search_web

    search_result = tool_search_web({"query": question, "num_results": 5})
    snippets: List[str] = []
    sources: List[str] = []

    if search_result.get("ok"):
        for item in search_result.get("results", []):
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            url = item.get("url", "")
            if snippet:
                snippets.append(f"{title}: {snippet}")
            if url:
                sources.append(url)

    return {
        "question": question,
        "snippets": snippets,
        "sources": sources,
    }


def _run_writer(topic: str, findings: List[Dict[str, Any]], feedback: str = "") -> str:
    """Use the WRITER agent to synthesize research *findings* into a report.

    Args:
        topic: The original research topic.
        findings: List of dicts from ``_research_question``.
        feedback: Optional reviewer feedback for a revision pass.

    Returns:
        Report text (str).
    """
    # Build a structured summary of findings for the writer
    findings_text_parts: List[str] = []
    for f in findings:
        q = f.get("question", "")
        snips = f.get("snippets", [])
        srcs = f.get("sources", [])
        part = f"### {q}\n"
        for s in snips:
            part += f"- {s}\n"
        if srcs:
            part += "Sources: " + ", ".join(srcs[:3]) + "\n"
        findings_text_parts.append(part)
    findings_text = "\n".join(findings_text_parts)

    user_prompt = (
        f"Topic: {topic}\n\n"
        f"Research Findings:\n{truncate_text(findings_text, 6000)}"
    )
    if feedback:
        user_prompt += (
            f"\n\n--- REVIEWER FEEDBACK (please address these issues) ---\n{feedback}"
        )

    messages = [
        {"role": "system", "content": _WRITER_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]
    result = call_llm(messages, temperature=0.3)
    return result.get("content", "") if result.get("ok") else "[Writer failed to produce report]"


def _run_reviewer(report: str) -> Dict[str, Any]:
    """Use the REVIEWER agent to score and critique *report*.

    Returns:
        Dict with keys: score (int), feedback (str).
    """
    messages = [
        {"role": "system", "content": _REVIEWER_SYSTEM},
        {"role": "user", "content": f"Report to review:\n\n{truncate_text(report, 6000)}"},
    ]
    result = call_llm(messages, temperature=0.2)
    content = result.get("content", "") if result.get("ok") else ""

    try:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(cleaned)
        score = int(parsed.get("score", 5))
        feedback = str(parsed.get("feedback", ""))
        return {"score": max(1, min(10, score)), "feedback": feedback}
    except (json.JSONDecodeError, TypeError, ValueError, KeyError):
        logger.warning("Reviewer returned non-JSON; defaulting score to 6.")
        return {"score": 6, "feedback": content}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_deep_research(topic: str, owner_id: int = 1) -> dict:
    """Run the full DeerFlow-style deep research pipeline.

    Pipeline stages:
      1. PLANNER — breaks topic into 3-5 research questions
      2. RESEARCHER — searches web for each question IN PARALLEL
      3. WRITER — synthesizes findings into a comprehensive report
      4. REVIEWER — scores report 1-10 and gives feedback
      5. If score < 7 — sends back to writer with feedback (max 1 revision)

    Args:
        topic: The research topic / question.
        owner_id: Owner identifier (default 1).

    Returns:
        Dict with keys: ok, report, score, questions, sources.
    """
    try:
        logger.info("Deep research started: %s", topic[:80])

        # 1. PLANNER
        questions = _run_planner(topic)
        logger.info("Planner produced %d questions", len(questions))

        # 2. RESEARCHER (parallel)
        all_findings: List[Dict[str, Any]] = []
        all_sources: List[str] = []
        with ThreadPoolExecutor(max_workers=min(len(questions), 5)) as pool:
            futures = {
                pool.submit(_research_question, q): q for q in questions
            }
            for future in as_completed(futures):
                try:
                    finding = future.result(timeout=60)
                    all_findings.append(finding)
                    all_sources.extend(finding.get("sources", []))
                except Exception as exc:
                    q = futures[future]
                    logger.warning("Researcher failed for '%s': %s", q[:50], exc)
                    all_findings.append({"question": q, "snippets": [], "sources": []})

        logger.info("Researchers returned %d findings", len(all_findings))

        # 3. WRITER (first pass)
        report = _run_writer(topic, all_findings)

        # 4. REVIEWER
        review = _run_reviewer(report)
        score = review["score"]
        logger.info("Reviewer scored report: %d/10", score)

        # 5. REVISION (if score < 7, max 1 revision)
        if score < 7:
            logger.info("Score below 7 — requesting revision")
            report = _run_writer(topic, all_findings, feedback=review["feedback"])
            review = _run_reviewer(report)
            score = review["score"]
            logger.info("Post-revision score: %d/10", score)

        # De-duplicate sources
        unique_sources = list(dict.fromkeys(all_sources))

        return {
            "ok": True,
            "report": report,
            "score": score,
            "questions": questions,
            "sources": unique_sources,
        }

    except Exception as e:
        logger.error("Deep research pipeline failed: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)[:300]}


def tool_deep_research(args: dict) -> dict:
    """Tool wrapper for deep research pipeline.

    Args:
        args: Dict with key ``topic`` (str).

    Returns:
        Pipeline result dict.
    """
    if not isinstance(args, dict):
        return {"ok": False, "error": "args must be a dict"}

    topic = str(args.get("topic", "")).strip()
    if not topic:
        return {"ok": False, "error": "topic is required"}
    if len(topic) > 1000:
        return {"ok": False, "error": "topic is too long (max 1000 chars)"}

    return run_deep_research(topic)
