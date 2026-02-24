import { Settings, Key, Trash2, Save } from "lucide-react";

type SettingsPanelProps = {
  draftChatId: string;
  draftUsername: string;
  draftToken: string;
  setDraftChatId: (value: string) => void;
  setDraftUsername: (value: string) => void;
  setDraftToken: (value: string) => void;
  saveSettings: () => void;
  clearToken: () => void;
  statusMessage: string;
};

export function SettingsPanel(props: SettingsPanelProps) {
  const {
    draftChatId,
    draftUsername,
    draftToken,
    setDraftChatId,
    setDraftUsername,
    setDraftToken,
    saveSettings,
    clearToken,
    statusMessage,
  } = props;

  return (
    <section className="panel">
      <header className="panel-head">
        <h2><Settings size={16} style={{ verticalAlign: -2 }} /> Settings</h2>
        <p>Session-only auth and user context. Nothing is persisted beyond this browser session.</p>
      </header>

      <article className="subpanel">
        <h3>Session Identity</h3>
        <div className="settings-grid">
          <label>
            <span>chat_id</span>
            <input
              value={draftChatId}
              onChange={(e) => setDraftChatId(e.target.value)}
              placeholder="e.g. 6346698354"
            />
          </label>
          <label>
            <span>username</span>
            <input
              value={draftUsername}
              onChange={(e) => setDraftUsername(e.target.value)}
              placeholder="telegram username"
            />
          </label>
        </div>
      </article>

      <article className="subpanel">
        <h3><Key size={14} style={{ verticalAlign: -2 }} /> Ops Token</h3>
        <div className="settings-grid">
          <label className="ops-token-row">
            <span>Bearer token (session-only)</span>
            <input
              value={draftToken}
              onChange={(e) => setDraftToken(e.target.value)}
              placeholder="Bearer token for protected routes"
              type="password"
            />
          </label>
        </div>
      </article>

      <div className="settings-actions">
        <button onClick={saveSettings} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Save size={14} /> Save session settings
        </button>
        <button className="ghost" onClick={clearToken} style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Trash2 size={14} /> Clear token
        </button>
      </div>

      {statusMessage && (
        <p style={{ color: "var(--ok)", fontSize: "0.82rem", marginTop: 8 }}>
          {statusMessage}
        </p>
      )}

      <article className="subpanel" style={{ marginTop: 16 }}>
        <h3>Keyboard Shortcuts</h3>
        <div className="muted" style={{ fontSize: "0.78rem", display: "grid", gap: 4 }}>
          <span><kbd style={{ background: "var(--bg-2)", padding: "2px 6px", borderRadius: 4, fontSize: "0.75rem" }}>Ctrl+1-9</kbd> Switch panels</span>
          <span>Panels are numbered top-to-bottom in the sidebar.</span>
        </div>
      </article>

      <article className="subpanel" style={{ marginTop: 8 }}>
        <h3>About</h3>
        <p className="muted" style={{ fontSize: "0.78rem" }}>
          Bob Command Center &middot; AGI Ops Console<br />
          Set <code>chat_id</code> + <code>username</code> to unlock user-scoped panels.<br />
          Add an <code>ops token</code> to access protected routes (Cron, Nodes, Blackbox).
        </p>
      </article>
    </section>
  );
}
