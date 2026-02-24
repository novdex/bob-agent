import { useEffect, useState } from "react";
import { Server, Puzzle, RefreshCw } from "lucide-react";
import { apiGet, apiPost } from "../../api/client";
import type { AppContext } from "../../types";
import { formatApiError, requireOpsToken } from "../../utils/errors";
import { showToast } from "../../hooks/useToast";
import { JsonTree, ErrorAlert, EmptyState, LoadingSkeleton, StatusBadge } from "../ui";

type NodesPanelProps = { context: AppContext };

export function NodesPanel({ context }: NodesPanelProps) {
  const [nodes, setNodes] = useState<Array<Record<string, unknown>>>([]);
  const [plugins, setPlugins] = useState<Array<Record<string, unknown>>>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reloading, setReloading] = useState(false);

  const loadAll = async () => {
    const tokenError = requireOpsToken(context);
    if (tokenError) { setError(tokenError); setNodes([]); setPlugins([]); return; }
    try {
      const [nodePayload, pluginPayload] = await Promise.all([
        apiGet<{ ok: boolean; nodes?: Array<Record<string, unknown>>; error?: string }>("/nodes", context.token),
        apiGet<{ ok: boolean; tools?: Array<Record<string, unknown>>; error?: string }>("/plugins/tools", context.token),
      ]);
      if (!nodePayload.ok) throw new Error(nodePayload.error || "Failed to load nodes.");
      if (!pluginPayload.ok) throw new Error(pluginPayload.error || "Failed to load plugin tools.");
      setNodes(Array.isArray(nodePayload.nodes) ? nodePayload.nodes : []);
      setPlugins(Array.isArray(pluginPayload.tools) ? pluginPayload.tools : []);
      setError("");
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  };

  const reloadPlugins = async () => {
    setReloading(true);
    try {
      const payload = await apiPost<{ ok: boolean; error?: string }>("/plugins/reload", {}, context.token);
      if (!payload.ok) throw new Error(payload.error || "Plugin reload failed.");
      showToast("Plugins reloaded", "success");
      await loadAll();
    } catch (err) {
      showToast(formatApiError(err), "error");
      setError(formatApiError(err));
    } finally {
      setReloading(false);
    }
  };

  useEffect(() => {
    void loadAll();
  }, [context.token]);

  return (
    <section className="panel">
      <header className="panel-head">
        <h2>Nodes &amp; Plugins</h2>
        <p>Topology and dynamic tool inventory.</p>
      </header>

      {error && <ErrorAlert message={error} onRetry={() => void loadAll()} onDismiss={() => setError("")} />}

      <div className="row-actions" style={{ marginBottom: 12 }}>
        <button onClick={() => void loadAll()} style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <RefreshCw size={14} /> Refresh
        </button>
        <button onClick={() => void reloadPlugins()} disabled={reloading} style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <Puzzle size={14} /> {reloading ? "Reloading\u2026" : "Reload plugins"}
        </button>
      </div>

      {loading && <LoadingSkeleton variant="card" />}

      <div className="split-grid">
        {/* Execution nodes */}
        <article className="subpanel">
          <h3><Server size={14} style={{ verticalAlign: -2 }} /> Execution Nodes ({nodes.length})</h3>
          {nodes.length === 0 && !loading && (
            <EmptyState title="No nodes" description="No execution nodes registered." icon={Server} />
          )}
          <div style={{ display: "grid", gap: 8 }}>
            {nodes.map((node, i) => {
              const id = String(node.node_id || node.id || i);
              const status = String(node.status || "unknown");
              const role = String(node.role || "-");
              return (
                <div key={id} className="subpanel" style={{ borderLeft: `3px solid ${status === "active" ? "var(--ok)" : "var(--text-dim)"}` }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <strong>{id}</strong>
                    <StatusBadge
                      label={status}
                      status={status === "active" ? "ok" : status === "draining" ? "warn" : "muted"}
                      size="sm"
                      pulse={status === "active"}
                    />
                    <span className="muted" style={{ marginLeft: "auto", fontSize: "0.78rem" }}>{role}</span>
                  </div>
                  <JsonTree data={node} maxDepth={2} collapsed />
                </div>
              );
            })}
          </div>
        </article>

        {/* Plugin tools */}
        <article className="subpanel">
          <h3><Puzzle size={14} style={{ verticalAlign: -2 }} /> Plugin Tools ({plugins.length})</h3>
          {plugins.length === 0 && !loading && (
            <EmptyState title="No plugins" description="No dynamic tools loaded." icon={Puzzle} />
          )}
          <div style={{ display: "grid", gap: 6 }}>
            {plugins.map((tool, i) => {
              const toolName = String(tool.name || tool.tool_name || `tool-${i}`);
              const desc = String(tool.description || "-");
              return (
                <div key={toolName} className="subpanel" style={{ padding: "8px 12px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Puzzle size={12} style={{ color: "var(--accent-2)", flexShrink: 0 }} />
                    <strong style={{ fontSize: "0.85rem" }}>{toolName}</strong>
                  </div>
                  <p className="muted" style={{ margin: "4px 0 0", fontSize: "0.78rem" }}>{desc}</p>
                </div>
              );
            })}
          </div>
        </article>
      </div>
    </section>
  );
}
