import { useMemo, useState } from "react";
import {
  Activity, Database, Layers, Cpu, AlertTriangle,
  Shield, Radio, Zap,
} from "lucide-react";
import { apiGet } from "../../api/client";
import type { AppContext, RuntimePayload } from "../../types";
import { formatApiError } from "../../utils/errors";
import { runtimeStat } from "../../utils/formatters";
import { usePolling } from "../../hooks/usePolling";
import { StatCard, JsonTree, ErrorAlert, LoadingSkeleton } from "../ui";

type RuntimePanelProps = {
  context: AppContext;
};

type CardDef = {
  label: string;
  key: string;
  icon: typeof Activity;
  color?: string;
};

const healthCards: CardDef[] = [
  { label: "Worker alive", key: "worker_alive", icon: Cpu, color: "var(--ok)" },
  { label: "Spine alive", key: "spine_supervisor_alive", icon: Activity, color: "var(--ok)" },
  { label: "DB healthy", key: "db_healthy", icon: Database, color: "var(--ok)" },
  { label: "Webhook", key: "webhook_registered", icon: Radio, color: "var(--accent)" },
];

const perfCards: CardDef[] = [
  { label: "Queue size", key: "command_queue_size", icon: Layers },
  { label: "Pending approvals", key: "approval_pending_count", icon: Shield, color: "var(--warn)" },
  { label: "Runtime alerts", key: "runtime_alert_count", icon: AlertTriangle, color: "var(--danger)" },
  { label: "Active model", key: "llm_last_model_used", icon: Zap, color: "var(--accent-2)" },
];

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

  const healthValues = useMemo(
    () => healthCards.map((c) => ({ ...c, value: runtimeStat(runtime, c.key) })),
    [runtime],
  );

  const perfValues = useMemo(
    () => perfCards.map((c) => ({ ...c, value: runtimeStat(runtime, c.key) })),
    [runtime],
  );

  if (!runtime && !error) return <LoadingSkeleton variant="card" />;

  return (
    <section className="panel">
      <header className="panel-head">
        <h2>Runtime Health</h2>
        <p>Polled every 5 s &middot; <code>/status/runtime</code></p>
      </header>

      {error && <ErrorAlert message={error} onRetry={() => void loadRuntime()} onDismiss={() => setError("")} />}

      {/* Health section */}
      <h3 style={{ margin: "16px 0 8px" }}>System Health</h3>
      <div className="stat-grid">
        {healthValues.map((c) => (
          <StatCard
            key={c.key}
            label={c.label}
            value={c.value}
            icon={c.icon}
            color={c.value === "yes" ? "var(--ok)" : c.value === "no" ? "var(--danger)" : c.color}
          />
        ))}
      </div>

      {/* Performance section */}
      <h3 style={{ margin: "16px 0 8px" }}>Performance &amp; LLM</h3>
      <div className="stat-grid">
        {perfValues.map((c) => (
          <StatCard key={c.key} label={c.label} value={c.value} icon={c.icon} color={c.color} />
        ))}
      </div>

      {/* Context summary */}
      <article className="subpanel" style={{ marginTop: 12 }}>
        <h3>Session Context</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
          <div>
            <span className="stat-card-label">chat_id</span>
            <code style={{ display: "block", marginTop: 4 }}>{context.chatId || "-"}</code>
          </div>
          <div>
            <span className="stat-card-label">username</span>
            <code style={{ display: "block", marginTop: 4 }}>{context.username || "-"}</code>
          </div>
          <div>
            <span className="stat-card-label">ops token</span>
            <code style={{ display: "block", marginTop: 4 }}>{context.token ? "loaded" : "missing"}</code>
          </div>
        </div>
      </article>

      {/* Raw JSON viewer */}
      <article className="subpanel" style={{ marginTop: 12 }}>
        <h3>Raw Runtime Data</h3>
        {runtime ? <JsonTree data={runtime} /> : <p className="muted">Loading...</p>}
      </article>
    </section>
  );
}
