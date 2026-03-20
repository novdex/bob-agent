"""
GitHub Research System — Bob autonomously researches top projects.

Bob can search GitHub for repos relevant to any topic, read their
READMEs and code patterns, extract key insights, and store them as
linked ResearchNotes in his knowledge graph.

Used to:
- Research best practices before implementing something
- Find libraries/tools for a task
- Learn from top open-source projects
- Inform the Karpathy experiment loop with real-world patterns

No GitHub API key needed — uses public search via web tools.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from ..database.models import ResearchNote
from ..database.session import SessionLocal
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.github_research")

_MAX_REPOS = 5
_MAX_README_CHARS = 3000


def search_github_repos(query: str, limit: int = 5) -> list[dict]:
    """Search GitHub for top repos matching query via web search."""
    from ..tools.basic import tool_search_web
    results = tool_search_web({
        "query": f"site:github.com {query} stars",
        "num_results": min(limit * 2, 10),
    })
    repos = []
    if not results.get("ok"):
        return repos

    for r in results.get("results", [])[:limit]:
        url = r.get("url", "")
        if "github.com" in url and url.count("/") >= 4:
            # Extract owner/repo
            parts = url.replace("https://github.com/", "").split("/")
            if len(parts) >= 2:
                repos.append({
                    "url": f"https://github.com/{parts[0]}/{parts[1]}",
                    "owner": parts[0],
                    "repo": parts[1],
                    "title": r.get("title", ""),
                    "snippet": r.get("snippet", "")[:300],
                })
    return repos[:limit]


def fetch_repo_readme(owner: str, repo: str) -> str:
    """Fetch README content from GitHub."""
    from ..tools.basic import tool_read_webpage
    # Try raw README first
    for branch in ["main", "master"]:
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"
        result = tool_read_webpage({"url": url})
        if result.get("ok") and result.get("content"):
            content = result["content"]
            if len(content) > 100:
                return truncate_text(content, _MAX_README_CHARS)
    return ""


def extract_key_insights(repo_name: str, readme: str, snippet: str) -> str:
    """Use LLM to extract key insights from a repo README."""
    from ..agent.llm import call_llm
    if not readme and not snippet:
        return snippet

    content = readme or snippet
    prompt = [{
        "role": "user",
        "content": (
            f"Extract the 3 most important technical insights from this GitHub repo README.\n"
            f"Repo: {repo_name}\n\n"
            f"README (excerpt):\n{content[:2000]}\n\n"
            f"Return 3 bullet points, each one sentence. Focus on architecture, "
            f"key techniques, and what makes it noteworthy. Be specific."
        ),
    }]
    try:
        result = call_llm(prompt, temperature=0.3)
        insights = ""
        if isinstance(result, dict) and result.get("ok"):
            insights = result.get("content", "")
            choices = result.get("choices", [])
            if choices:
                insights = choices[0].get("message", {}).get("content", insights)
        elif isinstance(result, str):
            insights = result
        return truncate_text(insights.strip(), 500)
    except Exception:
        return snippet[:300]


def research_github_topic(
    topic: str,
    owner_id: int = 1,
    save_notes: bool = True,
) -> dict:
    """Research a GitHub topic: search → read → extract → store as ResearchNotes."""
    logger.info("GITHUB_RESEARCH topic=%s", topic[:60])

    repos = search_github_repos(topic, limit=_MAX_REPOS)
    if not repos:
        return {"ok": False, "error": "No GitHub repos found", "topic": topic}

    saved_notes = []
    for repo in repos:
        owner, name = repo["owner"], repo["repo"]
        readme = fetch_repo_readme(owner, name)
        insights = extract_key_insights(f"{owner}/{name}", readme, repo["snippet"])

        if save_notes and insights:
            db = SessionLocal()
            try:
                note = ResearchNote(
                    owner_id=owner_id,
                    topic=f"GitHub: {owner}/{name}",
                    summary=insights,
                    sources_json=json.dumps([repo["url"]]),
                    tags_json=json.dumps(["github", topic, owner, name]),
                )
                db.add(note)
                db.commit()
                db.refresh(note)

                # Auto-link to related memories
                try:
                    from .memory_graph import auto_link
                    auto_link(db, owner_id, "research_note", note.id)
                except Exception:
                    pass

                saved_notes.append({
                    "repo": f"{owner}/{name}",
                    "url": repo["url"],
                    "note_id": note.id,
                    "insights_preview": insights[:100],
                })
            except Exception as e:
                logger.error("GITHUB_RESEARCH_SAVE_FAIL: %s", e)
            finally:
                db.close()

    return {
        "ok": True,
        "topic": topic,
        "repos_found": len(repos),
        "notes_saved": len(saved_notes),
        "notes": saved_notes,
    }


def tool_research_github(args: dict) -> dict:
    """Tool: Search GitHub for top repos on a topic, extract insights, save as ResearchNotes."""
    owner_id = int(args.get("_owner_id", 1))
    topic = str(args.get("topic", "")).strip()
    if not topic:
        return {"ok": False, "error": "topic is required"}
    save = bool(args.get("save_notes", True))
    return research_github_topic(topic, owner_id, save_notes=save)
