import type { ReactNode } from "react";
import type { PanelKey } from "../types";
import { PANELS } from "../constants";

type LayoutProps = {
  activePanel: PanelKey;
  setActivePanel: (key: PanelKey) => void;
  contextReady: boolean;
  hasToken: boolean;
  children: ReactNode;
};

export function Layout({ activePanel, setActivePanel, contextReady, hasToken, children }: LayoutProps) {
  return (
    <div className="app-shell">
      <div className="ambient" />
      <aside className="side-nav">
        <header>
          <h1>Bob Command Center</h1>
          <p>OpenClaw-style Ops Console</p>
        </header>
        <nav>
          {PANELS.map((panel) => (
            <button
              key={panel.key}
              className={activePanel === panel.key ? "active" : ""}
              onClick={() => setActivePanel(panel.key)}
            >
              {panel.label}
            </button>
          ))}
        </nav>
        <footer>
          <span className={contextReady ? "badge ok" : "badge warn"}>
            {contextReady ? "user context ready" : "set chat_id + username"}
          </span>
          <span className={hasToken ? "badge ok" : "badge warn"}>
            {hasToken ? "ops token loaded" : "ops token missing"}
          </span>
        </footer>
      </aside>
      <main className="main-content">{children}</main>
    </div>
  );
}
