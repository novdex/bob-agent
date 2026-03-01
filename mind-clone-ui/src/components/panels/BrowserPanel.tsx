import { useState } from "react";
import { Globe, Search, MousePointer, Type, Code, Camera, Play, Clock, ChevronRight } from "lucide-react";
import { apiPost } from "../../api/client";
import { showToast } from "../../hooks/useToast";
import type { AppContext } from "../../types";

type Props = { context: AppContext };

type ActionType = "browse" | "screenshot" | "click" | "type" | "extract" | "script";

type HistoryEntry = {
  action: ActionType;
  url: string;
  ts: number;
  ok: boolean;
};

type BrowserResult = {
  ok: boolean;
  url?: string;
  title?: string;
  text?: string;
  path?: string;
  clicked?: string;
  page_text?: string;
  typed?: string;
  selector?: string;
  count?: number;
  elements?: string[];
  result?: string;
  error?: string;
};

const glassCard: React.CSSProperties = {
  background: "linear-gradient(135deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%)",
  backdropFilter: "blur(16px)",
  WebkitBackdropFilter: "blur(16px)",
  border: "1px solid rgba(255,255,255,0.12)",
  borderRadius: "var(--radius-md)",
  padding: "16px 18px",
  transition: "all 0.3s cubic-bezier(0.4,0,0.2,1)",
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "10px 14px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid rgba(255,255,255,0.1)",
  background: "rgba(0,0,0,0.3)",
  color: "var(--text)",
  fontSize: "0.85rem",
  fontFamily: "var(--font-ui)",
  outline: "none",
};

const actions: { key: ActionType; label: string; icon: typeof Globe }[] = [
  { key: "browse", label: "Browse", icon: Search },
  { key: "screenshot", label: "Screenshot", icon: Camera },
  { key: "click", label: "Click", icon: MousePointer },
  { key: "type", label: "Type", icon: Type },
  { key: "extract", label: "Extract", icon: Code },
  { key: "script", label: "Script", icon: Code },
];

export function BrowserPanel({ context: _context }: Props) {
  const [url, setUrl] = useState("");
  const [action, setAction] = useState<ActionType>("browse");
  const [selector, setSelector] = useState("");
  const [text, setText] = useState("");
  const [script, setScript] = useState("");
  const [fullPage, setFullPage] = useState(false);
  const [submitForm, setSubmitForm] = useState(false);
  const [attribute, setAttribute] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BrowserResult | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);

  async function handleExecute() {
    if (!url.trim()) {
      showToast("URL is required", "error");
      return;
    }
    setLoading(true);
    setResult(null);

    try {
      let endpoint = "";
      let body: Record<string, unknown> = { url: url.trim() };

      switch (action) {
        case "browse":
          endpoint = "/api/browser/open";
          break;
        case "screenshot":
          endpoint = "/api/browser/screenshot";
          body.full_page = fullPage;
          break;
        case "click":
          endpoint = "/api/browser/click";
          body.selector = selector;
          break;
        case "type":
          endpoint = "/api/browser/type";
          body.selector = selector;
          body.text = text;
          body.submit = submitForm;
          break;
        case "extract":
          endpoint = "/api/browser/extract";
          body.selector = selector;
          if (attribute.trim()) body.attribute = attribute.trim();
          break;
        case "script":
          endpoint = "/api/browser/script";
          body.script = script;
          break;
      }

      const res = await apiPost<BrowserResult>(endpoint, body);
      setResult(res);
      setHistory((h) => [{ action, url: url.trim(), ts: Date.now(), ok: res.ok }, ...h].slice(0, 15));

      if (!res.ok) {
        showToast(res.error || "Browser action failed", "error");
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setResult({ ok: false, error: msg });
      showToast(msg, "error");
    } finally {
      setLoading(false);
    }
  }

  function renderForm() {
    switch (action) {
      case "browse":
        return null;
      case "screenshot":
        return (
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.82rem", color: "var(--text-secondary)" }}>
            <input
              type="checkbox"
              checked={fullPage}
              onChange={(e) => setFullPage(e.target.checked)}
              style={{ accentColor: "var(--accent)" }}
            />
            Full page
          </label>
        );
      case "click":
        return (
          <input
            style={inputStyle}
            placeholder="CSS selector (e.g. button.submit)"
            value={selector}
            onChange={(e) => setSelector(e.target.value)}
          />
        );
      case "type":
        return (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <input style={inputStyle} placeholder="CSS selector (e.g. input#email)" value={selector} onChange={(e) => setSelector(e.target.value)} />
            <input style={inputStyle} placeholder="Text to type" value={text} onChange={(e) => setText(e.target.value)} />
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.82rem", color: "var(--text-secondary)" }}>
              <input type="checkbox" checked={submitForm} onChange={(e) => setSubmitForm(e.target.checked)} style={{ accentColor: "var(--accent)" }} />
              Press Enter after typing
            </label>
          </div>
        );
      case "extract":
        return (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <input style={inputStyle} placeholder="CSS selector (e.g. h1, a.link)" value={selector} onChange={(e) => setSelector(e.target.value)} />
            <input style={inputStyle} placeholder="Attribute (optional, e.g. href, src)" value={attribute} onChange={(e) => setAttribute(e.target.value)} />
          </div>
        );
      case "script":
        return (
          <textarea
            style={{ ...inputStyle, minHeight: 100, resize: "vertical", fontFamily: "var(--font-mono)" }}
            placeholder="document.title"
            value={script}
            onChange={(e) => setScript(e.target.value)}
          />
        );
    }
  }

  function renderResult() {
    if (!result) return null;

    if (!result.ok) {
      return (
        <div style={{ ...glassCard, borderColor: "rgba(255,69,58,0.3)" }}>
          <div style={{ color: "var(--danger)", fontSize: "0.85rem", fontWeight: 600, marginBottom: 6 }}>Error</div>
          <pre style={{ margin: 0, fontSize: "0.8rem", color: "var(--text-secondary)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {result.error}
          </pre>
        </div>
      );
    }

    return (
      <div style={glassCard}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
          <div style={{ width: 6, height: 6, borderRadius: 3, background: "var(--ok)" }} />
          <span style={{ fontSize: "0.82rem", fontWeight: 600, color: "var(--ok)" }}>Success</span>
          {result.title && <span style={{ fontSize: "0.78rem", color: "var(--text-dim)", marginLeft: 8 }}>{result.title}</span>}
          {result.count !== undefined && <span style={{ fontSize: "0.78rem", color: "var(--text-dim)", marginLeft: 8 }}>{result.count} elements</span>}
        </div>

        {/* Page text */}
        {(result.text || result.page_text) && (
          <pre style={{
            margin: 0, padding: 12, borderRadius: "var(--radius-sm)",
            background: "rgba(0,0,0,0.4)", border: "1px solid rgba(255,255,255,0.06)",
            fontSize: "0.78rem", color: "var(--text-secondary)",
            fontFamily: "var(--font-mono)", maxHeight: 400, overflow: "auto",
            whiteSpace: "pre-wrap", wordBreak: "break-word",
          }}>
            {result.text || result.page_text}
          </pre>
        )}

        {/* Screenshot path */}
        {result.path && (
          <div style={{ fontSize: "0.82rem", color: "var(--accent)" }}>
            Screenshot saved: <code style={{ background: "rgba(0,129,242,0.1)", padding: "2px 6px", borderRadius: 4 }}>{result.path}</code>
          </div>
        )}

        {/* Extracted elements */}
        {result.elements && result.elements.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 300, overflow: "auto" }}>
            {result.elements.map((el, i) => (
              <div key={i} style={{
                padding: "6px 10px", borderRadius: "var(--radius-sm)",
                background: "rgba(0,0,0,0.3)", fontSize: "0.78rem",
                fontFamily: "var(--font-mono)", color: "var(--text-secondary)",
              }}>
                {el}
              </div>
            ))}
          </div>
        )}

        {/* Script result */}
        {result.result !== undefined && (
          <pre style={{
            margin: 0, padding: 12, borderRadius: "var(--radius-sm)",
            background: "rgba(0,0,0,0.4)", border: "1px solid rgba(255,255,255,0.06)",
            fontSize: "0.8rem", color: "var(--accent)",
            fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap",
          }}>
            {result.result}
          </pre>
        )}
      </div>
    );
  }

  return (
    <section className="panel">
      {/* Header */}
      <header className="panel-head">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 38, height: 38, borderRadius: 10,
            background: "linear-gradient(135deg, rgba(0,129,242,0.2) 0%, rgba(124,92,252,0.2) 100%)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <Globe size={20} style={{ color: "var(--accent)" }} />
          </div>
          <div>
            <h2 style={{ margin: 0 }}>Web Browser</h2>
            <p style={{ margin: 0, fontSize: "0.82rem", color: "var(--text-dim)" }}>Autonomous web automation</p>
          </div>
        </div>
        {history.length > 0 && (
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            padding: "4px 12px", borderRadius: 999,
            fontSize: "0.75rem", fontWeight: 500,
            color: "var(--accent)",
            background: "rgba(0,129,242,0.08)",
            border: "1px solid rgba(0,129,242,0.2)",
          }}>
            <Clock size={10} />
            {history.length} actions
          </div>
        )}
      </header>

      <div style={{ display: "flex", flexDirection: "column", gap: 14, flex: 1, overflow: "auto", padding: "0 2px" }}>
        {/* URL Bar + Actions */}
        <div style={glassCard}>
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <input
              style={{ ...inputStyle, flex: 1 }}
              placeholder="https://example.com"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !loading) handleExecute(); }}
            />
            <button
              onClick={handleExecute}
              disabled={loading}
              style={{
                padding: "10px 20px", borderRadius: "var(--radius-sm)",
                background: loading ? "rgba(255,255,255,0.05)" : "linear-gradient(135deg, #0081F2, #7c5cfc)",
                color: "#fff", border: "none", cursor: loading ? "wait" : "pointer",
                fontSize: "0.85rem", fontWeight: 600, display: "flex", alignItems: "center", gap: 6,
                opacity: loading ? 0.6 : 1,
              }}
            >
              <Play size={14} />
              {loading ? "Running..." : "Go"}
            </button>
          </div>

          {/* Action pills */}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {actions.map((a) => {
              const Icon = a.icon;
              const active = action === a.key;
              return (
                <button
                  key={a.key}
                  onClick={() => setAction(a.key)}
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 5,
                    padding: "5px 12px", borderRadius: 999,
                    fontSize: "0.75rem", fontWeight: 600,
                    background: active ? "rgba(0,129,242,0.15)" : "rgba(255,255,255,0.04)",
                    color: active ? "var(--accent)" : "var(--text-secondary)",
                    border: `1px solid ${active ? "rgba(0,129,242,0.3)" : "rgba(255,255,255,0.08)"}`,
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                  }}
                >
                  <Icon size={12} />
                  {a.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Action-specific form */}
        {action !== "browse" && (
          <div style={glassCard}>
            <div style={{ fontSize: "0.78rem", color: "var(--text-dim)", marginBottom: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              {action} parameters
            </div>
            {renderForm()}
          </div>
        )}

        {/* Result */}
        {renderResult()}

        {/* History */}
        {history.length > 0 && (
          <div style={glassCard}>
            <div style={{ fontSize: "0.78rem", color: "var(--text-dim)", marginBottom: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Recent Actions
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {history.map((h, i) => (
                <div
                  key={i}
                  onClick={() => setUrl(h.url)}
                  style={{
                    display: "flex", alignItems: "center", gap: 8,
                    padding: "8px 10px", borderRadius: "var(--radius-sm)",
                    background: "rgba(0,0,0,0.2)", cursor: "pointer",
                    transition: "background 0.2s",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(0,0,0,0.4)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(0,0,0,0.2)"; }}
                >
                  <div style={{
                    width: 6, height: 6, borderRadius: 3,
                    background: h.ok ? "var(--ok)" : "var(--danger)",
                  }} />
                  <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--accent)", textTransform: "uppercase", minWidth: 65 }}>
                    {h.action}
                  </span>
                  <span style={{ fontSize: "0.78rem", color: "var(--text-secondary)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {h.url}
                  </span>
                  <span style={{ fontSize: "0.7rem", color: "var(--text-dim)" }}>
                    {new Date(h.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </span>
                  <ChevronRight size={12} style={{ color: "var(--text-dim)" }} />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Empty state */}
        {!result && history.length === 0 && (
          <div style={{ ...glassCard, textAlign: "center", padding: "40px 24px" }}>
            <div style={{
              width: 64, height: 64, borderRadius: 16, margin: "0 auto 16px",
              background: "linear-gradient(135deg, rgba(0,129,242,0.12) 0%, rgba(124,92,252,0.12) 100%)",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <Globe size={32} strokeWidth={1.2} style={{ color: "var(--accent)" }} />
            </div>
            <h3 style={{ margin: "0 0 6px", fontWeight: 600 }}>Web Automation Ready</h3>
            <p style={{ color: "var(--text-dim)", fontSize: "0.85rem", margin: "0 0 16px" }}>
              Browse pages, take screenshots, click elements, fill forms, extract data, or run JavaScript.
            </p>
            <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
              {["Browse", "Screenshot", "Click", "Extract", "Script"].map((tag) => (
                <span key={tag} style={{
                  display: "inline-flex", alignItems: "center", gap: 4,
                  padding: "3px 10px", borderRadius: 20,
                  fontSize: "0.72rem", fontWeight: 600,
                  background: "rgba(0,129,242,0.1)", color: "var(--accent)",
                }}>
                  {tag}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
