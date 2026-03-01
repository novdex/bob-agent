import { useEffect, useState } from "react";
import { Clock, Plus, Power, PowerOff } from "lucide-react";
import { apiGet, apiPost } from "../../api/client";
import type { AppContext, CronJob } from "../../types";
import { formatApiError, requireOpsToken, requireUserContext } from "../../utils/errors";
import { formatTimestamp, formatDuration } from "../../utils/formatters";
import { showToast } from "../../hooks/useToast";
import { StatusBadge, ErrorAlert, EmptyState, LoadingSkeleton } from "../ui";

type CronPanelProps = { context: AppContext };

export function CronPanel({ context }: CronPanelProps) {
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [name, setName] = useState("ui_cron_job");
  const [message, setMessage] = useState("Run heartbeat self-check and summarize alerts.");
  const [intervalSeconds, setIntervalSeconds] = useState(300);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const loadJobs = async () => {
    const ctxError = requireUserContext(context) || requireOpsToken(context);
    if (ctxError) { setError(ctxError); setJobs([]); return; }
    try {
      const payload = await apiGet<{ ok: boolean; jobs?: CronJob[]; error?: string }>(
        `/cron/jobs?chat_id=${encodeURIComponent(context.chatId)}&username=${encodeURIComponent(context.username)}&include_disabled=true&limit=40`,
        context.token,
      );
      if (!payload.ok) throw new Error(payload.error || "Failed to load cron jobs.");
      setJobs(Array.isArray(payload.jobs) ? payload.jobs : []);
      setError("");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  };

  const createJob = async () => {
    const ctxError = requireUserContext(context) || requireOpsToken(context);
    if (ctxError) { setError(ctxError); return; }
    try {
      const payload = await apiPost<{ ok: boolean; error?: string }>(
        "/cron/jobs",
        { chat_id: context.chatId, username: context.username, name, message, interval_seconds: Number(intervalSeconds), lane: "cron" },
        context.token,
      );
      if (!payload.ok) throw new Error(payload.error || "Failed to create cron job.");
      showToast(`Cron job "${name}" created`, "success");
      await loadJobs();
    } catch (err) {
      showToast(formatApiError(err), "error");
      setError(formatApiError(err));
    }
  };

  const disableJob = async (jobId: number) => {
    try {
      const payload = await apiPost<{ ok: boolean; error?: string }>(
        `/cron/jobs/${jobId}/disable?chat_id=${encodeURIComponent(context.chatId)}&username=${encodeURIComponent(context.username)}`,
        {},
        context.token,
      );
      if (!payload.ok) throw new Error(payload.error || "Failed to disable job.");
      showToast(`Job #${jobId} disabled`, "success");
      await loadJobs();
    } catch (err) {
      showToast(formatApiError(err), "error");
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
        <p>Scheduled jobs &middot; Requires ops token</p>
      </header>

      {error && <ErrorAlert message={error} onRetry={() => void loadJobs()} onDismiss={() => setError("")} />}

      {/* Create form */}
      <article className="subpanel">
        <h3><Plus size={14} style={{ verticalAlign: -2 }} /> Create Cron Job</h3>
        <div className="form-grid">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Job name" />
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <label style={{ whiteSpace: "nowrap", fontSize: "0.82rem" }}>Interval</label>
            <input
              type="number"
              min={60}
              value={intervalSeconds}
              onChange={(e) => setIntervalSeconds(Number(e.target.value))}
              style={{ width: 90 }}
            />
            <span className="muted" style={{ fontSize: "0.78rem" }}>
              ({formatDuration(intervalSeconds)})
            </span>
          </div>
          <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={2} placeholder="Job message / command" />
        </div>
        <button onClick={() => void createJob()}>Create cron job</button>
      </article>

      {loading && <LoadingSkeleton variant="card" />}

      {/* Job cards */}
      <article className="subpanel">
        <h3>Scheduled Jobs ({jobs.length})</h3>
        {jobs.length === 0 && !loading && (
          <EmptyState title="No cron jobs" description="Create a job above to schedule recurring commands." icon={Clock} />
        )}
        <div style={{ display: "grid", gap: 10 }}>
          {jobs.map((job) => (
            <div
              key={job.job_id}
              className="subpanel"
              style={{ borderLeft: `3px solid ${job.enabled ? "var(--ok)" : "var(--text-dim)"}` }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <strong>#{job.job_id} {job.name}</strong>
                <StatusBadge
                  label={job.enabled ? "enabled" : "disabled"}
                  status={job.enabled ? "ok" : "muted"}
                  size="sm"
                />
                {job.enabled && (
                  <button
                    className="ghost danger"
                    onClick={() => void disableJob(job.job_id)}
                    style={{ marginLeft: "auto", padding: "3px 8px", display: "flex", alignItems: "center", gap: 4, fontSize: "0.78rem" }}
                  >
                    <PowerOff size={12} /> Disable
                  </button>
                )}
                {!job.enabled && (
                  <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 4, fontSize: "0.78rem", color: "var(--text-dim)" }}>
                    <Power size={12} /> Inactive
                  </span>
                )}
              </div>
              <div className="muted" style={{ fontSize: "0.78rem", display: "flex", flexWrap: "wrap", gap: "6px 16px" }}>
                <span>every {formatDuration(job.interval_seconds)}</span>
                <span>runs: {job.run_count}</span>
                {job.next_run_at && <span>next: {formatTimestamp(job.next_run_at)}</span>}
                {job.last_run_at && <span>last: {formatTimestamp(job.last_run_at)}</span>}
              </div>
              {job.last_error && (
                <p style={{ color: "var(--danger)", fontSize: "0.78rem", margin: "6px 0 0" }}>
                  {job.last_error}
                </p>
              )}
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}
