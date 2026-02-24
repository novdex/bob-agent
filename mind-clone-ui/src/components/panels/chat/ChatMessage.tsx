import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { User, Bot, AlertCircle } from "lucide-react";
import type { ChatMessage as ChatMsg } from "../../../types";

const roleConfig: Record<string, { icon: typeof User; label: string; className: string }> = {
  user:      { icon: User, label: "You", className: "chat-bubble--user" },
  assistant: { icon: Bot, label: "Bob", className: "chat-bubble--assistant" },
  system:    { icon: AlertCircle, label: "System", className: "chat-bubble--system" },
};

export function ChatMessageView({ role, text, ts }: ChatMsg) {
  const cfg = roleConfig[role] ?? roleConfig.system;
  const Icon = cfg.icon;
  const time = new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div className={`chat-bubble ${cfg.className}`}>
      <div className="chat-bubble-header">
        <Icon size={12} />
        <span>{cfg.label}</span>
        <span style={{ marginLeft: "auto" }}>{time}</span>
      </div>
      {role === "assistant" ? (
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      ) : (
        <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{text}</p>
      )}
    </div>
  );
}
