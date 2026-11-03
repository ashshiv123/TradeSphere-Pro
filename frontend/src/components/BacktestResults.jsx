import React, { useEffect, useState } from "react";
import { BarChart3, LineChart, FileText, CheckCircle2 } from "lucide-react";
import { fetchJson } from "../api";

export default function BacktestResults() {
  const [runs, setRuns] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    async function loadBacktests() {
      try {
        setLoading(true);
        const list = await fetchJson("/backtests");
        setRuns(list);
        if (list && list.length > 0) {
          const detail = await fetchJson(`/backtests/${list[0].id}`);
          setSelectedRun(detail);
        }
      } catch (err) {
        console.error("Failed to load backtests", err);
      } finally {
        setLoading(false);
      }
    }
    loadBacktests();
  }, []);

  const handleSelectRun = async (runId) => {
    try {
      setLoading(true);
      const detail = await fetchJson(`/backtests/${runId}`);
      setSelectedRun(detail);
    } catch (err) {
      alert("Error loading run detail: " + err.message);
    } finally {
      setLoading(false);
    }
  };

  if (runs.length === 0) {
    return (
      <div className="p-8 text-center border border-border rounded-xl bg-surface text-slate-400">
        No completed backtest runs available. Run `python -m app.backtest.run` to compute historical simulations.
      </div>
    );
  }

  const runInfo = selectedRun?.run;
  const metrics = runInfo?.metrics || {};
  const trades = selectedRun?.trades || [];

  return (
    <div className="space-y-6">
      {/* Runs Selector */}
      <div className="flex items-center gap-3 overflow-x-auto pb-2">
        {runs.map((r) => (
          <button
            key={r.id}
            onClick={() => handleSelectRun(r.id)}
            className={`px-4 py-2 rounded-xl text-xs font-medium border transition shrink-0 ${
              runInfo?.id === r.id
                ? "bg-blue-600/20 border-blue-500 text-blue-300 ring-1 ring-blue-500"
                : "bg-surface border-border text-slate-400 hover:border-slate-600"
            }`}
          >
            #{r.id} - {r.name} ({r.mode})
          </button>
        ))}
      </div>

      {/* Metrics Cards */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        <div className="p-4 rounded-xl border border-border bg-surface text-center">
          <div className="text-[10px] text-slate-400 uppercase">Total Return</div>
          <div className={`text-xl font-bold font-mono mt-1 ${
            (metrics.total_return_pct || 0) >= 0 ? "text-emerald-400" : "text-rose-400"
          }`}>
            {(metrics.total_return_pct || 0) > 0 ? `+${metrics.total_return_pct}%` : `${metrics.total_return_pct || 0}%`}
          </div>
        </div>

        <div className="p-4 rounded-xl border border-border bg-surface text-center">
          <div className="text-[10px] text-slate-400 uppercase">Win Rate</div>
          <div className="text-xl font-bold font-mono mt-1 text-slate-100">
            {metrics.win_rate || 0}%
          </div>
        </div>

        <div className="p-4 rounded-xl border border-border bg-surface text-center">
          <div className="text-[10px] text-slate-400 uppercase">Profit Factor</div>
          <div className="text-xl font-bold font-mono mt-1 text-blue-400">
            {metrics.profit_factor || 0}
          </div>
        </div>

        <div className="p-4 rounded-xl border border-border bg-surface text-center">
          <div className="text-[10px] text-slate-400 uppercase">Max Drawdown</div>
          <div className="text-xl font-bold font-mono mt-1 text-rose-400">
            {metrics.max_drawdown_pct || 0}%
          </div>
        </div>

        <div className="p-4 rounded-xl border border-border bg-surface text-center">
          <div className="text-[10px] text-slate-400 uppercase">Closed Trades</div>
          <div className="text-xl font-bold font-mono mt-1 text-slate-100">
            {metrics.total_trades || 0}
          </div>
        </div>

        <div className="p-4 rounded-xl border border-border bg-surface text-center">
          <div className="text-[10px] text-slate-400 uppercase">Expectancy</div>
          <div className="text-xl font-bold font-mono mt-1 text-slate-100">
            {metrics.expectancy_r || 0} R
          </div>
        </div>
      </div>

      {/* Trades Table */}
      <div className="border border-border rounded-xl bg-surface overflow-hidden">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold text-white">Backtest Simulation Trades Log</h3>
            <p className="text-xs text-slate-400">Pessimistic Stop-First Resolution | 0.05% Fees | 0.02% Slippage</p>
          </div>
          <span className="text-xs px-2.5 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
            {trades.length} Trades
          </span>
        </div>

        {trades.length > 0 ? (
          <div className="overflow-x-auto max-h-80 overflow-y-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#161c28] text-slate-400 font-semibold border-b border-border sticky top-0">
                <tr>
                  <th className="py-2.5 px-4">Symbol</th>
                  <th className="py-2.5 px-4">Side</th>
                  <th className="py-2.5 px-4">Entry</th>
                  <th className="py-2.5 px-4">Exit</th>
                  <th className="py-2.5 px-4">Exit Reason</th>
                  <th className="py-2.5 px-4">PnL</th>
                  <th className="py-2.5 px-4">Fees</th>
                  <th className="py-2.5 px-4">R-Multiple</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {trades.map((t, idx) => (
                  <tr key={idx} className="hover:bg-slate-800/40">
                    <td className="py-2.5 px-4 font-bold text-white">{t.symbol}</td>
                    <td className="py-2.5 px-4">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        t.side === "LONG" ? "bg-emerald-500/20 text-emerald-400" : "bg-rose-500/20 text-rose-400"
                      }`}>
                        {t.side}
                      </span>
                    </td>
                    <td className="py-2.5 px-4 font-mono">${Number(t.entry_price).toLocaleString()}</td>
                    <td className="py-2.5 px-4 font-mono">${Number(t.exit_price).toLocaleString()}</td>
                    <td className="py-2.5 px-4 font-mono uppercase text-slate-400 text-[11px]">{t.exit_reason}</td>
                    <td className={`py-2.5 px-4 font-mono font-bold ${
                      Number(t.pnl) >= 0 ? "text-emerald-400" : "text-rose-400"
                    }`}>
                      {Number(t.pnl) >= 0 ? `+$${Number(t.pnl).toFixed(2)}` : `-$${Math.abs(Number(t.pnl)).toFixed(2)}`}
                    </td>
                    <td className="py-2.5 px-4 font-mono text-slate-400">${Number(t.fees).toFixed(2)}</td>
                    <td className="py-2.5 px-4 font-mono text-slate-200">{t.r_multiple} R</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-8 text-center text-xs text-slate-400">
            No trades executed in this run period.
          </div>
        )}
      </div>
    </div>
  );
}
