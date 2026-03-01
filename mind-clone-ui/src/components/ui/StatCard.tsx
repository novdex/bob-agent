import type { LucideIcon } from "lucide-react";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

type Props = {
  label: string;
  value: string | number;
  icon?: LucideIcon;
  trend?: "up" | "down" | "flat";
  color?: string;
};

const trendIcons = { up: TrendingUp, down: TrendingDown, flat: Minus };
const trendColors = { up: "var(--ok)", down: "var(--danger)", flat: "var(--text-dim)" };

export function StatCard({ label, value, icon: Icon, trend, color }: Props) {
  const TrendIcon = trend ? trendIcons[trend] : null;
  const trendColor = trend ? trendColors[trend] : undefined;

  return (
    <div className="stat-card" style={color ? { borderColor: `${color}44` } : undefined}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {Icon && <Icon size={14} style={{ color: color ?? "var(--accent)", opacity: 0.8 }} />}
          <span className="stat-card-label">{label}</span>
        </span>
        {TrendIcon && <TrendIcon size={13} style={{ color: trendColor }} />}
      </div>
      <strong style={color ? { color } : undefined}>{value}</strong>
    </div>
  );
}
