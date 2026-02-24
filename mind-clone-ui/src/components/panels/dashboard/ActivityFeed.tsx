import { Activity, Zap, Shield, AlertCircle } from "lucide-react";
import type { AuditEvent } from "../../../types";
import { formatRelativeTime } from "../../../utils/formatters";
import { LoadingSkeleton } from "../../ui";

type Props = { events: AuditEvent[]; loading: boolean };

const iconMap: Record<string, typeof Activity> = {
  tool_call: Zap,
  approval: Shield,
  error: AlertCircle,
};

export function ActivityFeed({ events, loading }: Props) {
  if (loading) return <LoadingSkeleton lines={5} />;
  if (events.length === 0) {
    return <p className="muted" style={{ textAlign: "center", padding: 12 }}>No recent activity</p>;
  }

  return (
    <div className="activity-feed">
      {events.map((e) => {
        const Icon = iconMap[e.action] ?? Activity;
        return (
          <div key={e.id} className="activity-item">
            <Icon size={14} style={{ color: "var(--text-dim)" }} />
            <span className="truncate">
              <strong>{e.action}</strong> {e.target && <span className="muted">{e.target}</span>}
            </span>
            <span className="activity-time">{formatRelativeTime(e.created_at)}</span>
          </div>
        );
      })}
    </div>
  );
}
