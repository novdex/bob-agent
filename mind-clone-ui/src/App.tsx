import { Component, type ErrorInfo, type ReactNode, useEffect, useMemo, useState } from "react";
import { ApiRequestError, apiGet, apiPost, isRecord } from "./api/client";
import type { CronJob, RuntimePayload, UiApproval, UiTaskDetail, UiTaskSummary } from "./types";

type PanelKey =
  | "runtime"
  | "chat"
  | "tasks"
  | "approvals"
  | "cron"
  | "blackbox"
  | "nodes";

type PanelDef = {
  key: PanelKey;
  label: string;
};

type AppContext = {
  chatId: string;
  username: string;
  token: string;
};

const PANELS: PanelDef[] = [
  { key: "runtime", label: "Runtime" },
  { key: "chat", label: "Chat" },
  { key: "tasks", label: "Tasks" },
  { key: "approvals", label: "Approvals" },
  { key: "cron", label: "Cron" },
  { key: "blackbox", label: "Blackbox" },
  { key: "nodes", label: "Nodes/Plugins" }
];

const STORAGE_CHAT_ID = "bob_ui_chat_id";
const STORAGE_USERNAME = "bob_ui_username";
const STORAGE_TOKEN = "bob_ui_ops_token";

function readSession(key: string): string {
  try {
    return window.sessionStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function writeSession(key: string, value: string): void {
  try {
    if (value) {
      window.sessionStorage.setItem(key, value);
    } else {
      window.sessionStorage.removeItem(key);
    }
  } catch {
    // session storage can be blocked by browser policy
  }
}

function formatApiError(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (typeof error.detail === "string") {
      return `HTTP ${error.status}: ${error.detail}`;
    }
    if (isRecord(error.detail)) {
      const detail = error.detail.detail || error.detail.error || JSON.stringify(error.detail);
      return `HTTP ${error.status}: ${String(detail)}`;
    }
    return `HTTP ${error.status}: ${error.message}`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown request error.";
}

function hasUserContext(ctx: AppContext): boolean {
  return Boolean(ctx.chatId.trim() && ctx.username.trim());
}

function requireUserContext(ctx: AppContext): string | null {
  if (!ctx.chatId.trim()) {
    return "Set chat_id in Settings first.";
  }
  if (!ctx.username.trim()) {
    return "Set username in Settings first.";
  }
  return null;
}

function requireOpsToken(ctx: AppContext): string | null {
  if (!ctx.token.trim()) {
    return "Ops token required. Set it in Settings for protected panels.";
  }
  return null;
}

function formatTimestamp(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) {
    return "-";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function runtimeStat(runtime: RuntimePayload | null, key: string): string {
  if (!runtime || !(key in runtime)) {
    return "-";
  }
  const raw = runtime[key];
  if (raw === null || raw === undefined) {
    return "-";
  }
  if (typeof raw === "boolean") {
    return raw ? "yes" : "no";
  }
  if (typeof raw === "number") {
    return Number.isFinite(raw) ? String(raw) : "-";
  }
  if (typeof raw === "string") {
    return raw || "-";
  }
  return JSON.stringify(raw);
}

type PanelErrorBoundaryProps = {
  children: ReactNode;
};

type PanelErrorBoundaryState = {
  hasError: boolean;
  message: string;
};

class PanelErrorBoundary extends Component<PanelErrorBoundaryProps, PanelErrorBoundaryState> {
  constructor(props: PanelErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error: Error): PanelErrorBoundaryState {
    return { hasError: true, message: error.message || "Unexpected UI error." };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("PanelErrorBoundary", error, info.componentStack);
  }

  reset = () => {
    this.setState({ hasError: false, message: "" });
  };

  render() {
    if (this.state.hasError) {
      return (
        <section className="panel fatal">
          <h2>UI panel crashed</h2>
          <p className="error">{this.state.message || "Unexpected render error."}</p>
          <button onClick={this.reset}>Retry panel render</button>
        </section>
      );
    }
    return this.props.children;
  }
}

type SettingsPanelProps = {
  draftChatId: string;
  draftUsername: string;
  draftToken: string;
  setDraftChatId: (value: string) => void;
  setDraftUsername: (value: string) => void;
  setDraftToken: (value: string) => void;
  saveSettings: () => void;
  clearToken: () => void;
  statusMessage: string;
};

function SettingsPanel(props: SettingsPanelProps) {
  const {
    draftChatId,
    draftUsername,
    draftToken,
    setDraftChatId,
    setDraftUsername,
    setDraftToken,
    saveSettings,
    clearToken,
    statusMessage
  } = props;

  return (
    <section className="panel">
      <header className="panel-head">
        <h2>Settings</h2>
        <p>Session-only auth and user context. Nothing is persisted beyond this browser session.</p>
      </header>
      <div className="settings-grid">
        <label>
          <span>chat_id</span>
          <input
            value={draftChatId}
            onChange={(event) => setDraftChatId(event.target.value)}
            placeholder="e.g. 6346698354"
          />
        </label>
        <label>
          <span>username</span>
          <input
            value={draftUsername}
            onChange={(event) => setDraftUsername(event.target.value)}
            placeholder="telegram username"
          />
        </label>
        <label className="ops-token-row">
          <span>ops token (session)</span>
          <input
            value={draftToken}
            onChange={(event) => setDraftToken(event.target.value)}
            placeholder="Bearer token for protected routes"
            type="password"
          />
        </label>
      </div>
      <div className="settings-actions">
        <button onClick={saveSettings}>Save session settings</button>
        <button className="ghost" onClick={clearToken}>
          Clear token
        </button>
      </div>
      <p className="muted">{statusMessage || "Set chat_id + username to unlock user-scoped panels."}</p>
    </section>
  );
}

type RuntimePanelProps = {
  context: AppContext;
};

function RuntimePanel({ context }: RuntimePanelProps) {
  const [runtime, setRuntime] = useState<RuntimePayload | null>(null);
  const [error, setError] = useState("");

  const loadRuntime = async () => {
    try {
      const payload = await apiGet<RuntimePayload>("/status/runtime");
      setRuntime(payload);
      setError("");
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  useEffect(() => {
    void loadRuntime();
    const timer = window.setInterval(() => void loadRuntime(), 5000);
    return () => window.clearInterval(timer);
  }, []);

  const statusCards = useMemo(
    () => [
      { label: "Worker alive", value: runtimeStat(runtime, "worker_alive") },
      { label: "Spine alive", value: runtimeStat(runtime, "spine_supervisor_alive") },
      { label: "Webhook", value: runtimeStat(runtime, "webhook_registered") },
      { label: "DB healthy", value: runtimeStat(runtime, "db_healthy") },
      { label: "Queue size", value: runtimeStat(runtime, "command_queue_size") },
      { label: "Pending approvals", value: runtimeStat(runtime, "approval_pending_count") },
      { label: "Runtime alerts", value: runtimeStat(runtime, "runtime_alert_count") },
      { label: "Active model", value: runtimeStat(runtime, "llm_last_model_used") }
    ],
    [runtime]
  );

  return (
    <section className="panel">
      <header className="panel-head">
        <h2>Runtime Health</h2>
        <p>Polled every 5s from `/status/runtime`.</p>
      </header>
      {error && <p className="error">{error}</p>}
      <div className="stat-grid">
        {statusCards.map((card) => (
          <article className="stat-card" key={card.label}>
            <span>{card.label}</span>
            <strong>{card.value}</strong>
          </article>
        ))}
      </div>
      <article className="subpanel">
        <h3>Context</h3>
        <p>
          chat_id: <code>{context.chatId || "-"}</code>
        </p>
        <p>
          username: <code>{context.username || "-"}</code>
        </p>
        <p>
          ops token: <code>{context.token ? "loaded" : "missing"}</code>
        </p>
      </article>
      <article className="subpanel">
        <h3>Raw runtime JSON</h3>
        <pre>{runtime ? JSON.stringify(runtime, null, 2) : "Loading..."}</pre>
      </article>
    </section>
  );
}

type ChatPanelProps = {
  context: AppContext;
};

type ChatItem = { role: "user" | "assistant" | "system"; text: string; ts: number };

function ChatPanel({ context }: ChatPanelProps) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const onSend = async () => {
    const ctxError = requireUserContext(context);
    if (ctxError) {
      setError(ctxError);
      return;
    }
    const text = input.trim();
    if (!text) {
      return;
    }
    setBusy(true);
    setError("");
    setMessages((prev) => [...prev, { role: "user", text, ts: Date.now() }]);
    try {
      const payload = await apiPost<{ ok: boolean; response?: string; error?: string }>(
        "/chat",
        {
          chat_id: context.chatId,
          username: context.username,
          message: text
        }
      );
      if (!payload.ok) {
        throw new Error(payload.error || "Chat call failed.");
      }
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: String(payload.response || ""), ts: Date.now() }
      ]);
      setInput("");
    } catch (err) {
      const message = formatApiError(err);
      setError(message);
      setMessages((prev) => [...prev, { role: "system", text: `Error: ${message}`, ts: Date.now() }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <header className="panel-head">
        <h2>Chat Console</h2>
        <p>Direct request/response mode via `/chat`.</p>
      </header>
      {error && <p className="error">{error}</p>}
      <div className="chat-log">
        {messages.length === 0 && <p className="muted">No chat yet. Send a message to start.</p>}
        {messages.map((item) => (
          <article key={`${item.ts}-${item.role}`} className={`chat-item ${item.role}`}>
            <header>
              <span>{item.role}</span>
              <time>{new Date(item.ts).toLocaleTimeString()}</time>
            </header>
            <p>{item.text}</p>
          </article>
        ))}
      </div>
      <div className="chat-compose">
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Ask Bob..."
          rows={4}
        />
        <button onClick={() => void onSend()} disabled={busy}>
          {busy ? "Sending..." : "Send"}
        </button>
      </div>
    </section>
  );
}

type TasksPanelProps = {
  context: AppContext;
};

function TasksPanel({ context }: TasksPanelProps) {
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
        goal
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
          username: context.username
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

type ApprovalsPanelProps = {
  context: AppContext;
};

function ApprovalsPanel({ context }: ApprovalsPanelProps) {
  const [approvals, setApprovals] = useState<UiApproval[]>([]);
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");
  const [busyToken, setBusyToken] = useState("");

  const loadApprovals = async () => {
    const ctxError = requireUserContext(context);
    if (ctxError) {
      setError(ctxError);
      setApprovals([]);
      return;
    }
    try {
      const payload = await apiGet<{ ok: boolean; approvals?: UiApproval[]; error?: string }>(
        `/ui/approvals/pending?chat_id=${encodeURIComponent(context.chatId)}&username=${encodeURIComponent(context.username)}&limit=30`
      );
      if (!payload.ok) {
        throw new Error(payload.error || "Failed to load pending approvals.");
      }
      setApprovals(Array.isArray(payload.approvals) ? payload.approvals : []);
      setError("");
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  const decideApproval = async (token: string, approve: boolean) => {
    setBusyToken(token);
    try {
      const payload = await apiPost<{ ok: boolean; error?: string }>(
        "/approval/decision",
        {
          chat_id: context.chatId,
          username: context.username,
          token,
          approve,
          reason
        }
      );
      if (!payload.ok) {
        throw new Error(payload.error || "Approval decision failed.");
      }
      await loadApprovals();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusyToken("");
    }
  };

  useEffect(() => {
    void loadApprovals();
    const timer = window.setInterval(() => void loadApprovals(), 4000);
    return () => window.clearInterval(timer);
  }, [context.chatId, context.username]);

  return (
    <section className="panel">
      <header className="panel-head">
        <h2>Approval Queue</h2>
        <p>Approve or reject pending tool actions.</p>
      </header>
      {error && <p className="error">{error}</p>}
      <article className="subpanel">
        <h3>Decision reason (optional)</h3>
        <textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={2} />
      </article>
      <article className="subpanel">
        <h3>Pending approvals</h3>
        <div className="list-scroll">
          {approvals.length === 0 && <p className="muted">No pending approvals.</p>}
          {approvals.map((approval) => (
            <div className="list-row static" key={approval.token}>
              <div>
                <strong>{approval.tool_name}</strong>
                <p className="muted">
                  token={approval.token} source={approval.source_type}
                </p>
              </div>
              <div className="row-actions">
                <button
                  onClick={() => void decideApproval(approval.token, true)}
                  disabled={busyToken === approval.token}
                >
                  Approve
                </button>
                <button
                  className="danger"
                  onClick={() => void decideApproval(approval.token, false)}
                  disabled={busyToken === approval.token}
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}

type CronPanelProps = {
  context: AppContext;
};

function CronPanel({ context }: CronPanelProps) {
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [name, setName] = useState("ui_cron_job");
  const [message, setMessage] = useState("Run heartbeat self-check and summarize alerts.");
  const [intervalSeconds, setIntervalSeconds] = useState(300);
  const [error, setError] = useState("");

  const loadJobs = async () => {
    const ctxError = requireUserContext(context) || requireOpsToken(context);
    if (ctxError) {
      setError(ctxError);
      setJobs([]);
      return;
    }
    try {
      const payload = await apiGet<{ ok: boolean; jobs?: CronJob[]; error?: string }>(
        `/cron/jobs?chat_id=${encodeURIComponent(context.chatId)}&username=${encodeURIComponent(
          context.username
        )}&include_disabled=true&limit=40`,
        context.token
      );
      if (!payload.ok) {
        throw new Error(payload.error || "Failed to load cron jobs.");
      }
      setJobs(Array.isArray(payload.jobs) ? payload.jobs : []);
      setError("");
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  const createJob = async () => {
    const ctxError = requireUserContext(context) || requireOpsToken(context);
    if (ctxError) {
      setError(ctxError);
      return;
    }
    try {
      const payload = await apiPost<{ ok: boolean; error?: string }>(
        "/cron/jobs",
        {
          chat_id: context.chatId,
          username: context.username,
          name,
          message,
          interval_seconds: Number(intervalSeconds),
          lane: "cron"
        },
        context.token
      );
      if (!payload.ok) {
        throw new Error(payload.error || "Failed to create cron job.");
      }
      await loadJobs();
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  const disableJob = async (jobId: number) => {
    try {
      const payload = await apiPost<{ ok: boolean; error?: string }>(
        `/cron/jobs/${jobId}/disable?chat_id=${encodeURIComponent(context.chatId)}&username=${encodeURIComponent(
          context.username
        )}`,
        {},
        context.token
      );
      if (!payload.ok) {
        throw new Error(payload.error || "Failed to disable job.");
      }
      await loadJobs();
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  useEffect(() => {
    void loadJobs();
    const timer = window.setInterval(() => void loadJobs(), 6000);
    return () => window.clearInterval(timer);
  }, [context.chatId, context.username, context.token]);

  return (
    <section className="panel">
      <header className="panel-head">
        <h2>Cron Control</h2>
        <p>Requires ops token. Uses existing `/cron/jobs*` APIs.</p>
      </header>
      {error && <p className="error">{error}</p>}
      <article className="subpanel">
        <h3>Create cron job</h3>
        <div className="form-grid">
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="job name" />
          <input
            type="number"
            min={60}
            value={intervalSeconds}
            onChange={(event) => setIntervalSeconds(Number(event.target.value))}
          />
          <textarea value={message} onChange={(event) => setMessage(event.target.value)} rows={2} />
        </div>
        <button onClick={() => void createJob()}>Create cron job</button>
      </article>
      <article className="subpanel">
        <h3>Jobs</h3>
        <div className="list-scroll">
          {jobs.length === 0 && <p className="muted">No cron jobs available.</p>}
          {jobs.map((job) => (
            <div className="list-row static" key={job.job_id}>
              <div>
                <strong>#{job.job_id} {job.name}</strong>
                <p className="muted">
                  every {job.interval_seconds}s runs={job.run_count} next={formatTimestamp(job.next_run_at)}
                </p>
              </div>
              <div className="row-actions">
                <span className={`tag ${job.enabled ? "ok" : "warn"}`}>{job.enabled ? "enabled" : "disabled"}</span>
                {job.enabled && (
                  <button className="danger" onClick={() => void disableJob(job.job_id)}>
                    Disable
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}

type BlackboxPanelProps = {
  context: AppContext;
};

function BlackboxPanel({ context }: BlackboxPanelProps) {
  const [ownerId, setOwnerId] = useState<number | null>(null);
  const [sessions, setSessions] = useState<Array<Record<string, unknown>>>([]);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [error, setError] = useState("");

  const loadOwnerAndSessions = async () => {
    const ctxError = requireUserContext(context) || requireOpsToken(context);
    if (ctxError) {
      setError(ctxError);
      setOwnerId(null);
      setSessions([]);
      return;
    }
    try {
      const me = await apiGet<{ ok: boolean; owner_id?: number; error?: string }>(
        `/ui/me?chat_id=${encodeURIComponent(context.chatId)}&username=${encodeURIComponent(context.username)}`
      );
      if (!me.ok || !me.owner_id) {
        throw new Error(me.error || "Unable to resolve owner.");
      }
      setOwnerId(me.owner_id);
      const result = await apiGet<{ ok: boolean; sessions?: Array<Record<string, unknown>>; error?: string }>(
        `/debug/blackbox/sessions?owner_id=${me.owner_id}&limit=20`,
        context.token
      );
      if (!result.ok) {
        throw new Error(result.error || "Failed to load blackbox sessions.");
      }
      setSessions(Array.isArray(result.sessions) ? result.sessions : []);
      setError("");
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  const loadReport = async (targetSessionId: string) => {
    if (!ownerId || !targetSessionId) {
      return;
    }
    try {
      const payload = await apiGet<Record<string, unknown>>(
        `/debug/blackbox/session_report?owner_id=${ownerId}&session_id=${encodeURIComponent(targetSessionId)}&limit=240&include_timeline=true`,
        context.token
      );
      setReport(payload);
      setSessionId(targetSessionId);
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  useEffect(() => {
    void loadOwnerAndSessions();
  }, [context.chatId, context.username, context.token]);

  return (
    <section className="panel">
      <header className="panel-head">
        <h2>Blackbox Diagnostics</h2>
        <p>Session reports and failure traces for runtime forensics.</p>
      </header>
      {error && <p className="error">{error}</p>}
      <div className="split-grid">
        <article className="subpanel">
          <h3>Sessions</h3>
          <div className="list-scroll">
            {sessions.length === 0 && <p className="muted">No sessions loaded.</p>}
            {sessions.map((item, index) => {
              const sid = String(item.session_id || "");
              const total = String(item.event_count || "-");
              return (
                <button key={`${sid}-${index}`} className="list-row" onClick={() => void loadReport(sid)}>
                  <strong>{sid || "unknown"}</strong>
                  <span>events={total}</span>
                  <span>{String(item.source_type || "-")}</span>
                </button>
              );
            })}
          </div>
        </article>
        <article className="subpanel">
          <h3>Session report {sessionId ? `(${sessionId})` : ""}</h3>
          <pre>{report ? JSON.stringify(report, null, 2) : "Select a session to load report."}</pre>
        </article>
      </div>
    </section>
  );
}

type NodesPanelProps = {
  context: AppContext;
};

function NodesPanel({ context }: NodesPanelProps) {
  const [nodes, setNodes] = useState<Array<Record<string, unknown>>>([]);
  const [plugins, setPlugins] = useState<Array<Record<string, unknown>>>([]);
  const [error, setError] = useState("");

  const loadAll = async () => {
    const tokenError = requireOpsToken(context);
    if (tokenError) {
      setError(tokenError);
      setNodes([]);
      setPlugins([]);
      return;
    }
    try {
      const nodePayload = await apiGet<{ ok: boolean; nodes?: Array<Record<string, unknown>>; error?: string }>(
        "/nodes",
        context.token
      );
      const pluginPayload = await apiGet<{ ok: boolean; tools?: Array<Record<string, unknown>>; error?: string }>(
        "/plugins/tools",
        context.token
      );
      if (!nodePayload.ok) {
        throw new Error(nodePayload.error || "Failed to load nodes.");
      }
      if (!pluginPayload.ok) {
        throw new Error(pluginPayload.error || "Failed to load plugin tools.");
      }
      setNodes(Array.isArray(nodePayload.nodes) ? nodePayload.nodes : []);
      setPlugins(Array.isArray(pluginPayload.tools) ? pluginPayload.tools : []);
      setError("");
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  const reloadPlugins = async () => {
    try {
      const payload = await apiPost<{ ok: boolean; error?: string }>("/plugins/reload", {}, context.token);
      if (!payload.ok) {
        throw new Error(payload.error || "Plugin reload failed.");
      }
      await loadAll();
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  useEffect(() => {
    void loadAll();
  }, [context.token]);

  return (
    <section className="panel">
      <header className="panel-head">
        <h2>Nodes & Plugins</h2>
        <p>Topology and dynamic tool inventory.</p>
      </header>
      {error && <p className="error">{error}</p>}
      <div className="row-actions">
        <button onClick={() => void loadAll()}>Refresh</button>
        <button onClick={() => void reloadPlugins()}>Reload plugins</button>
      </div>
      <div className="split-grid">
        <article className="subpanel">
          <h3>Execution nodes</h3>
          <pre>{JSON.stringify(nodes, null, 2)}</pre>
        </article>
        <article className="subpanel">
          <h3>Plugin tools</h3>
          <pre>{JSON.stringify(plugins, null, 2)}</pre>
        </article>
      </div>
    </section>
  );
}

function App() {
  const [activePanel, setActivePanel] = useState<PanelKey>("runtime");
  const [chatId, setChatId] = useState(() => readSession(STORAGE_CHAT_ID));
  const [username, setUsername] = useState(() => readSession(STORAGE_USERNAME));
  const [token, setToken] = useState(() => readSession(STORAGE_TOKEN));
  const [statusMessage, setStatusMessage] = useState("");

  const [draftChatId, setDraftChatId] = useState(chatId);
  const [draftUsername, setDraftUsername] = useState(username);
  const [draftToken, setDraftToken] = useState(token);

  const context = useMemo<AppContext>(() => ({ chatId, username, token }), [chatId, username, token]);
  const contextReady = hasUserContext(context);

  const saveSettings = () => {
    const normalizedChatId = draftChatId.trim();
    const normalizedUsername = draftUsername.trim();
    const normalizedToken = draftToken.trim();

    setChatId(normalizedChatId);
    setUsername(normalizedUsername);
    setToken(normalizedToken);
    writeSession(STORAGE_CHAT_ID, normalizedChatId);
    writeSession(STORAGE_USERNAME, normalizedUsername);
    writeSession(STORAGE_TOKEN, normalizedToken);
    setStatusMessage("Session settings saved.");
  };

  const clearToken = () => {
    setToken("");
    setDraftToken("");
    writeSession(STORAGE_TOKEN, "");
    setStatusMessage("Ops token cleared from session.");
  };

  return (
    <div className="app-shell">
      <div className="ambient" />
      <aside className="side-nav">
        <header>
          <h1>Bob Command Center</h1>
          <p>OpenClaw-style Ops Console</p>
        </header>
        <nav>
          {PANELS.map((panel) => (
            <button
              key={panel.key}
              className={activePanel === panel.key ? "active" : ""}
              onClick={() => setActivePanel(panel.key)}
            >
              {panel.label}
            </button>
          ))}
        </nav>
        <footer>
          <span className={contextReady ? "badge ok" : "badge warn"}>
            {contextReady ? "user context ready" : "set chat_id + username"}
          </span>
          <span className={context.token ? "badge ok" : "badge warn"}>
            {context.token ? "ops token loaded" : "ops token missing"}
          </span>
        </footer>
      </aside>
      <main className="main-content">
        <PanelErrorBoundary>
          {activePanel === "runtime" && <RuntimePanel context={context} />}
          {activePanel === "chat" && <ChatPanel context={context} />}
          {activePanel === "tasks" && <TasksPanel context={context} />}
          {activePanel === "approvals" && <ApprovalsPanel context={context} />}
          {activePanel === "cron" && <CronPanel context={context} />}
          {activePanel === "blackbox" && <BlackboxPanel context={context} />}
          {activePanel === "nodes" && <NodesPanel context={context} />}
          <SettingsPanel
            draftChatId={draftChatId}
            draftUsername={draftUsername}
            draftToken={draftToken}
            setDraftChatId={setDraftChatId}
            setDraftUsername={setDraftUsername}
            setDraftToken={setDraftToken}
            saveSettings={saveSettings}
            clearToken={clearToken}
            statusMessage={statusMessage}
          />
        </PanelErrorBoundary>
      </main>
    </div>
  );
}

export default App;
