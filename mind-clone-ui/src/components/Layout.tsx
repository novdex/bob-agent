import type { ReactNode } from "react";
import {
  LayoutDashboard, MessageSquare, ListChecks, Target, Users, Shield,
  Workflow, BarChart3, Clock, Box, Server, Activity
} from "lucide-react";
import type { PanelKey } from "../types";
import { PANELS } from "../constants";

type LayoutProps = {
  activePanel: PanelKey;
  setActivePanel: (key: PanelKey) => void;
  contextReady: boolean;
  hasToken: boolean;
  badgeCounts?: { approvals: number; alerts: number };
  children: ReactNode;
};

const iconMap: Record<string, typeof Activity> = {
  dashboard: LayoutDashboard, chat: MessageSquare, tasks: ListChecks,
  goals: Target, team: Users, approvals: Shield, workflows: Workflow,
  usage: BarChart3, cron: Clock, blackbox: Box, nodes: Server, runtime: Activity,
};

export function Layout({ activePanel, setActivePanel, contextReady, hasToken, badgeCounts, children }: LayoutProps) {
  return (
    <div className="app-shell">
      <div className="ambient" />
      <aside className="side-nav">
        <header>
          <h1>Bob Command Center</h1>
          <p className="tagline">AGI Ops Console</p>
        </header>
        <nav>
          {PANELS.map((panel) => {
            const Icon = iconMap[panel.key] ?? Activity;
            const badge =
              panel.key === "approvals" && badgeCounts?.approvals
                ? badgeCounts.approvals
                : panel.key === "runtime" && badgeCounts?.alerts
                  ? badgeCounts.alerts
                  : 0;
            return (
              <button
                key={panel.key}
                className={activePanel === panel.key ? "active" : ""}
                onClick={() => setActivePanel(panel.key)}
              >
                <Icon size={15} />
                {panel.label}
                {badge > 0 && <span className="nav-badge">{badge}</span>}
              </button>
            );
          })}
        </nav>
        <footer>
          <span className={contextReady ? "badge ok" : "badge warn"}>
            {contextReady ? "context ready" : "set chat_id + username"}
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
