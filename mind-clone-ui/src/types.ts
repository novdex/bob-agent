export type RuntimePayload = Record<string, unknown>;

export type UiTaskSummary = {
  id: number;
  title: string;
  status: string;
  created_at: string | null;
  progress_done: number;
  progress_total: number;
  current_step?: string | null;
};

export type UiTaskDetail = {
  ok: boolean;
  task?: UiTaskSummary;
  detail_text?: string;
  plan?: Array<Record<string, unknown>>;
  error?: string;
};

export type UiApproval = {
  token: string;
  tool_name: string;
  source_type: string;
  source_ref?: string | null;
  step_id?: string | null;
  created_at?: string | null;
  expires_at?: string | null;
};

export type CronJob = {
  job_id: number;
  name: string;
  message: string;
  lane: string;
  interval_seconds: number;
  enabled: boolean;
  run_count: number;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_error?: string | null;
};

export type PanelKey =
  | "dashboard"
  | "runtime"
  | "chat"
  | "tasks"
  | "approvals"
  | "cron"
  | "blackbox"
  | "nodes"
  | "goals"
  | "team"
  | "usage"
  | "workflows";

export type PanelDef = {
  key: PanelKey;
  label: string;
};

export type AppContext = {
  chatId: string;
  username: string;
  token: string;
};

/* ── New types for additional panels ── */

export type Goal = {
  id: number;
  title: string;
  description: string;
  status: string;
  progress_pct: number;
  priority: string;
  task_ids: number[];
  milestones: Array<Record<string, unknown>>;
  created_at: string;
};

export type TeamAgent = {
  agent_key: string;
  display_name: string;
  status: string;
  agent_owner_id: number;
  username: string;
  last_seen_at: string | null;
};

export type UsageSummary = {
  ok: boolean;
  rows: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_cost_usd: number;
  by_model: Record<string, {
    events: number;
    prompt_tokens: number;
    completion_tokens: number;
    cost_usd: number;
  }>;
};

export type WorkflowProgram = {
  name: string;
  created_at: string | null;
  updated_at: string | null;
  preview: string;
};

export type AuditEvent = {
  id: number;
  actor_role: string;
  actor_ref: string;
  action: string;
  target: string;
  status: string;
  created_at: string | null;
  detail: Record<string, unknown>;
};

export type ChatMessage = {
  role: string;
  text: string;
  ts: number;
};
