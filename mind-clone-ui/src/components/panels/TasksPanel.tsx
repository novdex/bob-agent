import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../../api/client";
import type { AppContext, UiTaskDetail, UiTaskSummary } from "../../types";
import { formatApiError, requireUserContext } from "../../utils/errors";

type TasksPanelProps = {
  context: AppContext;
};

export function TasksPanel({ context }: TasksPanelProps) {
  const [tasks, setTasks] = useState<UiTaskSummary[]>([]);
  const [selectedTask, setSelectedTask] = useState<UiTaskDetail | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [error, setError] = useState("");
  const [actionBusy, setActionBusy] = useState(false);

  const loadTasks = async () => {
    const ctxError = requireUserContext(context);
    if (ctxError) {
      setError(ctxError);
      setTasks([]);
      return;
    }
    try {
      const payload = await apiGet<{ ok: boolean; tasks?: UiTaskSummary[]; error?: string }>(
        `/ui/tasks?chat_id=${encodeURIComponent(context.chatId)}&username=${encodeURIComponent(context.username)}&limit=25`
      );
      if (!payload.ok) {
        throw new Error(payload.error || "Failed to load tasks.");
      }
      setTasks(Array.isArray(payload.tasks) ? payload.tasks : []);
      setError("");
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  const loadTaskDetail = async (taskId: number) => {
    const ctxError = requireUserContext(context);
    if (ctxError) {
      setError(ctxError);
      return;
    }
    try {
      const payload = await apiGet<UiTaskDetail>(
        `/ui/tasks/${taskId}?chat_id=${encodeURIComponent(context.chatId)}&username=${encodeURIComponent(context.username)}`
      );
      if (!payload.ok) {
        throw new Error(payload.error || "Failed to load task detail.");
      }
      setSelectedTask(payload);
      setSelectedTaskId(taskId);
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  const onCreateTask = async () => {
    const ctxError = requireUserContext(context);
    if (ctxError) {
      setError(ctxError);
      return;
    }
    if (!title.trim() || !goal.trim()) {
      setError("Title and goal are required.");
      return;
    }
    setActionBusy(true);
    try {
      const payload = await apiPost<{
        ok: boolean;
        task_id?: number;
        error?: string;
      }>("/ui/tasks", {
        chat_id: context.chatId,
        username: context.username,
        title,
        goal,
      });
      if (!payload.ok) {
        throw new Error(payload.error || "Task creation failed.");
      }
      setTitle("");
      setGoal("");
      await loadTasks();
      if (payload.task_id) {
        await loadTaskDetail(payload.task_id);
      }
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setActionBusy(false);
    }
  };

  const onCancelTask = async () => {
    if (!selectedTaskId) {
      return;
    }
    setActionBusy(true);
    try {
      const payload = await apiPost<{ ok: boolean; message?: string; error?: string }>(
        `/ui/tasks/${selectedTaskId}/cancel`,
        {
          chat_id: context.chatId,
          username: context.username,
        }
      );
      if (!payload.ok) {
        throw new Error(payload.error || payload.message || "Cancel failed.");
      }
      await loadTasks();
      await loadTaskDetail(selectedTaskId);
    } catch (err) {
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
      {error && <p className="error">{error}</p>}
      <article className="subpanel">
        <h3>Create task</h3>
        <div className="form-grid">
          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Task title" />
          <textarea
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            rows={3}
            placeholder="Goal details"
          />
        </div>
        <button onClick={() => void onCreateTask()} disabled={actionBusy}>
          {actionBusy ? "Working..." : "Create task"}
        </button>
      </article>
      <div className="split-grid">
        <article className="subpanel">
          <h3>Recent tasks</h3>
          <div className="list-scroll">
            {tasks.length === 0 && <p className="muted">No tasks found.</p>}
            {tasks.map((task) => (
              <button
                key={task.id}
                className={`list-row ${selectedTaskId === task.id ? "active" : ""}`}
                onClick={() => void loadTaskDetail(task.id)}
              >
                <strong>#{task.id}</strong>
                <span>{task.title}</span>
                <span className="tag">{task.status}</span>
                <span>
                  {task.progress_done}/{task.progress_total}
                </span>
              </button>
            ))}
          </div>
        </article>
        <article className="subpanel">
          <h3>Task detail</h3>
          {!selectedTask && <p className="muted">Select a task to inspect details.</p>}
          {selectedTask && (
            <>
              <p>
                <strong>{selectedTask.task?.title}</strong> ({selectedTask.task?.status})
              </p>
              <p className="muted">{selectedTask.detail_text}</p>
              <button className="danger" onClick={() => void onCancelTask()} disabled={actionBusy}>
                Cancel task
              </button>
              <pre>{JSON.stringify(selectedTask.plan || [], null, 2)}</pre>
            </>
          )}
        </article>
      </div>
    </section>
  );
}
