import type { PanelDef } from "./types";

export const PANELS: PanelDef[] = [
  { key: "runtime", label: "Runtime" },
  { key: "chat", label: "Chat" },
  { key: "tasks", label: "Tasks" },
  { key: "approvals", label: "Approvals" },
  { key: "cron", label: "Cron" },
  { key: "blackbox", label: "Blackbox" },
  { key: "nodes", label: "Nodes/Plugins" },
];

export const STORAGE_CHAT_ID = "bob_ui_chat_id";
export const STORAGE_USERNAME = "bob_ui_username";
export const STORAGE_TOKEN = "bob_ui_ops_token";
