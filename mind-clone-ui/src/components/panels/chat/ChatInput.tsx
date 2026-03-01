import { useRef, useCallback } from "react";
import { Send } from "lucide-react";

type Props = {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  disabled: boolean;
};

export function ChatInput({ value, onChange, onSend, disabled }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  const autoResize = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, []);

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!disabled && value.trim()) onSend();
    }
  };

  return (
    <div className="chat-input-wrap">
      <textarea
        ref={ref}
        rows={1}
        value={value}
        onChange={(e) => { onChange(e.target.value); autoResize(); }}
        onKeyDown={handleKey}
        placeholder="Message Bob... (Enter to send, Shift+Enter for newline)"
        disabled={disabled}
      />
      <button onClick={onSend} disabled={disabled || !value.trim()}>
        <Send size={16} />
      </button>
    </div>
  );
}
