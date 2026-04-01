"""
Self-Improvement Engine — Bob fixes his own code.

This module is the MAIN self-improvement service.  It includes:
  - Code-based self-improvement (read notes, find code, patch, test) [original]
  - Safe nightly improvement (no code edits, skills+config+plugins)  [merged from safe_improve]
  - Self-play debate refinement                                      [merged from self_play]
  - Self-testing (auto-generate & run tests)                         [merged from self_tester]

Dangerous code-rewriting is gated behind SELF_IMPROVE_ENABLED.
The safe nightly path NEVER touches source code.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..database.session import SessionLocal
from ..database.models import SelfImprovementNote
from ..utils import truncate_text

logger = logging.getLogger("mind_clone.services.self_improve")

SELF_IMPROVE_ENABLED: bool = os.getenv("SELF_IMPROVE_ENABLED", "true").lower() in {"1", "true", "yes"}
BOB_CODEBASE_PATH = os.getenv("BOB_CODEBASE_PATH", r"C:\projects\ai-agent-platform\mind-clone")


def get_top_improvement_opportunity(owner_id: int) -> Optional[Dict[str, Any]]:
    """Get the highest priority open SelfImprovementNote."""
    db = SessionLocal()
    try:
        priority_order = {"high": 0, "medium": 1, "low": 2}
        notes = (
            db.query(SelfImprovementNote)
            .filter(
                SelfImprovementNote.owner_id == owner_id,
                SelfImprovementNote.status == "open",
            )
            .order_by(SelfImprovementNote.created_at.desc())
            .limit(20)
            .all()
        )
        if not notes:
            return None

        notes.sort(key=lambda n: priority_order.get(n.priority, 1))
        n = notes[0]

        import json
        actions = []
        try:
            actions = json.loads(n.actions_json or "[]")
        except Exception:
            pass

        return {
            "id": n.id,
            "title": n.title,
            "summary": n.summary,
            "actions": actions,
            "priority": n.priority,
        }
    finally:
        db.close()


def mark_note_resolved(note_id: int, resolution: str) -> bool:
    """Mark a SelfImprovementNote as resolved."""
    db = SessionLocal()
    try:
        note = db.query(SelfImprovementNote).filter(SelfImprovementNote.id == note_id).first()
        if not note:
            return False
        note.status = "resolved"
        note.summary = note.summary + f"\n\n[RESOLVED] {truncate_text(resolution, 300)}"
        db.commit()
        logger.info("SELF_IMPROVE_RESOLVED note_id=%d", note_id)
        return True
    except Exception as e:
        db.rollback()
        logger.warning("SELF_IMPROVE_MARK_FAIL: %s", str(e)[:200])
        return False
    finally:
        db.close()


def build_self_improve_prompt(opportunity: Dict[str, Any]) -> str:
    """Build a prompt for Bob to attempt self-improvement."""
    actions_str = "\n".join(f"  - {a}" for a in opportunity.get("actions", [])[:3])
    return f"""You have identified this improvement opportunity in yourself:

Title: {opportunity['title']}
Priority: {opportunity['priority']}
Summary: {opportunity['summary'][:500]}

Suggested actions:
{actions_str or '  - Review and fix the underlying issue'}

Your task:
1. Use `codebase_search` to find the relevant code in your own codebase at {BOB_CODEBASE_PATH}
2. Analyse the issue
3. Use `codebase_edit` or `codebase_write` to fix it
4. Use `codebase_run_tests` to verify the fix doesn't break anything
5. Use `git_commit` to commit if tests pass
6. Report what you fixed

Be careful. Only make targeted, minimal changes. Do not refactor broadly.
If you cannot safely fix it, explain why and what would be needed."""


def tool_self_improve(args: dict) -> dict:
    """Tool: Bob attempts to fix his top self-improvement opportunity."""
    if not SELF_IMPROVE_ENABLED:
        return {"ok": False, "error": "Self-improvement disabled"}

    owner_id = int(args.get("_owner_id", 1))

    opportunity = get_top_improvement_opportunity(owner_id)
    if not opportunity:
        return {"ok": True, "message": "No open improvement opportunities found. Bob is in good shape."}

    prompt = build_self_improve_prompt(opportunity)

    # Run through the agent loop so Bob can use his codebase tools
    try:
        from ..agent.loop import run_agent_loop
        result = run_agent_loop(owner_id, prompt)
        return {
            "ok": True,
            "opportunity": opportunity["title"],
            "result": truncate_text(result, 1000),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


# ===========================================================================
# Safe Nightly Improvement (merged from safe_improve.py)
# ===========================================================================
# Instead of modifying Bob's source code, the nightly improvement cycle:
# 1. Reviews performance (retro)
# 2. Creates new skills from successful patterns
# 3. Auto-tunes config based on performance data
# 4. Loads/reloads plugins
# 5. Sends improvement report to Telegram
# 6. NEVER touches source code
# ===========================================================================


def _get_tool_performance_stats(owner_id: int, hours: int = 24) -> dict[str, Any]:
    """Collect tool performance statistics for the given time window.

    Args:
        owner_id: The owner/user ID to pull stats for.
        hours: Number of hours to look back.

    Returns:
        Dict with per-tool success rates and overall stats.
    """
    try:
        from ..database.models import ToolPerformanceLog

        db = SessionLocal()
        try:
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
            rows = (
                db.query(ToolPerformanceLog)
                .filter(
                    ToolPerformanceLog.owner_id == owner_id,
                    ToolPerformanceLog.created_at >= since,
                )
                .all()
            )

            tool_stats: dict[str, dict[str, int]] = {}
            for row in rows:
                name = row.tool_name
                if name not in tool_stats:
                    tool_stats[name] = {"total": 0, "success": 0, "fail": 0}
                tool_stats[name]["total"] += 1
                if row.success:
                    tool_stats[name]["success"] += 1
                else:
                    tool_stats[name]["fail"] += 1

            return {
                "ok": True,
                "tool_stats": tool_stats,
                "total_calls": sum(s["total"] for s in tool_stats.values()),
                "total_tools": len(tool_stats),
                "period_hours": hours,
            }
        finally:
            db.close()
    except Exception as exc:
        logger.error("PERF_STATS_FAIL owner=%d error=%s", owner_id, str(exc)[:200])
        return {"ok": False, "error": str(exc)[:300], "tool_stats": {}}


def _identify_failure_patterns(
    tool_stats: dict[str, dict[str, int]],
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """Identify the top N failure patterns from tool stats.

    Args:
        tool_stats: Per-tool stats dict from _get_tool_performance_stats.
        top_n: Number of top failure patterns to return.

    Returns:
        List of dicts with tool_name, success_rate, total, and fail count.
    """
    patterns: list[dict[str, Any]] = []

    for tool_name, stats in tool_stats.items():
        total = stats["total"]
        if total < 2:
            continue
        success_rate = stats["success"] / total
        if success_rate < 0.8:  # Any tool below 80% is noteworthy
            patterns.append({
                "tool_name": tool_name,
                "success_rate": round(success_rate, 2),
                "total": total,
                "failures": stats["fail"],
            })

    # Sort by failure count descending
    patterns.sort(key=lambda p: p["failures"], reverse=True)
    return patterns[:top_n]


def _create_skills_from_failures(
    failure_patterns: list[dict[str, Any]],
) -> list[str]:
    """Create markdown skills to help Bob handle failure patterns better.

    For each failure pattern, creates a skill that teaches Bob an
    alternative approach or recovery strategy.

    Args:
        failure_patterns: List of failure pattern dicts.

    Returns:
        List of skill names that were created.
    """
    from .skills import create_skill

    created: list[str] = []

    skill_templates: dict[str, dict[str, Any]] = {
        "search_web": {
            "name": "recover_search_failure",
            "triggers": ["search failed", "web search error", "search timeout"],
            "description": "Recovery procedure when web search fails",
            "steps": (
                "## Recovery Steps for Search Failures\n"
                "1. Check if the query is too long — shorten to key terms\n"
                "2. Try an alternative search with simpler keywords\n"
                "3. If still failing, try read_webpage on a known reliable source\n"
                "4. If all web access fails, use cached knowledge and inform the user\n"
                "5. Log the failure pattern for future reference"
            ),
        },
        "read_webpage": {
            "name": "recover_webpage_failure",
            "triggers": ["webpage error", "page load failed", "url error"],
            "description": "Recovery procedure when webpage reading fails",
            "steps": (
                "## Recovery Steps for Webpage Failures\n"
                "1. Check if the URL is valid and accessible\n"
                "2. Try the URL without query parameters\n"
                "3. Try an alternative source for the same information\n"
                "4. If the site blocks bots, try search_web for cached versions\n"
                "5. Inform the user about the access issue"
            ),
        },
        "execute_python": {
            "name": "recover_python_execution",
            "triggers": ["python error", "execution failed", "code error"],
            "description": "Recovery procedure when Python execution fails",
            "steps": (
                "## Recovery Steps for Python Execution Failures\n"
                "1. Review the error message carefully\n"
                "2. Check for missing imports or dependencies\n"
                "3. Simplify the code to isolate the issue\n"
                "4. Try running in sandbox_python instead\n"
                "5. If persistent, break the task into smaller steps"
            ),
        },
        "deep_research": {
            "name": "recover_deep_research",
            "triggers": ["research failed", "deep research error"],
            "description": "Recovery procedure when deep research fails",
            "steps": (
                "## Recovery Steps for Deep Research Failures\n"
                "1. Break the research question into smaller sub-questions\n"
                "2. Use search_web for each sub-question separately\n"
                "3. Use read_webpage on specific known sources\n"
                "4. Synthesise partial results into a coherent answer\n"
                "5. Clearly mark gaps and uncertainties"
            ),
        },
    }

    # Generic fallback template for unknown tools
    generic_template = {
        "triggers": ["tool error", "tool failed"],
        "description": "Generic recovery procedure for tool failures",
        "steps": (
            "## Generic Recovery Steps\n"
            "1. Read the error message and identify the root cause\n"
            "2. Check if inputs are valid and well-formatted\n"
            "3. Try the operation with simpler inputs\n"
            "4. Try an alternative tool that achieves the same goal\n"
            "5. If stuck, report the issue clearly to the user"
        ),
    }

    for pattern in failure_patterns:
        tool_name = pattern["tool_name"]

        if tool_name in skill_templates:
            template = skill_templates[tool_name]
        else:
            template = {
                "name": f"recover_{tool_name.replace(' ', '_')}",
                "triggers": generic_template["triggers"] + [tool_name],
                "description": f"Recovery procedure when {tool_name} fails",
                "steps": generic_template["steps"].replace(
                    "Generic Recovery", f"{tool_name} Recovery"
                ),
            }

        skill_name = template.get("name", f"recover_{tool_name}")
        try:
            success = create_skill(
                name=str(skill_name),
                triggers=template["triggers"],
                description=template["description"],
                steps=template["steps"],
            )
            if success:
                created.append(str(skill_name))
                logger.info(
                    "SAFE_IMPROVE_SKILL_CREATED name=%s for_tool=%s",
                    skill_name, tool_name,
                )
        except Exception as exc:
            logger.warning(
                "SAFE_IMPROVE_SKILL_FAIL name=%s error=%s",
                skill_name, str(exc)[:200],
            )

    return created


async def _send_improvement_report(owner_id: int, report: str) -> bool:
    """Send the improvement report to Telegram.

    Args:
        owner_id: The owner ID (used as chat_id for Telegram).
        report: The formatted report text.

    Returns:
        True if sent successfully, False otherwise.
    """
    try:
        from ..services.telegram.messaging import send_telegram_message
        await send_telegram_message(str(owner_id), report)
        logger.info("SAFE_IMPROVE_REPORT_SENT owner=%d", owner_id)
        return True
    except Exception as exc:
        logger.warning(
            "SAFE_IMPROVE_REPORT_FAIL owner=%d error=%s",
            owner_id, str(exc)[:200],
        )
        return False


def run_safe_improvement(owner_id: int) -> dict[str, Any]:  # DEAD CODE: not imported anywhere outside this file (tool_safe_improve is registered in registry but this function is internal)
    """Run the full safe nightly improvement cycle.

    This replaces the dangerous code-rewriting experiment with:
    a. Load tool performance stats
    b. Identify top 3 failure patterns
    c. For each failure: create a skill teaching Bob to handle it better
    d. Auto-tune config if needed
    e. Load/reload plugins
    f. Send report to Telegram
    g. Return summary

    NEVER touches source code.

    Args:
        owner_id: The owner/user ID to run improvement for.

    Returns:
        Dict with full improvement summary.
    """
    logger.info("SAFE_IMPROVE_START owner=%d", owner_id)
    summary: dict[str, Any] = {
        "ok": True,
        "owner_id": owner_id,
        "steps": {},
    }

    # Step A: Load performance stats
    perf = _get_tool_performance_stats(owner_id)
    summary["steps"]["performance"] = {
        "total_calls": perf.get("total_calls", 0),
        "total_tools": perf.get("total_tools", 0),
    }

    # Step B: Identify failure patterns
    tool_stats = perf.get("tool_stats", {})
    failures = _identify_failure_patterns(tool_stats)
    summary["steps"]["failure_patterns"] = failures

    # Step C: Create skills from failures
    skills_created: list[str] = []
    if failures:
        skills_created = _create_skills_from_failures(failures)
    summary["steps"]["skills_created"] = skills_created

    # Step D: Auto-tune config
    try:
        from .config_tuner import auto_tune_from_performance
        tune_result = auto_tune_from_performance(owner_id)
        summary["steps"]["config_tuning"] = tune_result.get("changes", [])
    except Exception as exc:
        logger.warning("SAFE_IMPROVE_TUNE_FAIL: %s", str(exc)[:200])
        summary["steps"]["config_tuning"] = {"error": str(exc)[:200]}

    # Step E: Load/reload plugins
    try:
        from .plugin_loader import load_plugins
        plugin_result = load_plugins()
        summary["steps"]["plugins"] = plugin_result
    except Exception as exc:
        logger.warning("SAFE_IMPROVE_PLUGINS_FAIL: %s", str(exc)[:200])
        summary["steps"]["plugins"] = {"error": str(exc)[:200]}

    # Step F: Send report to Telegram
    report_lines = [
        "* Safe Nightly Improvement Report*",
        "",
        f"Performance: {perf.get('total_calls', 0)} tool calls across "
        f"{perf.get('total_tools', 0)} tools",
        "",
    ]

    if failures:
        report_lines.append("Failure Patterns:")
        for f in failures:
            report_lines.append(
                f"  - {f['tool_name']}: {f['success_rate']*100:.0f}% success "
                f"({f['failures']} fails / {f['total']} total)"
            )
        report_lines.append("")

    if skills_created:
        report_lines.append(f"Skills Created: {', '.join(skills_created)}")
    else:
        report_lines.append("Skills: No new skills needed")

    tune_changes = summary["steps"].get("config_tuning", [])
    if isinstance(tune_changes, list) and tune_changes:
        report_lines.append("")
        report_lines.append("Config Tuning:")
        for change in tune_changes:
            report_lines.append(
                f"  - {change.get('key', '?')}: {change.get('old', '?')} -> "
                f"{change.get('new', '?')} ({change.get('reason', '')})"
            )
    else:
        report_lines.append("Config: No tuning needed")

    plugins = summary["steps"].get("plugins", {})
    if isinstance(plugins, dict) and not plugins.get("error"):
        loaded = plugins.get("loaded", [])
        failed = plugins.get("failed", [])
        report_lines.append(
            f"\nPlugins: {len(loaded)} loaded, {len(failed)} failed"
        )

    report_lines.append("\nSource code was NOT modified")
    report = "\n".join(report_lines)
    summary["report"] = report

    # Send async report (best-effort)
    try:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        _send_improvement_report(owner_id, report),
                    )
                    future.result(timeout=30)
            else:
                asyncio.run(_send_improvement_report(owner_id, report))
        except RuntimeError:
            asyncio.run(_send_improvement_report(owner_id, report))
    except Exception as exc:
        logger.warning("SAFE_IMPROVE_TELEGRAM_FAIL: %s", str(exc)[:200])
        summary["telegram_sent"] = False

    logger.info(
        "SAFE_IMPROVE_COMPLETE owner=%d skills=%d tune_changes=%d",
        owner_id,
        len(skills_created),
        len(tune_changes) if isinstance(tune_changes, list) else 0,
    )
    return summary


def tool_safe_improve(args: dict) -> dict:
    """Tool wrapper for the safe nightly improvement cycle.

    This is what Bob calls instead of the old dangerous self_improve tool.
    It reviews performance, creates skills, tunes config, and reports --
    all without touching source code.

    Args:
        args: Dict with optional _owner_id (defaults to 1).

    Returns:
        Dict with the full improvement summary.
    """
    try:
        owner_id = int(args.get("_owner_id", 1))
        return run_safe_improvement(owner_id)
    except Exception as exc:
        logger.error("TOOL_SAFE_IMPROVE_FAIL: %s", str(exc)[:300])
        return {"ok": False, "error": str(exc)[:300]}


# ===========================================================================
# Self-Play (merged from self_play.py)
# ===========================================================================
# Bob debates itself to improve responses.  Generates a response, then
# plays devil's advocate against it, then writes a final improved version.
# Only on complex analytical questions -- not simple tasks.
# ===========================================================================

_DEBATE_KEYWORDS = {"is it", "should i", "what do you think", "opinion", "evaluate",
                    "assess", "worth it", "better or worse", "pros and cons"}


def needs_self_play(message: str) -> bool:
    """Check if a message warrants self-play debate refinement."""
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


# ===========================================================================
# Self-Testing (merged from self_tester.py)
# ===========================================================================
# Bob writes and runs tests for his own features.  After building anything
# new, Bob auto-generates unit tests, runs them, and flags failures.
# ===========================================================================

_REPO_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
_TEST_DIR = Path(_REPO_ROOT) / "tests" / "unit"


def generate_tests_for_service(service_name: str, service_code: str) -> Optional[str]:
    """Use LLM to generate pytest tests for a service."""
    from ..agent.llm import call_llm
    prompt = [{
        "role": "user",
        "content": (
            f"Write 3-5 pytest unit tests for this Python service.\n"
            f"Service name: {service_name}\n\n"
            f"Code (excerpt):\n```python\n{service_code[:2000]}\n```\n\n"
            f"Write tests that:\n"
            f"- Import the module correctly\n"
            f"- Test key functions with mock DB/LLM calls\n"
            f"- Use pytest fixtures and mocking\n"
            f"- Are runnable without network/DB\n\n"
            f"Return ONLY pytest code, no explanations."
        ),
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
        code = code.strip()
        if code.startswith("```"):
            lines = code.split("\n")
            code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        if "def test_" in code:
            return code.strip()
    except Exception as e:
        logger.debug("TEST_GEN_FAIL: %s", str(e)[:80])
    return None


def run_tests(test_file: str = None) -> dict:
    """Run pytest and return results."""
    cmd = ["python", "-m", "pytest"]
    if test_file:
        cmd.append(test_file)
    else:
        cmd.extend(["tests/unit/", "-q", "--tb=short",
                    "--ignore=tests/unit/test_agents.py",
                    "--ignore=tests/unit/test_knowledge.py"])
    try:
        result = subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True, timeout=90)
        passed = result.returncode == 0
        output = (result.stdout + result.stderr)[-2000:]
        return {"ok": True, "passed": passed, "output": output}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Tests timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_run_self_tests(args: dict) -> dict:
    """Tool: Run Bob's full test suite and return results."""
    test_file = args.get("test_file")
    return run_tests(test_file)


def tool_generate_tests(args: dict) -> dict:
    """Tool: Generate pytest tests for a service file."""
    service_name = str(args.get("service_name", "")).strip()
    service_file = str(args.get("service_file", "")).strip()
    if not service_name or not service_file:
        return {"ok": False, "error": "service_name and service_file required"}
    try:
        code = Path(_REPO_ROOT, service_file).read_text(encoding="utf-8")[:3000]
    except Exception as e:
        return {"ok": False, "error": f"Cannot read file: {e}"}
    tests = generate_tests_for_service(service_name, code)
    if not tests:
        return {"ok": False, "error": "LLM did not generate valid tests"}
    # Save the test file
    test_path = _TEST_DIR / f"test_{service_name}.py"
    try:
        test_path.write_text(tests, encoding="utf-8")
        return {"ok": True, "test_file": str(test_path), "tests_preview": tests[:300]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
