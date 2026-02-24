import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../../api/client";
import type { AppContext, UiApproval } from "../../types";
import { formatApiError, requireUserContext } from "../../utils/errors";

type ApprovalsPanelProps = {
  context: AppContext;
};

export function ApprovalsPanel({ context }: ApprovalsPanelProps) {
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
          reason,
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
