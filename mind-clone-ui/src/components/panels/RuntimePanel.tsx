import { useMemo, useState } from "react";
import { apiGet } from "../../api/client";
import type { AppContext, RuntimePayload } from "../../types";
import { formatApiError } from "../../utils/errors";
import { runtimeStat } from "../../utils/formatters";
import { usePolling } from "../../hooks/usePolling";

type RuntimePanelProps = {
  context: AppContext;
};

export function RuntimePanel({ context }: RuntimePanelProps) {
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

  usePolling(loadRuntime, 5000);

  const statusCards = useMemo(
    () => [
      { label: "Worker alive", value: runtimeStat(runtime, "worker_alive") },
      { label: "Spine alive", value: runtimeStat(runtime, "spine_supervisor_alive") },
      { label: "Webhook", value: runtimeStat(runtime, "webhook_registered") },
      { label: "DB healthy", value: runtimeStat(runtime, "db_healthy") },
      { label: "Queue size", value: runtimeStat(runtime, "command_queue_size") },
      { label: "Pending approvals", value: runtimeStat(runtime, "approval_pending_count") },
      { label: "Runtime alerts", value: runtimeStat(runtime, "runtime_alert_count") },
      { label: "Active model", value: runtimeStat(runtime, "llm_last_model_used") },
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
