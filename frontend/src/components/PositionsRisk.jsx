import React from "react";
import { ShieldAlert, ShieldCheck, Activity, AlertOctagon } from "lucide-react";

export default function PositionsRisk({ positions, riskStatus }) {
  const portfolio = riskStatus?.portfolio || {};
  const killSwitch = riskStatus?.kill_switch || {};
  const recentEvents = riskStatus?.recent_events || [];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Positions Table */}
      <div className="lg:col-span-2 border border-border rounded-xl bg-surface overflow-hidden">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold text-white">Active Exchange Positions</h3>
            <p className="text-xs text-slate-400">Synced via 60-Second Testnet Reconciliation Engine</p>
          </div>
          <span className="text-xs px-2.5 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
            {positions?.length || 0} Open
          </span>
        </div>

        {positions && positions.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#161c28] text-slate-400 font-semibold border-b border-border">
                <tr>
                  <th className="py-3 px-4">Symbol</th>
                  <th className="py-3 px-4">Side</th>
                  <th className="py-3 px-4">Qty</th>
                  <th className="py-3 px-4">Entry</th>
                  <th className="py-3 px-4">Stop Loss</th>
                  <th className="py-3 px-4">Take Profit</th>
                  <th className="py-3 px-4">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {positions.map((pos) => (
                  <tr key={pos.id} className="hover:bg-slate-800/40">
                    <td className="py-3 px-4 font-bold text-white">{pos.symbol}</td>
                    <td className="py-3 px-4">
                      <span className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                        pos.side === "LONG" ? "bg-emerald-500/20 text-emerald-400" : "bg-rose-500/20 text-rose-400"
                      }`}>
                        {pos.side}
                      </span>
                    </td>
                    <td className="py-3 px-4 font-mono">{Number(pos.qty).toFixed(4)}</td>
                    <td className="py-3 px-4 font-mono">${Number(pos.entry_price).toLocaleString()}</td>
                    <td className="py-3 px-4 font-mono text-rose-400">${Number(pos.stop_loss).toLocaleString()}</td>
                    <td className="py-3 px-4 font-mono text-emerald-400">${Number(pos.take_profit).toLocaleString()}</td>
                    <td className="py-3 px-4 font-mono text-slate-400 uppercase">{pos.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-8 text-center text-xs text-slate-400">
            No active positions open on testnet exchange.
          </div>
        )}
      </div>

      {/* Risk Metrics & Audit Log */}
      <div className="border border-border rounded-xl bg-surface p-6 flex flex-col justify-between">
        <div>
          <h3 className="text-sm font-bold text-white mb-4 pb-2 border-b border-border flex items-center gap-2">
            <Activity className="w-4 h-4 text-blue-400" />
            Portfolio Risk Health
          </h3>

          <div className="space-y-3 mb-6">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400">Portfolio Equity:</span>
              <span className="font-mono font-bold text-slate-100">${portfolio.equity?.toLocaleString() || "10,000.00"}</span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400">Margin Used / Exposure:</span>
              <span className="font-mono text-slate-200">
                {portfolio.exposure_pct || 0}% / <span className="text-slate-500">{portfolio.max_exposure_pct || 30}% max</span>
              </span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400">Open Positions:</span>
              <span className="font-mono text-slate-200">
                {portfolio.open_positions_count || 0} / {portfolio.max_open_positions || 3} max
              </span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-400">Kill-Switch State:</span>
              <span className={`font-mono font-bold ${killSwitch.active ? "text-rose-400" : "text-emerald-400"}`}>
                {killSwitch.active ? "TRIGGERED (HALTED)" : "NORMAL (ARMED)"}
              </span>
            </div>
          </div>

          <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
            Recent Risk Audit Events
          </h4>
          <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
            {recentEvents.length > 0 ? (
              recentEvents.map((ev) => (
                <div key={ev.id} className="p-2 rounded bg-[#171f2d] text-[11px] border border-border/60">
                  <div className="flex items-center justify-between text-slate-400 font-mono">
                    <span className="font-bold text-slate-200">{ev.rule}</span>
                    <span className={`px-1.5 py-0.2 rounded text-[10px] font-semibold uppercase ${
                      ev.action === "veto" ? "bg-rose-500/20 text-rose-400" : "bg-blue-500/20 text-blue-400"
                    }`}>
                      {ev.action}
                    </span>
                  </div>
                  <div className="text-slate-400 mt-1 truncate">
                    {ev.symbol ? `${ev.symbol}: ` : ""}{JSON.stringify(ev.details || {})}
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-4 text-xs text-slate-500">No recent risk vetoes or warnings.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
