import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../../api/client";
import type { AppContext, CronJob } from "../../types";
import { formatApiError, requireOpsToken, requireUserContext } from "../../utils/errors";
import { formatTimestamp } from "../../utils/formatters";

type CronPanelProps = {
  context: AppContext;
};

export function CronPanel({ context }: CronPanelProps) {
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
          lane: "cron",
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
