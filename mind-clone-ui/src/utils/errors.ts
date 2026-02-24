import { ApiRequestError, isRecord } from "../api/client";
import type { AppContext } from "../types";

export function formatApiError(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (typeof error.detail === "string") {
      return `HTTP ${error.status}: ${error.detail}`;
    }
    if (isRecord(error.detail)) {
      const detail = error.detail.detail || error.detail.error || JSON.stringify(error.detail);
      return `HTTP ${error.status}: ${String(detail)}`;
    }
    return `HTTP ${error.status}: ${error.message}`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown request error.";
}

export function hasUserContext(ctx: AppContext): boolean {
  return Boolean(ctx.chatId.trim() && ctx.username.trim());
}

export function requireUserContext(ctx: AppContext): string | null {
  if (!ctx.chatId.trim()) {
    return "Set chat_id in Settings first.";
  }
  if (!ctx.username.trim()) {
    return "Set username in Settings first.";
  }
  return null;
}

export function requireOpsToken(ctx: AppContext): string | null {
  if (!ctx.token.trim()) {
    return "Ops token required. Set it in Settings for protected panels.";
  }
  return null;
}
