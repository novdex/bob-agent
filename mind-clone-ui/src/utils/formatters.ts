import { formatDistanceToNow } from "date-fns";
import type { RuntimePayload } from "../types";

export function formatTimestamp(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

export function runtimeStat(runtime: RuntimePayload | null, key: string): string {
  if (!runtime || !(key in runtime)) return "-";
  const raw = runtime[key];
  if (raw === null || raw === undefined) return "-";
  if (typeof raw === "boolean") return raw ? "yes" : "no";
  if (typeof raw === "number") return Number.isFinite(raw) ? String(raw) : "-";
  if (typeof raw === "string") return raw || "-";
  return JSON.stringify(raw);
}

export function formatRelativeTime(isoString: string | null | undefined): string {
  if (!isoString) return "-";
  try {
    return formatDistanceToNow(new Date(isoString), { addSuffix: true });
  } catch {
    return isoString;
  }
}

export function formatCost(usd: number): string {
  if (!Number.isFinite(usd)) return "$0.00";
  return usd < 0.01 && usd > 0
    ? `$${usd.toFixed(4)}`
    : `$${usd.toFixed(2)}`;
}

export function formatTokenCount(count: number): string {
  if (!Number.isFinite(count)) return "0";
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}K`;
  return String(count);
}

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "-";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

export function clampString(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen - 1) + "\u2026";
}
