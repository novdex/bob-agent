"""
Meta-Tools — bundle common tool sequences into single deterministic calls.

Instead of Bob making 5+ tool calls for common patterns,
meta-tools wrap those sequences into one call. 80% latency reduction.

Based on: "Optimizing Agentic Workflows via Meta-tools" (2026 paper)
KEY INSIGHT: Recurring tool sequences → deterministic meta-tools
→ skip unnecessary intermediate LLM reasoning steps.

Built-in meta-tools:
- research_and_save(topic) — search + read + summarise + save note
- search_and_report(query) — search + read pages + compile report
- github_and_link(topic) — GitHub research + auto-link memories
- run_and_check(command) — run command + check output + report
"""
from __future__ import annotations
import json
import logging
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.meta_tools")


def meta_research_and_save(args: dict) -> dict:
    """Search web + read top pages + summarise + save as ResearchNote."""
    owner_id = int(args.get("_owner_id", 1))
    topic = str(args.get("topic", "")).strip()
    if not topic:
        return {"ok": False, "error": "topic required"}
    from ..tools.basic import tool_search_web, tool_read_webpage, tool_save_research_note
    # Step 1: Search
    search = tool_search_web({"query": topic, "num_results": 4})
    if not search.get("ok"):
        return {"ok": False, "error": "Search failed"}
    results = search.get("results", [])[:3]
    # Step 2: Read top pages
    summaries = []
    for r in results:
        url = r.get("url", "")
        if url:
            page = tool_read_webpage({"url": url})
            if page.get("ok"):
                summaries.append(truncate_text(page.get("content", ""), 500))
            else:
                summaries.append(r.get("snippet", "")[:200])
        else:
            summaries.append(r.get("snippet", "")[:200])
    # Step 3: Save
    combined = f"Research on: {topic}\n\n" + "\n\n".join(summaries)
    save_r = tool_save_research_note({
        "_owner_id": owner_id,
        "topic": topic,
        "summary": truncate_text(combined, 3000),
        "sources": [r.get("url", "") for r in results],
        "tags": ["meta_research", topic],
    })
    return {
        "ok": True,
        "topic": topic,
        "sources_read": len(summaries),
        "note_id": save_r.get("note_id"),
        "summary_preview": truncate_text(combined, 200),
    }


def meta_github_and_link(args: dict) -> dict:
    """GitHub research + auto-link to knowledge graph in one call."""
    owner_id = int(args.get("_owner_id", 1))
    topic = str(args.get("topic", "")).strip()
    if not topic:
        return {"ok": False, "error": "topic required"}
    from .github_research import research_github_topic
    result = research_github_topic(topic, owner_id, save_notes=True)
    return result


def meta_run_and_check(args: dict) -> dict:
    """Run a shell command, check output, return structured result."""
    from ..tools.basic import tool_run_command
    command = str(args.get("command", "")).strip()
    expect_success = bool(args.get("expect_success", True))
    if not command:
        return {"ok": False, "error": "command required"}
    result = tool_run_command({"command": command, "timeout": 30})
    output = result.get("output", "")
    success = result.get("ok", False)
    return {
        "ok": True,
        "command": command,
        "success": success,
        "output": truncate_text(output, 1000),
        "check": "passed" if (success == expect_success) else "failed",
    }


def meta_search_and_report(args: dict) -> dict:
    """Multi-source search + compile into a structured report."""
    owner_id = int(args.get("_owner_id", 1))
    query = str(args.get("query", "")).strip()
    if not query:
        return {"ok": False, "error": "query required"}
    from ..tools.basic import tool_search_web
    from ..agent.llm import call_llm
    search = tool_search_web({"query": query, "num_results": 6})
    if not search.get("ok"):
        return {"ok": False, "error": "Search failed"}
    results = search.get("results", [])[:5]
    snippets = "\n".join(f"- {r.get('title','')}: {r.get('snippet','')[:150]}" for r in results)
    # Compile via LLM
    prompt = [{"role": "user", "content": f"Compile a brief report on: {query}\n\nSources:\n{snippets}\n\nWrite 3-4 sentences, cite key facts. Be specific."}]
    try:
        res = call_llm(prompt, temperature=0.3)
        report = ""
        if isinstance(res, dict) and res.get("ok"):
            report = res.get("content", "")
            choices = res.get("choices", [])
            if choices:
                report = choices[0].get("message", {}).get("content", report)
        return {"ok": True, "query": query, "report": truncate_text(report, 1000), "sources": len(results)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
