import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../../api/client";
import type { AppContext } from "../../types";
import { formatApiError, requireOpsToken } from "../../utils/errors";

type NodesPanelProps = {
  context: AppContext;
};

export function NodesPanel({ context }: NodesPanelProps) {
  const [nodes, setNodes] = useState<Array<Record<string, unknown>>>([]);
  const [plugins, setPlugins] = useState<Array<Record<string, unknown>>>([]);
  const [error, setError] = useState("");

  const loadAll = async () => {
    const tokenError = requireOpsToken(context);
    if (tokenError) {
      setError(tokenError);
      setNodes([]);
      setPlugins([]);
      return;
    }
    try {
      const nodePayload = await apiGet<{ ok: boolean; nodes?: Array<Record<string, unknown>>; error?: string }>(
        "/nodes",
        context.token
      );
      const pluginPayload = await apiGet<{ ok: boolean; tools?: Array<Record<string, unknown>>; error?: string }>(
        "/plugins/tools",
        context.token
      );
      if (!nodePayload.ok) {
        throw new Error(nodePayload.error || "Failed to load nodes.");
      }
      if (!pluginPayload.ok) {
        throw new Error(pluginPayload.error || "Failed to load plugin tools.");
      }
      setNodes(Array.isArray(nodePayload.nodes) ? nodePayload.nodes : []);
      setPlugins(Array.isArray(pluginPayload.tools) ? pluginPayload.tools : []);
      setError("");
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  const reloadPlugins = async () => {
    try {
      const payload = await apiPost<{ ok: boolean; error?: string }>("/plugins/reload", {}, context.token);
      if (!payload.ok) {
        throw new Error(payload.error || "Plugin reload failed.");
      }
      await loadAll();
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  useEffect(() => {
    void loadAll();
  }, [context.token]);

  return (
    <section className="panel">
      <header className="panel-head">
        <h2>Nodes & Plugins</h2>
        <p>Topology and dynamic tool inventory.</p>
      </header>
      {error && <p className="error">{error}</p>}
      <div className="row-actions">
        <button onClick={() => void loadAll()}>Refresh</button>
        <button onClick={() => void reloadPlugins()}>Reload plugins</button>
      </div>
      <div className="split-grid">
        <article className="subpanel">
          <h3>Execution nodes</h3>
          <pre>{JSON.stringify(nodes, null, 2)}</pre>
        </article>
        <article className="subpanel">
          <h3>Plugin tools</h3>
          <pre>{JSON.stringify(plugins, null, 2)}</pre>
        </article>
      </div>
    </section>
  );
}
