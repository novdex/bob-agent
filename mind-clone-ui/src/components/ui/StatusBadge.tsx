import { Circle } from "lucide-react";

type Props = {
  label: string;
  status?: "ok" | "warn" | "danger" | "accent" | "muted";
  size?: "sm" | "md";
  pulse?: boolean;
};

const colorMap: Record<string, string> = {
  ok: "var(--ok)",
  warn: "var(--warn)",
  danger: "var(--danger)",
  accent: "var(--accent)",
  muted: "var(--text-dim)",
};

export function StatusBadge({ label, status = "muted", size = "sm", pulse }: Props) {
  const color = colorMap[status] ?? colorMap.muted;
  const fontSize = size === "sm" ? "0.75rem" : "0.85rem";
  const dotSize = size === "sm" ? 8 : 10;

  return (
    <span
      className="status-badge"
      style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize, color }}
    >
      <Circle
        size={dotSize}
        fill={color}
        stroke="none"
        className={pulse ? "pulse" : undefined}
      />
      {label}
    </span>
  );
}
