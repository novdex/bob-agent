type Props = {
  value: number;
  max: number;
  color?: string;
  showLabel?: boolean;
};

export function ProgressBar({ value, max, color = "var(--accent)", showLabel = true }: Props) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;

  return (
    <div className="progress-bar-wrap">
      <div className="progress-bar-track">
        <div
          className="progress-bar-fill"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      {showLabel && (
        <span className="progress-bar-label">
          {value}/{max}
        </span>
      )}
    </div>
  );
}
