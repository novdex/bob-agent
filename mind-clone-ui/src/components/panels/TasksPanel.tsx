import { useEffect, useState } from "react";
import { Plus, XCircle, ListChecks } from "lucide-react";
import { apiGet, apiPost } from "../../api/client";
import type { AppContext, UiTaskDetail, UiTaskSummary } from "../../types";
import { formatApiError, requireUserContext } from "../../utils/errors";
import { showToast } from "../../hooks/useToast";
import {
  StatusBadge, ProgressBar, JsonTree, ErrorAlert, EmptyState, LoadingSkeleton,
} from "../ui";

type TasksPanelProps = { context: AppContext };

const statusColor = (s: string): "ok" | "warn" | "danger" | "accent" | "muted" => {
  if (s === "completed" || s === "done") return "ok";
  if (s === "running" || s === "in_progress") return "accent";
  if (s === "failed" || s === "cancelled") return "danger";
  if (s === "queued" || s === "pending") return "warn";
  return "muted";
};

export function TasksPanel({ context }: TasksPanelProps) {
  const [tasks, setTasks] = useState<UiTaskSummary[]>([]);
  const [selectedTask, setSelectedTask] = useState<UiTaskDetail | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [error, setError] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadTasks = async () => {
    const ctxError = requireUserContext(context);
    if (ctxError) { setError(ctxError); setTasks([]); return; }
    try {
      const payload = await apiGet<{ ok: boolean; tasks?: UiTaskSummary[]; error?: string }>(
        `/ui/tasks?chat_id=${encodeURIComponent(context.chatId)}&username=${encodeURIComponent(context.username)}&limit=25`,
      );
      if (!payload.ok) throw new Error(payload.error || "Failed to load tasks.");
      setTasks(Array.isArray(payload.tasks) ? payload.tasks : []);
      setError("");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  };

  const loadTaskDetail = async (taskId: number) => {
    const ctxError = requireUserContext(context);
    if (ctxError) { setError(ctxError); return; }
    try {
      const payload = await apiGet<UiTaskDetail>(
        `/ui/tasks/${taskId}?chat_id=${encodeURIComponent(context.chatId)}&username=${encodeURIComponent(context.username)}`,
      );
      if (!payload.ok) throw new Error(payload.error || "Failed to load task detail.");
      setSelectedTask(payload);
      setSelectedTaskId(taskId);
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  const onCreateTask = async () => {
    const ctxError = requireUserContext(context);
    if (ctxError) { setError(ctxError); return; }
    if (!title.trim() || !goal.trim()) { setError("Title and goal are required."); return; }
    setActionBusy(true);
    try {
      const payload = await apiPost<{ ok: boolean; task_id?: number; error?: string }>(
        "/ui/tasks",
        { chat_id: context.chatId, username: context.username, title, goal },
      );
      if (!payload.ok) throw new Error(payload.error || "Task creation failed.");
      showToast(`Task #${payload.task_id} created`, "success");
      setTitle(""); setGoal("");
      await loadTasks();
      if (payload.task_id) await loadTaskDetail(payload.task_id);
    } catch (err) {
      showToast(formatApiError(err), "error");
      setError(formatApiError(err));
    } finally {
      setActionBusy(false);
    }
  };

  const onCancelTask = async () => {
    if (!selectedTaskId) return;
    setActionBusy(true);
    try {
      const payload = await apiPost<{ ok: boolean; message?: string; error?: string }>(
        `/ui/tasks/${selectedTaskId}/cancel`,
        { chat_id: context.chatId, username: context.username },
      );
      if (!payload.ok) throw new Error(payload.error || payload.message || "Cancel failed.");
      showToast(`Task #${selectedTaskId} cancelled`, "success");
      await loadTasks();
      await loadTaskDetail(selectedTaskId);
    } catch (err) {
      showToast(formatApiError(err), "error");
      setError(formatApiError(err));
    } finally {
      setActionBusy(false);
    }
  };

  useEffect(() => {
    void loadTasks();
    const timer = window.setInterval(() => void loadTasks(), 4000);
    return () => window.clearInterval(timer);
  }, [context.chatId, context.username]);

  return (
    <section className="panel">
      <header className="panel-head">
        <h2>Task Control</h2>
        <p>Create, inspect, and cancel queued graph tasks.</p>
      </header>

      {error && <ErrorAlert message={error} onRetry={() => void loadTasks()} onDismiss={() => setError("")} />}

      {/* Create form */}
      <article className="subpanel">
        <h3><Plus size={14} style={{ verticalAlign: -2 }} /> Create Task</h3>
        <div className="form-grid">
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Task title" />
          <textarea value={goal} onChange={(e) => setGoal(e.target.value)} rows={3} placeholder="Goal details" />
        </div>
        <button onClick={() => void onCreateTask()} disabled={actionBusy}>
          {actionBusy ? "Working\u2026" : "Create task"}
        </button>
      </article>

      {loading && <LoadingSkeleton variant="card" />}

      <div className="split-grid">
        {/* Task list */}
        <article className="subpanel">
          <h3>Recent Tasks</h3>
          <div className="list-scroll">
            {tasks.length === 0 && !loading && (
              <EmptyState title="No tasks" description="Create a task above to get started." icon={ListChecks} />
            )}
            {tasks.map((task) => (
              <button
                key={task.id}
                className={`list-row ${selectedTaskId === task.id ? "active" : ""}`}
                onClick={() => void loadTaskDetail(task.id)}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <strong>#{task.id}</strong>{" "}
                  <span className="truncate" style={{ display: "inline-block", maxWidth: "60%" }}>{task.title}</span>
                  <div style={{ marginTop: 4 }}>
                    <ProgressBar value={task.progress_done} max={task.progress_total} color={
                      task.status === "completed" ? "var(--ok)" :
                      task.status === "failed" ? "var(--danger)" : "var(--accent)"
                    } />
                  </div>
                </div>
                <StatusBadge label={task.status} status={statusColor(task.status)} size="sm" />
              </button>
            ))}
          </div>
        </article>

        {/* Detail */}
        <article className="subpanel">
          <h3>Task Detail</h3>
          {!selectedTask && <p className="muted">Select a task to inspect details.</p>}
          {selectedTask && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <strong>{selectedTask.task?.title}</strong>
                <StatusBadge
                  label={selectedTask.task?.status ?? "unknown"}
                  status={statusColor(selectedTask.task?.status ?? "")}
                  pulse={selectedTask.task?.status === "running"}
                />
              </div>
              {selectedTask.detail_text && <p className="muted">{selectedTask.detail_text}</p>}
              <button className="danger" onClick={() => void onCancelTask()} disabled={actionBusy} style={{ marginBottom: 12 }}>
                <XCircle size={14} style={{ verticalAlign: -2 }} /> Cancel task
              </button>
              <h4 style={{ margin: "8px 0 4px" }}>Plan</h4>
              <JsonTree data={selectedTask.plan || []} maxDepth={3} />
            </>
          )}
        </article>
      </div>
    </section>
  );
}
