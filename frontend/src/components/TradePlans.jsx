import React, { useState } from "react";
import { Check, X, Clock, AlertCircle } from "lucide-react";
import { fetchJson } from "../api";

export default function TradePlans({ plans, onRefresh }) {
  const [actingId, setActingId] = useState(null);

  const handleApprove = async (planId) => {
    try {
      setActingId(planId);
      await fetchJson(`/plans/${planId}/approve`, { method: "POST" });
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

  if (!plans || plans.length === 0) {
    return (
      <div className="p-8 text-center border border-border rounded-xl bg-surface text-slate-400">
        No trade proposals currently pending. When a 4h candle triggers a LONG or SHORT passing risk rules, it appears here for approval.
      </div>
    );
  }

  return (
    <div className="border border-border rounded-xl bg-surface overflow-hidden">
      <div className="px-6 py-4 border-b border-border flex items-center justify-between">
        <div>
          <h3 className="text-sm font-bold text-white">Risk-Approved Trade Proposals</h3>
          <p className="text-xs text-slate-400">Manual Approval Gate (AUTO_APPROVE = FALSE)</p>
        </div>
        <span className="text-xs px-2.5 py-1 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 font-mono">
          {plans.length} Total Plans
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-[#161c28] text-slate-400 font-semibold border-b border-border">
            <tr>
              <th className="py-3 px-4">Plan ID</th>
              <th className="py-3 px-4">Symbol</th>
              <th className="py-3 px-4">Side</th>
              <th className="py-3 px-4">Qty</th>
              <th className="py-3 px-4">Entry</th>
              <th className="py-3 px-4">Stop Loss</th>
              <th className="py-3 px-4">Take Profit</th>
              <th className="py-3 px-4">Leverage</th>
              <th className="py-3 px-4">Risk Amount</th>
              <th className="py-3 px-4">Status</th>
              <th className="py-3 px-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {plans.map((p) => {
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
                  <td className="py-3 px-4 font-mono text-slate-300">${Number(p.risk_amount).toFixed(2)}</td>
                  <td className="py-3 px-4">
                    <span className={`px-2 py-0.5 rounded text-[11px] font-medium uppercase font-mono ${
                      p.status === "approved"
                        ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                        : p.status === "rejected"
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
                          className="flex items-center gap-1 px-2.5 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-xs transition disabled:opacity-50"
                        >
                          <Check className="w-3.5 h-3.5" />
                          Approve
                        </button>
                        <button
                          disabled={actingId === p.id}
                          onClick={() => handleReject(p.id)}
                          className="flex items-center gap-1 px-2.5 py-1 rounded bg-rose-600 hover:bg-rose-500 text-white font-medium text-xs transition disabled:opacity-50"
                        >
                          <X className="w-3.5 h-3.5" />
                          Reject
                        </button>
                      </div>
                    ) : (
                      <span className="text-[11px] text-slate-500 font-mono">
                        {p.approved_by || "processed"}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

