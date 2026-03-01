import { useState, useEffect, useCallback } from "react";
import { Workflow, Play, Save } from "lucide-react";
import { apiGet, apiPost } from "../../api/client";
import { usePolling } from "../../hooks/usePolling";
import { showToast } from "../../hooks/useToast";
import { formatApiError, requireUserContext } from "../../utils/errors";
import { EmptyState, LoadingSkeleton, ErrorAlert, JsonTree } from "../ui";
import { formatRelativeTime, clampString } from "../../utils/formatters";
import type { AppContext, WorkflowProgram } from "../../types";

type Props = { context: AppContext };
type RunResult = { ok: boolean; steps?: number; events?: unknown[]; error?: string };

export function WorkflowsPanel({ context }: Props) {
  const ctxError = requireUserContext(context);
  const [programs, setPrograms] = useState<WorkflowProgram[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [running, setRunning] = useState(false);

  const fetchPrograms = useCallback(async () => {
    if (ctxError) return;
    try {
      const res = await apiGet<{ programs: WorkflowProgram[] }>(`/workflow/programs?chat_id=${context.chatId}&username=${context.username}`);
      setPrograms(res.programs ?? []);
    } catch (e) { setError(formatApiError(e)); }
    finally { setLoading(false); }
  }, [context.chatId, context.username, ctxError]);

  useEffect(() => { fetchPrograms(); }, [fetchPrograms]);
  usePolling(fetchPrograms, 10000);

  if (ctxError) {
    return (
      <section className="panel">
        <div className="panel-head"><h2><Workflow size={18} /> Workflows</h2></div>
        <EmptyState title="User context required" description={ctxError} />
      </section>
    );
  }

  async function saveProgram() {
    if (!name.trim() || !body.trim()) return;
    try {
      await apiPost("/workflow/programs", { chat_id: Number(context.chatId), name: name.trim(), body: body.trim() });
      showToast("Program saved", "success");
      fetchPrograms();
    } catch (e) { showToast(formatApiError(e), "error"); }
  }

  async function runWorkflow(programName?: string) {
    setRunning(true);
    setRunResult(null);
    try {
      const payload = programName
        ? { chat_id: Number(context.chatId), name: programName }
        : { chat_id: Number(context.chatId), body: body.trim() };
      const res = await apiPost<RunResult>("/workflow/run", payload);
      setRunResult(res);
      showToast(res.ok ? "Workflow completed" : "Workflow failed", res.ok ? "success" : "error");
    } catch (e) { showToast(formatApiError(e), "error"); }
    finally { setRunning(false); }
  }

  function loadProgram(p: WorkflowProgram) {
    setName(p.name);
    setBody(p.preview);
  }

  return (
    <section className="panel">
      <div className="panel-head"><h2><Workflow size={18} /> Workflows</h2><p className="muted">Create &amp; run workflow programs</p></div>

      {/* Editor */}
      <div className="subpanel">
        <div className="form-grid">
          <input placeholder="Program name" value={name} onChange={(e) => setName(e.target.value)} />
          <textarea rows={6} placeholder="Workflow body (set/if/loop/sleep/task/send/broadcast)..." value={body} onChange={(e) => setBody(e.target.value)} style={{ fontFamily: "var(--font-mono)", fontSize: "0.82rem" }} />
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={saveProgram} disabled={!name.trim() || !body.trim()}><Save size={14} /> Save</button>
            <button onClick={() => runWorkflow()} disabled={!body.trim() || running}><Play size={14} /> {running ? "Running..." : "Run Inline"}</button>
          </div>
        </div>
      </div>

      {error && <ErrorAlert message={error} onRetry={fetchPrograms} />}

      <div className="split-grid">
        <div className="subpanel">
          <h3>Saved Programs</h3>
          {loading ? <LoadingSkeleton lines={3} /> : programs.length === 0 ? (
            <EmptyState title="No programs" description="Write your first workflow above" />
          ) : (
            <div className="list-scroll" style={{ marginTop: 8 }}>
              {programs.map((p) => (
                <div key={p.name} className="list-row" onClick={() => loadProgram(p)}>
                  <Workflow size={14} style={{ color: "var(--accent-2)" }} />
                  <span>
                    <strong>{p.name}</strong>
                    <span className="muted" style={{ display: "block", fontSize: "0.72rem" }}>{clampString(p.preview, 60)}</span>
                  </span>
                  <span className="muted" style={{ fontSize: "0.72rem" }}>{formatRelativeTime(p.updated_at)}</span>
                  <button className="ghost" style={{ padding: "2px 8px", fontSize: "0.75rem" }} onClick={(e) => { e.stopPropagation(); runWorkflow(p.name); }} disabled={running}>
                    <Play size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="subpanel">
          <h3>Run Result</h3>
          {runResult ? (
            <div style={{ marginTop: 8 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
                <span className={`tag ${runResult.ok ? "ok" : "danger"}`}>{runResult.ok ? "Success" : "Failed"}</span>
                {runResult.steps !== undefined && <span className="muted" style={{ fontSize: "0.82rem" }}>{runResult.steps} steps</span>}
              </div>
              {runResult.events && <JsonTree data={runResult.events} maxDepth={3} />}
              {runResult.error && <p className="error">{runResult.error}</p>}
            </div>
          ) : <p className="muted" style={{ marginTop: 8 }}>Run a workflow to see results</p>}
        </div>
      </div>
    </section>
  );
}
