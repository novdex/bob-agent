import { useState, useEffect, useCallback } from "react";
import { Users, Plus, Send, Power } from "lucide-react";
import { apiGet, apiPost } from "../../api/client";
import { usePolling } from "../../hooks/usePolling";
import { showToast } from "../../hooks/useToast";
import { formatApiError, requireUserContext } from "../../utils/errors";
import { StatusBadge, EmptyState, LoadingSkeleton, ErrorAlert } from "../ui";
import { formatRelativeTime } from "../../utils/formatters";
import type { AppContext, TeamAgent } from "../../types";

type Props = { context: AppContext };
type LogItem = { role: string; text: string; ts: string };

export function TeamPanel({ context }: Props) {
  const ctxError = requireUserContext(context);
  const [agents, setAgents] = useState<TeamAgent[]>([]);
  const [selected, setSelected] = useState<TeamAgent | null>(null);
  const [log, setLog] = useState<LogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [spawnKey, setSpawnKey] = useState("");
  const [spawnName, setSpawnName] = useState("");
  const [msg, setMsg] = useState("");
  const [activeCount, setActiveCount] = useState(0);

  const fetchAgents = useCallback(async () => {
    if (ctxError) return;
    try {
      const res = await apiGet<{ agents: TeamAgent[] }>(`/agents/list?chat_id=${context.chatId}&username=${context.username}&include_stopped=true`);
      setAgents(res.agents ?? []);
      setActiveCount((res.agents ?? []).filter((a) => a.status === "active").length);
    } catch (e) { setError(formatApiError(e)); }
    finally { setLoading(false); }
  }, [context.chatId, context.username, ctxError]);

  useEffect(() => { fetchAgents(); }, [fetchAgents]);
  usePolling(fetchAgents, 6000);

  useEffect(() => {
    if (!selected) { setLog([]); return; }
    apiGet<{ items: LogItem[] }>(`/agents/log?chat_id=${context.chatId}&agent_key=${selected.agent_key}&limit=20`)
      .then((r) => setLog(r.items ?? []))
      .catch(() => setLog([]));
  }, [selected, context.chatId]);

  if (ctxError) {
    return (
      <section className="panel">
        <div className="panel-head"><h2><Users size={18} /> Team Agents</h2></div>
        <EmptyState title="User context required" description={ctxError} />
      </section>
    );
  }

  async function spawnAgent() {
    if (!spawnKey.trim()) return;
    try {
      await apiPost("/agents/spawn", { chat_id: Number(context.chatId), agent_key: spawnKey.trim(), display_name: spawnName || spawnKey });
      showToast("Agent spawned", "success");
      setSpawnKey(""); setSpawnName("");
      fetchAgents();
    } catch (e) { showToast(formatApiError(e), "error"); }
  }

  async function sendMessage() {
    if (!selected || !msg.trim()) return;
    try {
      await apiPost("/agents/send", { chat_id: Number(context.chatId), agent_key: selected.agent_key, message: msg.trim() });
      showToast("Message sent", "success");
      setMsg("");
    } catch (e) { showToast(formatApiError(e), "error"); }
  }

  async function toggleAgent(agent: TeamAgent) {
    try {
      await apiPost("/agents/stop", { chat_id: Number(context.chatId), agent_key: agent.agent_key, stop: agent.status === "active" });
      showToast(agent.status === "active" ? "Agent stopped" : "Agent started", "success");
      fetchAgents();
    } catch (e) { showToast(formatApiError(e), "error"); }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <h2><Users size={18} /> Team Agents</h2>
        <p className="muted">{activeCount} active / {agents.length} total</p>
      </div>

      {/* Spawn form */}
      <div className="subpanel">
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input placeholder="agent_key" value={spawnKey} onChange={(e) => setSpawnKey(e.target.value)} style={{ flex: 1 }} />
          <input placeholder="display name" value={spawnName} onChange={(e) => setSpawnName(e.target.value)} style={{ flex: 1 }} />
          <button onClick={spawnAgent} disabled={!spawnKey.trim()}><Plus size={14} /> Spawn</button>
        </div>
      </div>

      {error && <ErrorAlert message={error} onRetry={fetchAgents} />}

      <div className="split-grid">
        <div className="subpanel">
          <h3>Agents</h3>
          {loading ? <LoadingSkeleton lines={4} /> : agents.length === 0 ? (
            <EmptyState title="No agents" description="Spawn your first team agent" />
          ) : (
            <div className="list-scroll" style={{ marginTop: 8 }}>
              {agents.map((a) => (
                <div key={a.agent_key} className={`list-row${selected?.agent_key === a.agent_key ? " active" : ""}`} onClick={() => setSelected(a)}>
                  <StatusBadge label="" status={a.status === "active" ? "ok" : "muted"} pulse={a.status === "active"} />
                  <span className="truncate">{a.display_name || a.agent_key}</span>
                  <span className="muted" style={{ fontSize: "0.72rem" }}>{formatRelativeTime(a.last_seen_at)}</span>
                  <button className="ghost" style={{ padding: "2px 6px" }} onClick={(e) => { e.stopPropagation(); toggleAgent(a); }}>
                    <Power size={13} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="subpanel">
          <h3>{selected ? selected.display_name || selected.agent_key : "Conversation"}</h3>
          {selected ? (
            <>
              <div className="list-scroll" style={{ maxHeight: 240, marginTop: 8 }}>
                {log.length === 0 ? <p className="muted" style={{ fontSize: "0.82rem" }}>No messages yet</p> : log.map((l, i) => (
                  <div key={i} style={{ fontSize: "0.82rem", padding: "4px 0", borderBottom: "1px solid var(--line)" }}>
                    <strong>{l.role}</strong>: {l.text}
                  </div>
                ))}
              </div>
              <div className="chat-input-wrap" style={{ marginTop: 8 }}>
                <input placeholder="Send to agent..." value={msg} onChange={(e) => setMsg(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") sendMessage(); }} />
                <button onClick={sendMessage} disabled={!msg.trim()}><Send size={14} /></button>
              </div>
            </>
          ) : <p className="muted" style={{ marginTop: 8 }}>Select an agent</p>}
        </div>
      </div>
    </section>
  );
}
