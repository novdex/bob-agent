import { useEffect, useState } from "react";
import { Box, FileText } from "lucide-react";
import { apiGet } from "../../api/client";
import type { AppContext } from "../../types";
import { formatApiError, requireOpsToken, requireUserContext } from "../../utils/errors";
import { JsonTree, ErrorAlert, EmptyState, LoadingSkeleton, StatusBadge } from "../ui";

type BlackboxPanelProps = { context: AppContext };

export function BlackboxPanel({ context }: BlackboxPanelProps) {
  const [ownerId, setOwnerId] = useState<number | null>(null);
  const [sessions, setSessions] = useState<Array<Record<string, unknown>>>([]);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const loadOwnerAndSessions = async () => {
    const ctxError = requireUserContext(context) || requireOpsToken(context);
    if (ctxError) { setError(ctxError); setOwnerId(null); setSessions([]); return; }
    try {
      const me = await apiGet<{ ok: boolean; owner_id?: number; error?: string }>(
        `/ui/me?chat_id=${encodeURIComponent(context.chatId)}&username=${encodeURIComponent(context.username)}`,
      );
      if (!me.ok || !me.owner_id) throw new Error(me.error || "Unable to resolve owner.");
      setOwnerId(me.owner_id);
      const result = await apiGet<{ ok: boolean; sessions?: Array<Record<string, unknown>>; error?: string }>(
        `/debug/blackbox/sessions?owner_id=${me.owner_id}&limit=20`,
        context.token,
      );
      if (!result.ok) throw new Error(result.error || "Failed to load blackbox sessions.");
      setSessions(Array.isArray(result.sessions) ? result.sessions : []);
      setError("");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  };

  const loadReport = async (targetSessionId: string) => {
    if (!ownerId || !targetSessionId) return;
    try {
      const payload = await apiGet<Record<string, unknown>>(
        `/debug/blackbox/session_report?owner_id=${ownerId}&session_id=${encodeURIComponent(targetSessionId)}&limit=240&include_timeline=true`,
        context.token,
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

      {error && <ErrorAlert message={error} onRetry={() => void loadOwnerAndSessions()} onDismiss={() => setError("")} />}
      {loading && <LoadingSkeleton variant="card" />}

      <div className="split-grid">
        {/* Session list */}
        <article className="subpanel">
          <h3>Sessions ({sessions.length})</h3>
          <div className="list-scroll">
            {sessions.length === 0 && !loading && (
              <EmptyState title="No sessions" description="No blackbox sessions recorded yet." icon={Box} />
            )}
            {sessions.map((item, index) => {
              const sid = String(item.session_id || "");
              const total = typeof item.event_count === "number" ? item.event_count : 0;
              const source = String(item.source_type || "-");
              const isSelected = sid === sessionId;
              return (
                <button
                  key={`${sid}-${index}`}
                  className={`list-row ${isSelected ? "active" : ""}`}
                  onClick={() => void loadReport(sid)}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <strong className="truncate" style={{ display: "block", maxWidth: "100%" }}>
                      {sid || "unknown"}
                    </strong>
                    <span className="muted" style={{ fontSize: "0.75rem" }}>
                      {total} events &middot; {source}
                    </span>
                  </div>
                  <StatusBadge
                    label={source}
                    status={source === "api" ? "accent" : source === "telegram" ? "ok" : "muted"}
                    size="sm"
                  />
                </button>
              );
            })}
          </div>
        </article>

        {/* Report viewer */}
        <article className="subpanel">
          <h3>
            <FileText size={14} style={{ verticalAlign: -2 }} />{" "}
            Session Report {sessionId ? `(${sessionId.slice(0, 12)}\u2026)` : ""}
          </h3>
          {!report && <p className="muted">Select a session to load its report.</p>}
          {report && <JsonTree data={report} maxDepth={4} />}
        </article>
      </div>
    </section>
  );
}
