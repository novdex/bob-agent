import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";

type Props = {
  title: string;
  description?: string;
  icon?: LucideIcon;
  action?: { label: string; onClick: () => void };
};

export function EmptyState({ title, description, icon: Icon = Inbox, action }: Props) {
  return (
    <div className="empty-state">
      <Icon size={36} strokeWidth={1.2} />
      <h3>{title}</h3>
      {description && <p className="muted">{description}</p>}
      {action && (
        <button onClick={action.onClick} style={{ marginTop: 8 }}>
          {action.label}
        </button>
      )}
    </div>
  );
}
