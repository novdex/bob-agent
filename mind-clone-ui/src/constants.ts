import type { PanelDef } from "./types";

export const PANELS: PanelDef[] = [
  { key: "dashboard", label: "Dashboard" },
  { key: "chat", label: "Chat" },
  { key: "tasks", label: "Tasks" },
  { key: "goals", label: "Goals" },
  { key: "team", label: "Team Agents" },
  { key: "approvals", label: "Approvals" },
  { key: "workflows", label: "Workflows" },
  { key: "usage", label: "Usage & Cost" },
  { key: "cron", label: "Cron" },
  { key: "blackbox", label: "Blackbox" },
  { key: "nodes", label: "Nodes" },
  { key: "runtime", label: "Runtime" },
];

export const STORAGE_CHAT_ID = "bob_ui_chat_id";
export const STORAGE_USERNAME = "bob_ui_username";
export const STORAGE_TOKEN = "bob_ui_ops_token";
