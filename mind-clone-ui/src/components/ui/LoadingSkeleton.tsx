type Props = {
  lines?: number;
  variant?: "text" | "card" | "chart";
};

export function LoadingSkeleton({ lines = 3, variant = "text" }: Props) {
  if (variant === "card") {
    return (
      <div className="stat-grid">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="skeleton skeleton-card" />
        ))}
      </div>
    );
  }

  if (variant === "chart") {
    return <div className="skeleton skeleton-chart" />;
  }

  return (
    <div style={{ display: "grid", gap: 8 }}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="skeleton skeleton-line"
          style={{ width: i === lines - 1 ? "60%" : "100%" }}
        />
      ))}
    </div>
  );
}
