import { useState, useEffect, useCallback, useMemo } from "react";
import { BarChart3, DollarSign, Cpu, Hash } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, PieChart, Pie } from "recharts";
import { apiGet } from "../../api/client";
import { usePolling } from "../../hooks/usePolling";
import { formatApiError, requireOpsToken } from "../../utils/errors";
import { formatCost, formatTokenCount } from "../../utils/formatters";
import { StatCard, LoadingSkeleton, EmptyState, ErrorAlert } from "../ui";
import type { AppContext, UsageSummary } from "../../types";

type Props = { context: AppContext };

const CHART_COLORS = ["#74d0ff", "#b48eff", "#ff8a65", "#4ec98f", "#d8b55f", "#df6464"];

export function UsagePanel({ context }: Props) {
  const opsError = requireOpsToken(context);
  const [data, setData] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchUsage = useCallback(async () => {
    if (opsError) return;
    try {
      const res = await apiGet<UsageSummary>(`/ops/usage/summary?owner_id=${context.chatId}`, context.token);
      setData(res);
    } catch (e) { setError(formatApiError(e)); }
    finally { setLoading(false); }
  }, [context.chatId, context.token, opsError]);

  useEffect(() => { fetchUsage(); }, [fetchUsage]);
  usePolling(fetchUsage, 30000);

  const barData = useMemo(() => {
    if (!data?.by_model) return [];
    return Object.entries(data.by_model).map(([model, v]) => ({ model, cost: v.cost_usd, events: v.events }));
  }, [data]);

  const pieData = useMemo(() => {
    if (!data?.by_model) return [];
    return Object.entries(data.by_model).map(([model, v]) => ({ name: model, value: v.prompt_tokens + v.completion_tokens }));
  }, [data]);

  if (opsError) {
    return (
      <section className="panel">
        <div className="panel-head"><h2><BarChart3 size={18} /> Usage &amp; Cost</h2></div>
        <EmptyState title="Ops token required" description={opsError} />
      </section>
    );
  }

  return (
    <section className="panel">
      <div className="panel-head"><h2><BarChart3 size={18} /> Usage &amp; Cost</h2><p className="muted">LLM spending &amp; token breakdown</p></div>

      {error && <ErrorAlert message={error} onRetry={fetchUsage} />}

      {loading ? <LoadingSkeleton variant="card" /> : data ? (
        <>
          <div className="stat-grid">
            <StatCard icon={DollarSign} label="Total Cost" value={formatCost(data.total_cost_usd)} color="var(--accent-3)" />
            <StatCard icon={Hash} label="Prompt Tokens" value={formatTokenCount(data.total_prompt_tokens)} />
            <StatCard icon={Hash} label="Completion Tokens" value={formatTokenCount(data.total_completion_tokens)} />
            <StatCard icon={Cpu} label="API Calls" value={String(data.rows)} color="var(--accent-2)" />
          </div>

          {/* Cost by Model bar chart */}
          {barData.length > 0 && (
            <div className="subpanel" style={{ marginTop: 12 }}>
              <h3>Cost by Model</h3>
              <div style={{ width: "100%", height: 200, marginTop: 8 }}>
                <ResponsiveContainer>
                  <BarChart data={barData} layout="vertical" margin={{ left: 10, right: 20 }}>
                    <XAxis type="number" tickFormatter={(v: number) => `$${v.toFixed(3)}`} stroke="var(--text-dim)" fontSize={11} />
                    <YAxis type="category" dataKey="model" stroke="var(--text-dim)" fontSize={11} width={100} />
                    <Tooltip
                      contentStyle={{ background: "var(--bg-1)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12 }}
                      formatter={(v: number) => [`$${v.toFixed(4)}`, "Cost"]}
                    />
                    <Bar dataKey="cost" radius={[0, 4, 4, 0]}>
                      {barData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Token distribution pie chart */}
          {pieData.length > 0 && (
            <div className="subpanel" style={{ marginTop: 12 }}>
              <h3>Token Distribution</h3>
              <div style={{ width: "100%", height: 200, marginTop: 8 }}>
                <ResponsiveContainer>
                  <PieChart>
                    <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={70} label={({ name }) => name} fontSize={11}>
                      {pieData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                    </Pie>
                    <Tooltip contentStyle={{ background: "var(--bg-1)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12 }} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </>
      ) : <EmptyState title="No usage data" description="Usage data will appear after API calls" />}
    </section>
  );
}
