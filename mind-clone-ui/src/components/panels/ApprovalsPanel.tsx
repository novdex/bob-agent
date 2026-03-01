import { useEffect, useState } from "react";
import { Shield, CheckCircle2, XCircle, Clock } from "lucide-react";
import { apiGet, apiPost } from "../../api/client";
import type { AppContext, UiApproval } from "../../types";
import { formatApiError, requireUserContext } from "../../utils/errors";
import { formatRelativeTime } from "../../utils/formatters";
import { showToast } from "../../hooks/useToast";
import { ErrorAlert, EmptyState, StatusBadge, LoadingSkeleton } from "../ui";

type ApprovalsPanelProps = { context: AppContext };

function expiresLabel(expiresAt: string | null | undefined): string {
  if (!expiresAt) return "";
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (ms <= 0) return "expired";
  const mins = Math.ceil(ms / 60_000);
  return mins < 60 ? `${mins}m left` : `${Math.floor(mins / 60)}h ${mins % 60}m left`;
}

export function ApprovalsPanel({ context }: ApprovalsPanelProps) {
  const [approvals, setApprovals] = useState<UiApproval[]>([]);
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");
  const [busyToken, setBusyToken] = useState("");
  const [loading, setLoading] = useState(true);

  const loadApprovals = async () => {
    const ctxError = requireUserContext(context);
    if (ctxError) { setError(ctxError); setApprovals([]); return; }
    try {
      const payload = await apiGet<{ ok: boolean; approvals?: UiApproval[]; error?: string }>(
        `/ui/approvals/pending?chat_id=${encodeURIComponent(context.chatId)}&username=${encodeURIComponent(context.username)}&limit=30`,
      );
      if (!payload.ok) throw new Error(payload.error || "Failed to load pending approvals.");
      setApprovals(Array.isArray(payload.approvals) ? payload.approvals : []);
      setError("");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  };

  const decideApproval = async (token: string, approve: boolean) => {
    setBusyToken(token);
    try {
      const payload = await apiPost<{ ok: boolean; error?: string }>(
        "/approval/decision",
        { chat_id: context.chatId, username: context.username, token, approve, reason },
      );
      if (!payload.ok) throw new Error(payload.error || "Approval decision failed.");
      showToast(approve ? "Approved" : "Rejected", approve ? "success" : "info");
      await loadApprovals();
    } catch (err) {
      showToast(formatApiError(err), "error");
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

      {error && <ErrorAlert message={error} onRetry={() => void loadApprovals()} onDismiss={() => setError("")} />}

      <article className="subpanel">
        <h3>Decision reason (optional)</h3>
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder="Add context to your decision..." />
      </article>

      {loading && <LoadingSkeleton variant="card" />}

      <article className="subpanel">
        <h3>
          Pending Approvals
          {approvals.length > 0 && (
            <span className="nav-badge" style={{ marginLeft: 8 }}>{approvals.length}</span>
          )}
        </h3>

        {approvals.length === 0 && !loading && (
          <EmptyState
            title="No pending approvals"
            description="All clear — no tool actions awaiting your decision."
            icon={Shield}
          />
        )}

        <div style={{ display: "grid", gap: 10 }}>
          {approvals.map((approval) => {
            const expires = expiresLabel(approval.expires_at);
            const isExpired = expires === "expired";
            return (
              <div
                key={approval.token}
                className="subpanel"
                style={{
                  borderLeft: `3px solid ${isExpired ? "var(--danger)" : "var(--warn)"}`,
                  opacity: isExpired ? 0.6 : 1,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <strong style={{ flex: 1 }}>{approval.tool_name}</strong>
                  <StatusBadge
                    label={isExpired ? "expired" : "pending"}
                    status={isExpired ? "danger" : "warn"}
                    pulse={!isExpired}
                    size="sm"
                  />
                </div>

                <div className="muted" style={{ fontSize: "0.78rem", marginBottom: 8 }}>
                  <span>source: {approval.source_type}</span>
                  {approval.step_id && <span> &middot; step: {approval.step_id}</span>}
                  {approval.created_at && <span> &middot; {formatRelativeTime(approval.created_at)}</span>}
                  {expires && (
                    <span style={{ marginLeft: 8 }}>
                      <Clock size={11} style={{ verticalAlign: -1 }} /> {expires}
                    </span>
                  )}
                </div>

                <div className="row-actions">
                  <button
                    onClick={() => void decideApproval(approval.token, true)}
                    disabled={busyToken === approval.token || isExpired}
                    style={{ display: "flex", alignItems: "center", gap: 4 }}
                  >
                    <CheckCircle2 size={14} /> Approve
                  </button>
                  <button
                    className="danger"
                    onClick={() => void decideApproval(approval.token, false)}
                    disabled={busyToken === approval.token || isExpired}
                    style={{ display: "flex", alignItems: "center", gap: 4 }}
                  >
                    <XCircle size={14} /> Reject
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </article>
    </section>
  );
}
