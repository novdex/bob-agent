import { useMemo, useState, useEffect, useCallback } from "react";
import type { AppContext, PanelKey, RuntimePayload } from "./types";
import { STORAGE_CHAT_ID, STORAGE_TOKEN, STORAGE_USERNAME } from "./constants";
import { hasUserContext } from "./utils/errors";
import { readSession, writeSession } from "./hooks/useSessionStorage";
import { useKeyboardNav } from "./hooks/useKeyboardNav";
import { apiGet } from "./api/client";
import { PanelErrorBoundary } from "./components/PanelErrorBoundary";
import { SettingsPanel } from "./components/SettingsPanel";
import { Layout } from "./components/Layout";
import {
  DashboardPanel,
  RuntimePanel,
  ChatPanel,
  TasksPanel,
  ApprovalsPanel,
  CronPanel,
  BlackboxPanel,
  NodesPanel,
  GoalsPanel,
  TeamPanel,
  UsagePanel,
  WorkflowsPanel,
} from "./components/panels";

function App() {
  const [activePanel, setActivePanel] = useState<PanelKey>("dashboard");
  const [chatId, setChatId] = useState(() => readSession(STORAGE_CHAT_ID));
  const [username, setUsername] = useState(() => readSession(STORAGE_USERNAME));
  const [token, setToken] = useState(() => readSession(STORAGE_TOKEN));
  const [statusMessage, setStatusMessage] = useState("");
  const [badgeCounts, setBadgeCounts] = useState({ approvals: 0, alerts: 0 });

  const [draftChatId, setDraftChatId] = useState(chatId);
  const [draftUsername, setDraftUsername] = useState(username);
  const [draftToken, setDraftToken] = useState(token);

  const context = useMemo<AppContext>(() => ({ chatId, username, token }), [chatId, username, token]);
  const contextReady = hasUserContext(context);

  // Keyboard nav: Ctrl+1-9 switches panels
  useKeyboardNav(setActivePanel);

  // Poll badge counts from runtime
  const fetchBadges = useCallback(async () => {
    try {
      const rt = await apiGet<RuntimePayload>("/status/runtime");
      setBadgeCounts({
        approvals: typeof rt.approval_pending_count === "number" ? rt.approval_pending_count : 0,
        alerts: typeof rt.runtime_alert_count === "number" ? rt.runtime_alert_count : 0,
      });
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    fetchBadges();
    const t = setInterval(fetchBadges, 10000);
    return () => clearInterval(t);
  }, [fetchBadges]);

  const saveSettings = () => {
    const nc = draftChatId.trim(), nu = draftUsername.trim(), nt = draftToken.trim();
    setChatId(nc); setUsername(nu); setToken(nt);
    writeSession(STORAGE_CHAT_ID, nc); writeSession(STORAGE_USERNAME, nu); writeSession(STORAGE_TOKEN, nt);
    setStatusMessage("Session settings saved.");
  };

  const clearToken = () => {
    setToken(""); setDraftToken(""); writeSession(STORAGE_TOKEN, "");
    setStatusMessage("Ops token cleared.");
  };

  return (
    <Layout
      activePanel={activePanel}
      setActivePanel={setActivePanel}
      contextReady={contextReady}
      hasToken={Boolean(context.token)}
      badgeCounts={badgeCounts}
    >
      <PanelErrorBoundary>
        {activePanel === "dashboard" && <DashboardPanel context={context} setActivePanel={setActivePanel} />}
        {activePanel === "runtime" && <RuntimePanel context={context} />}
        {activePanel === "chat" && <ChatPanel context={context} />}
        {activePanel === "tasks" && <TasksPanel context={context} />}
        {activePanel === "approvals" && <ApprovalsPanel context={context} />}
        {activePanel === "cron" && <CronPanel context={context} />}
        {activePanel === "blackbox" && <BlackboxPanel context={context} />}
        {activePanel === "nodes" && <NodesPanel context={context} />}
        {activePanel === "goals" && <GoalsPanel context={context} />}
        {activePanel === "team" && <TeamPanel context={context} />}
        {activePanel === "usage" && <UsagePanel context={context} />}
        {activePanel === "workflows" && <WorkflowsPanel context={context} />}
        <SettingsPanel
          draftChatId={draftChatId} draftUsername={draftUsername} draftToken={draftToken}
          setDraftChatId={setDraftChatId} setDraftUsername={setDraftUsername} setDraftToken={setDraftToken}
          saveSettings={saveSettings} clearToken={clearToken} statusMessage={statusMessage}
        />
      </PanelErrorBoundary>
    </Layout>
  );
}

export default App;
