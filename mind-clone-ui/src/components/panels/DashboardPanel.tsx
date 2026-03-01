import { useEffect, useState, useCallback } from "react";
import { Activity, Database, Layers, Cpu, MessageSquare, Target, ListChecks, Zap } from "lucide-react";
import { apiGet } from "../../api/client";
import { usePolling } from "../../hooks/usePolling";
import { StatCard, LoadingSkeleton } from "../ui";
import { ActivityFeed } from "./dashboard/ActivityFeed";
import { runtimeStat } from "../../utils/formatters";
import type { AppContext, RuntimePayload, UiTaskSummary, UiApproval, AuditEvent } from "../../types";
import type { PanelKey } from "../../types";

type Props = { context: AppContext; setActivePanel: (p: PanelKey) => void };

export function DashboardPanel({ context, setActivePanel }: Props) {
  const [runtime, setRuntime] = useState<RuntimePayload | null>(null);
  const [tasks, setTasks] = useState<UiTaskSummary[]>([]);
  const [approvals, setApprovals] = useState<UiApproval[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchAll = useCallback(async () => {
    try {
      const [rt, ts, ap, au] = await Promise.allSettled([
        apiGet<RuntimePayload>("/status/runtime"),
        context.chatId
          ? apiGet<{ tasks: UiTaskSummary[] }>(`/ui/tasks?chat_id=${context.chatId}&limit=5`)
          : Promise.resolve({ tasks: [] }),
        context.chatId
          ? apiGet<{ items: UiApproval[] }>(`/ui/approvals/pending?chat_id=${context.chatId}&username=${context.username}&limit=5`)
          : Promise.resolve({ items: [] }),
        context.token
          ? apiGet<{ items: AuditEvent[] }>("/ops/audit/events?limit=8", context.token)
          : Promise.resolve({ items: [] }),
      ]);
      if (rt.status === "fulfilled") setRuntime(rt.value);
      if (ts.status === "fulfilled") setTasks(ts.value.tasks ?? []);
      if (ap.status === "fulfilled") setApprovals(ap.value.items ?? []);
      if (au.status === "fulfilled") setAuditEvents(au.value.items ?? []);
    } finally {
      setLoading(false);
    }
  }, [context.chatId, context.username, context.token]);

  useEffect(() => { fetchAll(); }, [fetchAll]);
  usePolling(fetchAll, 8000);

  const rs = (k: string) => runtimeStat(runtime, k);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2><Activity size={18} /> Dashboard</h2>
        <p className="muted">Bob's state at a glance</p>
      </div>

      {/* Health cards */}
      {loading ? <LoadingSkeleton variant="card" /> : (
        <div className="stat-grid">
          <StatCard icon={Cpu} label="Worker" value={rs("worker_alive")} color={rs("worker_alive") === "yes" ? "var(--ok)" : "var(--danger)"} />
          <StatCard icon={Database} label="Database" value={rs("db_healthy")} color={rs("db_healthy") === "yes" ? "var(--ok)" : "var(--danger)"} />
          <StatCard icon={Layers} label="Queue" value={rs("command_queue_size")} color="var(--accent)" />
          <StatCard icon={Zap} label="Model" value={rs("active_model")} color="var(--accent-2)" />
        </div>
      )}

      {/* Tasks + Approvals */}
      <div className="split-grid">
        <div className="subpanel">
          <h3><ListChecks size={15} /> Active Tasks</h3>
          {loading ? <LoadingSkeleton lines={3} /> : tasks.length === 0 ? (
            <p className="muted" style={{ fontSize: "0.82rem", marginTop: 8 }}>No tasks</p>
          ) : (
            <div style={{ display: "grid", gap: 4, marginTop: 8 }}>
              {tasks.map((t) => (
                <div key={t.id} className="list-row static" style={{ padding: "6px 8px", fontSize: "0.82rem" }}>
                  <span className="truncate">{t.title}</span>
                  <span className={`tag ${t.status === "done" ? "ok" : t.status === "failed" ? "danger" : "accent"}`}>
                    {t.status}
                  </span>
                </div>
              ))}
              <button className="ghost" style={{ fontSize: "0.78rem", padding: "4px 8px" }} onClick={() => setActivePanel("tasks")}>
                View all &rarr;
              </button>
            </div>
          )}
        </div>

        <div className="subpanel">
          <h3><Target size={15} /> Pending Approvals</h3>
          {loading ? <LoadingSkeleton lines={2} /> : approvals.length === 0 ? (
            <p className="muted" style={{ fontSize: "0.82rem", marginTop: 8 }}>All clear</p>
          ) : (
            <div style={{ marginTop: 8 }}>
              <p style={{ fontSize: "1.4rem", fontWeight: 600, color: "var(--warn)" }}>{approvals.length}</p>
              <p className="muted" style={{ fontSize: "0.82rem" }}>awaiting your decision</p>
              <button className="ghost" style={{ fontSize: "0.78rem", padding: "4px 8px", marginTop: 6 }} onClick={() => setActivePanel("approvals")}>
                Review &rarr;
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Activity feed */}
      <div className="subpanel" style={{ marginTop: 12 }}>
        <h3><Activity size={15} /> Recent Activity</h3>
        <div style={{ marginTop: 8 }}>
          <ActivityFeed events={auditEvents} loading={loading} />
        </div>
      </div>

      {/* Quick actions */}
      <div className="quick-actions">
        <button onClick={() => setActivePanel("chat")}><MessageSquare size={14} /> Chat</button>
        <button onClick={() => setActivePanel("tasks")}><ListChecks size={14} /> New Task</button>
        <button onClick={() => setActivePanel("goals")}><Target size={14} /> Goals</button>
      </div>
    </section>
  );
}
