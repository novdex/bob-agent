import { AlertTriangle, RefreshCw, X } from "lucide-react";

type Props = {
  message: string;
  onRetry?: () => void;
  onDismiss?: () => void;
};

export function ErrorAlert({ message, onRetry, onDismiss }: Props) {
  return (
    <div className="error" style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <AlertTriangle size={16} style={{ flexShrink: 0 }} />
      <span style={{ flex: 1 }}>{message}</span>
      {onRetry && (
        <button className="ghost" onClick={onRetry} style={{ padding: "4px 8px" }}>
          <RefreshCw size={14} />
        </button>
      )}
      {onDismiss && (
        <button className="ghost" onClick={onDismiss} style={{ padding: "4px 8px" }}>
          <X size={14} />
        </button>
      )}
    </div>
  );
}
