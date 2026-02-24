import { useEffect, useState } from "react";
import { apiGet } from "../../api/client";
import type { AppContext } from "../../types";
import { formatApiError, requireOpsToken, requireUserContext } from "../../utils/errors";

type BlackboxPanelProps = {
  context: AppContext;
};

export function BlackboxPanel({ context }: BlackboxPanelProps) {
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
