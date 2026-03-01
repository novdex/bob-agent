export function TypingIndicator() {
  return (
    <div className="typing-indicator">
      <span />
      <span />
      <span />
      <span style={{ marginLeft: 6, fontSize: "0.78rem", color: "var(--text-dim)", animation: "none" }}>
        Bob is thinking...
      </span>
    </div>
  );
}
