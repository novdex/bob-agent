"""
Observability Dashboard — live view of Bob's health.

Reports on:
- Tool success rates (last 24h)
- Experiment history + composite score trend
- Memory graph size
- Skills library size
- Active scheduled jobs
- Recent reflexion lessons
- Error patterns
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone, timedelta
from ..database.session import SessionLocal
from ..database.models import (
    ToolPerformanceLog, ExperimentLog, MemoryLink, MemoryVector,
    SkillProfile, SelfImprovementNote, ScheduledJob, EpisodicMemory,
)
from sqlalchemy import func as sqlfunc
logger = logging.getLogger("mind_clone.services.observability")


def get_dashboard(owner_id: int = 1) -> dict:
    """Get full observability dashboard."""
    db = SessionLocal()
    try:
        since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        since_7d = datetime.now(timezone.utc) - timedelta(days=7)

        # Tool performance
        perf = db.query(
            ToolPerformanceLog.tool_name,
            sqlfunc.count(ToolPerformanceLog.id).label("total"),
            sqlfunc.avg(ToolPerformanceLog.success).label("success_rate"),
        ).filter(
            ToolPerformanceLog.owner_id == owner_id,
            ToolPerformanceLog.created_at >= since_24h,
        ).group_by(ToolPerformanceLog.tool_name).order_by(
            sqlfunc.avg(ToolPerformanceLog.success).asc()
        ).limit(10).all()

        tool_stats = [
            {"tool": r.tool_name, "calls": int(r.total), "success_rate": round(float(r.success_rate or 0), 3)}
            for r in perf
        ]
        overall_success = (
            round(sum(t["success_rate"] for t in tool_stats) / len(tool_stats), 3)
            if tool_stats else 0.0
        )

        # Experiment history
        experiments = db.query(ExperimentLog).filter(
            ExperimentLog.owner_id == owner_id
        ).order_by(ExperimentLog.id.desc()).limit(5).all()
        exp_summary = [
            {"title": e.hypothesis_title[:50], "improved": e.improved,
             "score_before": round(e.score_before, 3), "score_after": round(e.score_after, 3)}
            for e in experiments
        ]

        # Memory stats
        memory_links = db.query(MemoryLink).filter(MemoryLink.owner_id == owner_id).count()
        memory_vectors = db.query(MemoryVector).filter(MemoryVector.owner_id == owner_id).count()
        episodic = db.query(EpisodicMemory).filter(EpisodicMemory.owner_id == owner_id).count()

        # Skills
        skills = db.query(SkillProfile).filter(
            SkillProfile.owner_id == owner_id, SkillProfile.status == "active"
        ).count()

        # Lessons
        lessons = db.query(SelfImprovementNote).filter(
            SelfImprovementNote.owner_id == owner_id,
            SelfImprovementNote.status == "open",
        ).count()

        # Scheduled jobs
        jobs = db.query(ScheduledJob).filter(
            ScheduledJob.owner_id == owner_id, ScheduledJob.enabled == 1
        ).all()
        job_list = [
            {"name": j.name, "interval_h": round(j.interval_seconds / 3600, 1),
             "run_count": j.run_count or 0}
            for j in jobs
        ]

        # Current composite score
        from .auto_research import measure_composite_score
        score = measure_composite_score(db, owner_id)

        return {
            "ok": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "composite_score": score["composite"],
            "tool_success_rate": overall_success,
            "error_rate": score["error_rate"],
            "tool_stats": tool_stats[:5],
            "experiments": {
                "total": len(experiments),
                "recent": exp_summary,
                "improvements": sum(1 for e in experiments if e.improved),
            },
            "memory": {
                "graph_links": memory_links,
                "vectors": memory_vectors,
                "episodic_memories": episodic,
                "lessons_learned": lessons,
                "skills_library": skills,
            },
            "scheduled_jobs": job_list,
        }
    except Exception as e:
        logger.error("DASHBOARD_FAIL: %s", e)
        return {"ok": False, "error": str(e)[:200]}
    finally:
        db.close()


def format_dashboard_text(dashboard: dict) -> str:
    """Format dashboard as readable text for Telegram."""
    if not dashboard.get("ok"):
        return f"Dashboard error: {dashboard.get('error', '?')}"
    d = dashboard
    mem = d.get("memory", {})
    exp = d.get("experiments", {})
    jobs = d.get("scheduled_jobs", [])
    lines = [
        f"📊 *Bob Observability Dashboard*",
        f"",
        f"🎯 *Composite Score:* {d.get('composite_score', 0):.3f}",
        f"✅ *Tool Success:* {d.get('tool_success_rate', 0):.1%}",
        f"❌ *Error Rate:* {d.get('error_rate', 0):.1%}",
        f"",
        f"🧠 *Memory:*",
        f"• Graph links: {mem.get('graph_links', 0)}",
        f"• Episodic memories: {mem.get('episodic_memories', 0)}",
        f"• Lessons learned: {mem.get('lessons_learned', 0)}",
        f"• Skills library: {mem.get('skills_library', 0)}",
        f"• Vector KB: {mem.get('vectors', 0)}",
        f"",
        f"🧪 *Experiments:* {exp.get('total', 0)} total, {exp.get('improvements', 0)} improvements",
        f"",
        f"⏰ *Scheduled Jobs:* {len(jobs)} active",
    ]
    for j in jobs[:4]:
        lines.append(f"  • {j['name']} (every {j['interval_h']}h, ran {j['run_count']}x)")
    return "\n".join(lines)


def tool_dashboard(args: dict) -> dict:
    """Tool: Get Bob's full observability dashboard."""
    owner_id = int(args.get("_owner_id", 1))
    dashboard = get_dashboard(owner_id)
    text = format_dashboard_text(dashboard)
    return {**dashboard, "formatted": text}
