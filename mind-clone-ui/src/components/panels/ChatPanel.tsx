import { useState, useRef, useEffect } from "react";
import { MessageSquare } from "lucide-react";
import { apiPost } from "../../api/client";
import { formatApiError, requireUserContext } from "../../utils/errors";
import { showToast } from "../../hooks/useToast";
import { ChatMessageView } from "./chat/ChatMessage";
import { ChatInput } from "./chat/ChatInput";
import { TypingIndicator } from "./chat/TypingIndicator";
import { EmptyState } from "../ui";
import type { AppContext, ChatMessage } from "../../types";

type Props = { context: AppContext };
type ChatResponse = { ok: boolean; response?: string; error?: string };

export function ChatPanel({ context }: Props) {
  const ctxError = requireUserContext(context);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, busy]);

  if (ctxError) {
    return (
      <section className="panel">
        <div className="panel-head"><h2><MessageSquare size={18} /> Chat</h2></div>
        <EmptyState title="User context required" description={ctxError} />
      </section>
    );
  }

  async function handleSend() {
    const text = draft.trim();
    if (!text || busy) return;

    setMessages((m) => [...m, { role: "user", text, ts: Date.now() }]);
    setDraft("");
    setBusy(true);

    try {
      const res = await apiPost<ChatResponse>("/chat", {
        chat_id: Number(context.chatId),
        message: text,
        username: context.username,
      });
      if (!res.ok) throw new Error(res.error || "Chat call failed.");
      setMessages((m) => [...m, {
        role: "assistant",
        text: res.response ?? "No response",
        ts: Date.now(),
      }]);
    } catch (err) {
      const errMsg = formatApiError(err);
      showToast(errMsg, "error");
      setMessages((m) => [...m, { role: "system", text: errMsg, ts: Date.now() }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <h2><MessageSquare size={18} /> Chat with Bob</h2>
        <p className="muted">Markdown rendering &middot; Enter to send</p>
      </div>

      <div className="chat-log" ref={scrollRef}>
        {messages.length === 0 && !busy && (
          <EmptyState icon={MessageSquare} title="Start a conversation" description="Send a message to Bob below" />
        )}
        {messages.map((m, i) => (
          <ChatMessageView key={i} role={m.role} text={m.text} ts={m.ts} />
        ))}
        {busy && <TypingIndicator />}
      </div>

      <ChatInput value={draft} onChange={setDraft} onSend={handleSend} disabled={busy} />
    </section>
  );
}
