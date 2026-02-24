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
        <h2>Settings</h2>
        <p>Session-only auth and user context. Nothing is persisted beyond this browser session.</p>
      </header>
      <div className="settings-grid">
        <label>
          <span>chat_id</span>
          <input
            value={draftChatId}
            onChange={(event) => setDraftChatId(event.target.value)}
            placeholder="e.g. 6346698354"
          />
        </label>
        <label>
          <span>username</span>
          <input
            value={draftUsername}
            onChange={(event) => setDraftUsername(event.target.value)}
            placeholder="telegram username"
          />
        </label>
        <label className="ops-token-row">
          <span>ops token (session)</span>
          <input
            value={draftToken}
            onChange={(event) => setDraftToken(event.target.value)}
            placeholder="Bearer token for protected routes"
            type="password"
          />
        </label>
      </div>
      <div className="settings-actions">
        <button onClick={saveSettings}>Save session settings</button>
        <button className="ghost" onClick={clearToken}>
          Clear token
        </button>
      </div>
      <p className="muted">{statusMessage || "Set chat_id + username to unlock user-scoped panels."}</p>
    </section>
  );
}
