import type { RuntimePayload } from "../types";

export function formatTimestamp(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) {
    return "-";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

export function runtimeStat(runtime: RuntimePayload | null, key: string): string {
  if (!runtime || !(key in runtime)) {
    return "-";
  }
  const raw = runtime[key];
  if (raw === null || raw === undefined) {
    return "-";
  }
  if (typeof raw === "boolean") {
    return raw ? "yes" : "no";
  }
  if (typeof raw === "number") {
    return Number.isFinite(raw) ? String(raw) : "-";
  }
  if (typeof raw === "string") {
    return raw || "-";
  }
  return JSON.stringify(raw);
}
