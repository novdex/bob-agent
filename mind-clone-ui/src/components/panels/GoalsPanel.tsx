import { useState, useEffect, useCallback } from "react";
import { Target, Plus } from "lucide-react";
import { apiGet, apiPost, apiPatch } from "../../api/client";
import { usePolling } from "../../hooks/usePolling";
import { showToast } from "../../hooks/useToast";
import { formatApiError, requireOpsToken } from "../../utils/errors";
import { ProgressBar, StatusBadge, EmptyState, LoadingSkeleton, ErrorAlert } from "../ui";
import type { AppContext, Goal } from "../../types";

type Props = { context: AppContext };

export function GoalsPanel({ context }: Props) {
  const opsError = requireOpsToken(context);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [selected, setSelected] = useState<Goal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [priority, setPriority] = useState("medium");

  const fetchGoals = useCallback(async () => {
    if (opsError) return;
    try {
      const res = await apiGet<{ goals: Goal[] }>(`/goals?owner_id=${context.chatId}`, context.token);
      setGoals(res.goals ?? []);
    } catch (e) { setError(formatApiError(e)); }
    finally { setLoading(false); }
  }, [context.chatId, context.token, opsError]);

  useEffect(() => { fetchGoals(); }, [fetchGoals]);
  usePolling(fetchGoals, 8000);

  if (opsError) {
    return (
      <section className="panel">
        <div className="panel-head"><h2><Target size={18} /> Goals</h2></div>
        <EmptyState title="Ops token required" description={opsError} />
      </section>
    );
  }

  async function createGoal() {
    if (!title.trim()) return;
    try {
      await apiPost("/goal", { owner_id: Number(context.chatId), title: title.trim(), description: desc, priority }, context.token);
      showToast("Goal created", "success");
      setTitle(""); setDesc("");
      fetchGoals();
    } catch (e) { showToast(formatApiError(e), "error"); }
  }

  async function updateGoal(id: number, patch: Record<string, string>) {
    try {
      await apiPatch(`/goal/${id}`, patch, context.token);
      showToast("Goal updated", "success");
      fetchGoals();
    } catch (e) { showToast(formatApiError(e), "error"); }
  }

  const statusColor = (s: string) => s === "completed" ? "ok" : s === "failed" ? "danger" : s === "active" ? "accent" : "muted";

  return (
    <section className="panel">
      <div className="panel-head"><h2><Target size={18} /> Goals</h2><p className="muted">Goal decomposition &amp; tracking</p></div>

      {/* Create form */}
      <div className="subpanel">
        <div className="form-grid">
          <input placeholder="Goal title" value={title} onChange={(e) => setTitle(e.target.value)} />
          <textarea rows={2} placeholder="Description (optional)" value={desc} onChange={(e) => setDesc(e.target.value)} />
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <select value={priority} onChange={(e) => setPriority(e.target.value)} style={{ background: "rgba(5,10,16,0.7)", color: "var(--text)", border: "1px solid var(--line)", borderRadius: "var(--radius-sm)", padding: "6px 10px" }}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
            <button onClick={createGoal} disabled={!title.trim()}><Plus size={14} /> Create Goal</button>
          </div>
        </div>
      </div>

      {error && <ErrorAlert message={error} onRetry={fetchGoals} />}

      {/* Split: list + detail */}
      <div className="split-grid">
        <div className="subpanel">
          <h3>All Goals</h3>
          {loading ? <LoadingSkeleton lines={4} /> : goals.length === 0 ? (
            <EmptyState title="No goals yet" description="Create your first goal above" />
          ) : (
            <div className="list-scroll" style={{ marginTop: 8 }}>
              {goals.map((g) => (
                <div key={g.id} className={`list-row static${selected?.id === g.id ? " active" : ""}`} onClick={() => setSelected(g)} style={{ cursor: "pointer" }}>
                  <span>
                    <strong className="truncate" style={{ display: "block" }}>{g.title}</strong>
                    <ProgressBar value={g.progress_pct} max={100} showLabel={false} />
                  </span>
                  <StatusBadge label={g.status} status={statusColor(g.status)} />
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="subpanel">
          <h3>Detail</h3>
          {selected ? (
            <div style={{ marginTop: 8, display: "grid", gap: 8, fontSize: "0.85rem" }}>
              <p><strong>{selected.title}</strong></p>
              {selected.description && <p className="muted">{selected.description}</p>}
              <ProgressBar value={selected.progress_pct} max={100} color={selected.progress_pct === 100 ? "var(--ok)" : "var(--accent)"} />
              <div style={{ display: "flex", gap: 8 }}>
                <StatusBadge label={selected.status} status={statusColor(selected.status)} size="md" />
                <span className="tag">{selected.priority}</span>
              </div>
              {selected.task_ids.length > 0 && <p className="muted">Linked tasks: {selected.task_ids.join(", ")}</p>}
              <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                <button className="ghost" style={{ fontSize: "0.78rem" }} onClick={() => updateGoal(selected.id, { status: "completed" })}>Mark Complete</button>
                <button className="ghost danger" style={{ fontSize: "0.78rem" }} onClick={() => updateGoal(selected.id, { status: "cancelled" })}>Cancel</button>
              </div>
            </div>
          ) : <p className="muted" style={{ marginTop: 8 }}>Select a goal</p>}
        </div>
      </div>
    </section>
  );
}
