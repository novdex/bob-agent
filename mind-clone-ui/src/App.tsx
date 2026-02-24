import { useMemo, useState } from "react";
import type { AppContext, PanelKey } from "./types";
import { STORAGE_CHAT_ID, STORAGE_TOKEN, STORAGE_USERNAME } from "./constants";
import { hasUserContext } from "./utils/errors";
import { readSession, writeSession } from "./hooks/useSessionStorage";
import { PanelErrorBoundary } from "./components/PanelErrorBoundary";
import { SettingsPanel } from "./components/SettingsPanel";
import { Layout } from "./components/Layout";
import {
  RuntimePanel,
  ChatPanel,
  TasksPanel,
  ApprovalsPanel,
  CronPanel,
  BlackboxPanel,
  NodesPanel,
} from "./components/panels";

function App() {
  const [activePanel, setActivePanel] = useState<PanelKey>("runtime");
  const [chatId, setChatId] = useState(() => readSession(STORAGE_CHAT_ID));
  const [username, setUsername] = useState(() => readSession(STORAGE_USERNAME));
  const [token, setToken] = useState(() => readSession(STORAGE_TOKEN));
  const [statusMessage, setStatusMessage] = useState("");

  const [draftChatId, setDraftChatId] = useState(chatId);
  const [draftUsername, setDraftUsername] = useState(username);
  const [draftToken, setDraftToken] = useState(token);

  const context = useMemo<AppContext>(() => ({ chatId, username, token }), [chatId, username, token]);
  const contextReady = hasUserContext(context);

  const saveSettings = () => {
    const normalizedChatId = draftChatId.trim();
    const normalizedUsername = draftUsername.trim();
    const normalizedToken = draftToken.trim();

    setChatId(normalizedChatId);
    setUsername(normalizedUsername);
    setToken(normalizedToken);
    writeSession(STORAGE_CHAT_ID, normalizedChatId);
    writeSession(STORAGE_USERNAME, normalizedUsername);
    writeSession(STORAGE_TOKEN, normalizedToken);
    setStatusMessage("Session settings saved.");
  };

  const clearToken = () => {
    setToken("");
    setDraftToken("");
    writeSession(STORAGE_TOKEN, "");
    setStatusMessage("Ops token cleared from session.");
  };

  return (
    <Layout
      activePanel={activePanel}
      setActivePanel={setActivePanel}
      contextReady={contextReady}
      hasToken={Boolean(context.token)}
    >
      <PanelErrorBoundary>
        {activePanel === "runtime" && <RuntimePanel context={context} />}
        {activePanel === "chat" && <ChatPanel context={context} />}
        {activePanel === "tasks" && <TasksPanel context={context} />}
        {activePanel === "approvals" && <ApprovalsPanel context={context} />}
        {activePanel === "cron" && <CronPanel context={context} />}
        {activePanel === "blackbox" && <BlackboxPanel context={context} />}
        {activePanel === "nodes" && <NodesPanel context={context} />}
        <SettingsPanel
          draftChatId={draftChatId}
          draftUsername={draftUsername}
          draftToken={draftToken}
          setDraftChatId={setDraftChatId}
          setDraftUsername={setDraftUsername}
          setDraftToken={setDraftToken}
          saveSettings={saveSettings}
          clearToken={clearToken}
          statusMessage={statusMessage}
        />
      </PanelErrorBoundary>
    </Layout>
  );
}

export default App;
