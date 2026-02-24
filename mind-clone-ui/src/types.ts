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
  | "runtime"
  | "chat"
  | "tasks"
  | "approvals"
  | "cron"
  | "blackbox"
  | "nodes";

export type PanelDef = {
  key: PanelKey;
  label: string;
};

export type AppContext = {
  chatId: string;
  username: string;
  token: string;
};
