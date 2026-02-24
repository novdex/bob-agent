import { useState } from "react";
import { apiPost } from "../../api/client";
import type { AppContext } from "../../types";
import { formatApiError, requireUserContext } from "../../utils/errors";

type ChatItem = { role: "user" | "assistant" | "system"; text: string; ts: number };

type ChatPanelProps = {
  context: AppContext;
};

export function ChatPanel({ context }: ChatPanelProps) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const onSend = async () => {
    const ctxError = requireUserContext(context);
    if (ctxError) {
      setError(ctxError);
      return;
    }
    const text = input.trim();
    if (!text) {
      return;
    }
    setBusy(true);
    setError("");
    setMessages((prev) => [...prev, { role: "user", text, ts: Date.now() }]);
    try {
      const payload = await apiPost<{ ok: boolean; response?: string; error?: string }>(
        "/chat",
        {
          chat_id: context.chatId,
          username: context.username,
          message: text,
        }
      );
      if (!payload.ok) {
        throw new Error(payload.error || "Chat call failed.");
      }
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: String(payload.response || ""), ts: Date.now() },
      ]);
      setInput("");
    } catch (err) {
      const message = formatApiError(err);
      setError(message);
      setMessages((prev) => [...prev, { role: "system", text: `Error: ${message}`, ts: Date.now() }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <header className="panel-head">
        <h2>Chat Console</h2>
        <p>Direct request/response mode via `/chat`.</p>
      </header>
      {error && <p className="error">{error}</p>}
      <div className="chat-log">
        {messages.length === 0 && <p className="muted">No chat yet. Send a message to start.</p>}
        {messages.map((item) => (
          <article key={`${item.ts}-${item.role}`} className={`chat-item ${item.role}`}>
            <header>
              <span>{item.role}</span>
              <time>{new Date(item.ts).toLocaleTimeString()}</time>
            </header>
            <p>{item.text}</p>
          </article>
        ))}
      </div>
      <div className="chat-compose">
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Ask Bob..."
          rows={4}
        />
        <button onClick={() => void onSend()} disabled={busy}>
          {busy ? "Sending..." : "Send"}
        </button>
      </div>
    </section>
  );
}
