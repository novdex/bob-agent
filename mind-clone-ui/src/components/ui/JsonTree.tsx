import { useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";

type Props = {
  data: unknown;
  maxDepth?: number;
  collapsed?: boolean;
  label?: string;
  depth?: number;
};

export function JsonTree({ data, maxDepth = 4, collapsed = true, label, depth = 0 }: Props) {
  const [open, setOpen] = useState(!collapsed || depth === 0);

  if (data === null || data === undefined) return <span className="json-null">null</span>;
  if (typeof data === "boolean") return <span className="json-bool">{String(data)}</span>;
  if (typeof data === "number") return <span className="json-num">{data}</span>;
  if (typeof data === "string") {
    if (data.length > 120) {
      return <span className="json-str">"{data.slice(0, 120)}&hellip;"</span>;
    }
    return <span className="json-str">"{data}"</span>;
  }

  const isArray = Array.isArray(data);
  const entries = isArray ? data.map((v, i) => [String(i), v] as const) : Object.entries(data as Record<string, unknown>);
  const summary = isArray ? `Array(${entries.length})` : `{${entries.length} keys}`;

  if (depth >= maxDepth) return <span className="json-collapsed">{summary}</span>;

  return (
    <div className="json-node" style={{ paddingLeft: depth > 0 ? 14 : 0 }}>
      <button className="json-toggle" onClick={() => setOpen(!open)}>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        {label && <span className="json-key">{label}: </span>}
        {!open && <span className="json-collapsed">{summary}</span>}
      </button>
      {open && (
        <div className="json-children">
          {entries.map(([key, val]) => (
            <JsonTree key={key} data={val} maxDepth={maxDepth} collapsed={collapsed} label={key} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}
