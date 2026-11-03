import React, { useState } from "react";
import { Check, X, Clock, AlertCircle, HelpCircle, Filter } from "lucide-react";
import { fetchJson } from "../api";

export default function TradePlans({ plans, onRefresh }) {
  const [actingId, setActingId] = useState(null);
  const [filter, setFilter] = useState("proposed"); // "proposed", "filled", "all"

  const handleApprove = async (planId) => {
    try {
      setActingId(planId);
      const res = await fetchJson(`/plans/${planId}/approve`, { method: "POST" });
      alert(`Plan #${planId} APPROVED! Order placed on Binance Testnet.`);
      onRefresh();
    } catch (err) {
      alert("Approval failed: " + err.message);
    } finally {
      setActingId(null);
    }
  };

  const handleReject = async (planId) => {
    try {
      setActingId(planId);
      await fetchJson(`/plans/${planId}/reject`, { method: "POST" });
      onRefresh();
    } catch (err) {
      alert("Rejection failed: " + err.message);
    } finally {
      setActingId(null);
    }
  };

  const proposedPlans = (plans || []).filter((p) => p.status === "proposed");
  const filledPlans = (plans || []).filter((p) => p.status === "filled" || p.status === "approved");
  
  const displayedPlans = (plans || []).filter((p) => {
    if (filter === "proposed") return p.status === "proposed";
    if (filter === "filled") return p.status === "filled" || p.status === "approved";
    return true;
  });

  return (
    <div className="space-y-6">
      {/* Educational Explainer Banner */}
      <div className="p-4 border border-blue-500/20 rounded-xl bg-blue-950/20 text-xs text-slate-300 flex items-start gap-3">
        <HelpCircle className="w-5 h-5 text-blue-400 shrink-0 mt-0.5" />
        <div>
          <span className="font-bold text-white">What is the Trade Proposals Page?</span>
          <p className="mt-1 leading-relaxed text-slate-400">
            Whenever a 4-hour candle closes, TradeSphere Pro analyzes 10 quantitative market factors (momentum, RSI, funding rate, liquidation zones, sentiment). If a coin passes all 10 institutional risk rules, a <strong>Trade Proposal</strong> is generated.
          </p>
          <p className="mt-1 leading-relaxed text-slate-400">
            Because safety is our top priority, <code>AUTO_APPROVE = FALSE</code> by default. The system waits for you to click <strong>Approve</strong>. Once approved, TradeSphere sends the MARKET entry order and the conditional Stop-Loss + Take-Profit orders directly to Binance Futures Testnet!
          </p>
        </div>
      </div>

      {/* Main Table Card */}
      <div className="border border-border rounded-xl bg-surface overflow-hidden">
        <div className="px-6 py-4 border-b border-border flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h3 className="text-sm font-bold text-white">Algorithmic Trade Proposals</h3>
            <p className="text-xs text-slate-400">Manual Approval Gate (AUTO_APPROVE = FALSE)</p>
          </div>

          {/* Filter Tabs */}
          <div className="flex items-center gap-1.5 p-1 bg-[#121824] rounded-lg border border-border text-xs">
            <button
              onClick={() => setFilter("proposed")}
              className={`px-3 py-1 rounded-md transition font-medium flex items-center gap-1.5 ${
                filter === "proposed"
                  ? "bg-blue-600 text-white shadow-sm"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              <span>Pending Review</span>
              <span className="px-1.5 py-0.2 rounded-full bg-blue-900/60 text-[10px] font-mono">
                {proposedPlans.length}
              </span>
            </button>

            <button
              onClick={() => setFilter("filled")}
              className={`px-3 py-1 rounded-md transition font-medium flex items-center gap-1.5 ${
                filter === "filled"
                  ? "bg-blue-600 text-white shadow-sm"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              <span>Approved & Executed</span>
              <span className="px-1.5 py-0.2 rounded-full bg-slate-800 text-[10px] font-mono">
                {filledPlans.length}
              </span>
            </button>

            <button
              onClick={() => setFilter("all")}
              className={`px-3 py-1 rounded-md transition font-medium ${
                filter === "all"
                  ? "bg-blue-600 text-white shadow-sm"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              All ({plans?.length || 0})
            </button>
          </div>
        </div>

        {displayedPlans.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#161c28] text-slate-400 font-semibold border-b border-border">
                <tr>
                  <th className="py-3 px-4">Plan ID</th>
                  <th className="py-3 px-4">Symbol</th>
                  <th className="py-3 px-4">Side</th>
                  <th className="py-3 px-4">Order Qty</th>
                  <th className="py-3 px-4">Proposed Entry</th>
                  <th className="py-3 px-4">Stop Loss</th>
                  <th className="py-3 px-4">Take Profit</th>
                  <th className="py-3 px-4">Leverage</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4 text-right">Approval Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {displayedPlans.map((p) => {
                  const isProposed = p.status === "proposed";
                  return (
                    <tr key={p.id} className="hover:bg-slate-800/40 transition">
                      <td className="py-3 px-4 font-mono text-slate-400">#{p.id}</td>
                      <td className="py-3 px-4 font-bold text-white">{p.symbol}</td>
                      <td className="py-3 px-4">
                        <span className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                          p.side === "LONG" ? "bg-emerald-500/20 text-emerald-400" : "bg-rose-500/20 text-rose-400"
                        }`}>
                          {p.side}
                        </span>
                      </td>
                      <td className="py-3 px-4 font-mono text-slate-200">{Number(p.qty).toFixed(4)}</td>
                      <td className="py-3 px-4 font-mono text-slate-200">${Number(p.entry_price).toLocaleString()}</td>
                      <td className="py-3 px-4 font-mono text-rose-400">${Number(p.stop_loss).toLocaleString()}</td>
                      <td className="py-3 px-4 font-mono text-emerald-400">${Number(p.take_profit).toLocaleString()}</td>
                      <td className="py-3 px-4 font-mono text-slate-300">{p.leverage}x</td>
                      <td className="py-3 px-4">
                        <span className={`px-2 py-0.5 rounded text-[11px] font-medium uppercase font-mono ${
                          p.status === "approved" || p.status === "filled"
                            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                            : p.status === "rejected" || p.status === "failed"
                            ? "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                            : "bg-amber-500/10 text-amber-400 border border-amber-500/20 animate-pulse"
                        }`}>
                          {p.status}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-right">
                        {isProposed ? (
                          <div className="flex items-center justify-end gap-2">
                            <button
                              disabled={actingId === p.id}
                              onClick={() => handleApprove(p.id)}
                              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-xs transition disabled:opacity-50 shadow-sm"
                            >
                              <Check className="w-3.5 h-3.5" />
                              Approve & Send to Binance
                            </button>
                            <button
                              disabled={actingId === p.id}
                              onClick={() => handleReject(p.id)}
                              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-medium text-xs transition disabled:opacity-50"
                            >
                              <X className="w-3.5 h-3.5" />
                              Reject
                            </button>
                          </div>
                        ) : (
                          <span className="text-[11px] text-slate-500 font-mono">
                            {p.status === "filled" ? "Executed on Binance" : p.approved_by || "Processed"}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-8 text-center text-xs text-slate-400">
            {filter === "proposed"
              ? "No trade proposals currently waiting for review. When a new 4h candle triggers a signal passing risk gates, it appears here for you to click Approve."
              : "No plans found in this filter."}
          </div>
        )}
      </div>
    </div>
  );
}
