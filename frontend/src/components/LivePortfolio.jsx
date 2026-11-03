import React from "react";
import { Wallet, TrendingUp, TrendingDown, ShieldCheck, CheckCircle2, AlertCircle, RefreshCw, Layers } from "lucide-react";

export default function LivePortfolio({ portfolio, onRefresh }) {
  if (!portfolio) {
    return (
      <div className="p-8 text-center border border-border rounded-xl bg-surface text-slate-400">
        Loading live Binance portfolio...
      </div>
    );
  }

  const {
    wallet_balance = 0,
    unrealized_pnl = 0,
    total_equity = 0,
    available_balance = 0,
    positions = [],
    open_orders = [],
    exchange = "Binance Futures Testnet",
    status = "connected",
  } = portfolio;

  const isProfit = unrealized_pnl >= 0;

  return (
    <div className="space-y-6">
      {/* Real Binance Account Overview Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Equity */}
        <div className="p-5 border border-border rounded-xl bg-surface relative overflow-hidden">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Total Account Equity
            </span>
            <Wallet className="w-4 h-4 text-blue-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-white">
            ${Number(total_equity).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="mt-2 flex items-center gap-1.5 text-xs text-slate-400">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>Binance Futures Testnet</span>
          </div>
        </div>

        {/* Live Unrealized PnL */}
        <div className={`p-5 border rounded-xl bg-surface relative overflow-hidden ${
          isProfit ? "border-emerald-500/30 bg-emerald-950/10" : "border-rose-500/30 bg-rose-950/10"
        }`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Live Floating Profit / Loss
            </span>
            {isProfit ? (
              <TrendingUp className="w-4 h-4 text-emerald-400" />
            ) : (
              <TrendingDown className="w-4 h-4 text-rose-400" />
            )}
          </div>
          <div className={`text-2xl font-bold font-mono ${isProfit ? "text-emerald-400" : "text-rose-400"}`}>
            {isProfit ? "+" : ""}${Number(unrealized_pnl).toFixed(2)} USDT
          </div>
          <div className="mt-2 text-xs text-slate-400">
            Live profit from open market positions
          </div>
        </div>

        {/* Wallet Cash Balance */}
        <div className="p-5 border border-border rounded-xl bg-surface">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Wallet Cash Balance
            </span>
            <span className="text-xs font-mono text-slate-400">USDT</span>
          </div>
          <div className="text-2xl font-bold font-mono text-slate-200">
            ${Number(wallet_balance).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="mt-2 text-xs text-slate-400">
            Realized cash sitting in Binance wallet
          </div>
        </div>

        {/* Available Trading Margin */}
        <div className="p-5 border border-border rounded-xl bg-surface">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Free Available Margin
            </span>
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-slate-200">
            ${Number(available_balance).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="mt-2 text-xs text-slate-400">
            Funds free for new trade allocations
          </div>
        </div>
      </div>

      {/* Active Binance Positions Section */}
      <div className="border border-border rounded-xl bg-surface overflow-hidden">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-white">Live Open Positions on Binance</h3>
              <span className="text-[11px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
                {positions.length} ACTIVE
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Live positions verified directly on Binance Futures matching engine
            </p>
          </div>
          <button
            onClick={onRefresh}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-[#18202f] hover:bg-[#1f293d] text-xs font-medium text-slate-300 transition"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh Exchange
          </button>
        </div>

        {positions.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#161c28] text-slate-400 font-semibold border-b border-border">
                <tr>
                  <th className="py-3 px-4">Symbol</th>
                  <th className="py-3 px-4">Side</th>
                  <th className="py-3 px-4">Size (Qty)</th>
                  <th className="py-3 px-4">Entry Price</th>
                  <th className="py-3 px-4">Notional Value</th>
                  <th className="py-3 px-4">Leverage</th>
                  <th className="py-3 px-4">Floating PnL ($)</th>
                  <th className="py-3 px-4">Return (ROI %)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {positions.map((p, idx) => {
                  const posProfit = Number(p.unrealized_pnl) >= 0;
                  return (
                    <tr key={idx} className="hover:bg-slate-800/40 transition">
                      <td className="py-3 px-4 font-bold text-white flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
                        {p.symbol}
                      </td>
                      <td className="py-3 px-4">
                        <span className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                          p.side === "LONG" ? "bg-emerald-500/20 text-emerald-400" : "bg-rose-500/20 text-rose-400"
                        }`}>
                          {p.side}
                        </span>
                      </td>
                      <td className="py-3 px-4 font-mono text-slate-200">{Number(p.qty).toFixed(4)}</td>
                      <td className="py-3 px-4 font-mono text-slate-200">${Number(p.entry_price).toLocaleString()}</td>
                      <td className="py-3 px-4 font-mono text-slate-300">${Number(p.notional).toLocaleString()}</td>
                      <td className="py-3 px-4 font-mono text-slate-300">{p.leverage}x</td>
                      <td className={`py-3 px-4 font-mono font-bold ${posProfit ? "text-emerald-400" : "text-rose-400"}`}>
                        {posProfit ? "+" : ""}${Number(p.unrealized_pnl).toFixed(2)} USDT
                      </td>
                      <td className="py-3 px-4 font-mono font-bold">
                        <span className={`px-2 py-0.5 rounded text-[11px] ${
                          posProfit ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                        }`}>
                          {posProfit ? "+" : ""}{Number(p.pnl_pct).toFixed(2)}%
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-8 text-center text-xs text-slate-400">
            No positions currently open on Binance. When you approve a Trade Proposal, it executes and appears here immediately.
          </div>
        )}
      </div>

      {/* Active Binance Stop-Loss & Take-Profit Orders Section */}
      <div className="border border-border rounded-xl bg-surface overflow-hidden">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-white">Active Protection Orders on Binance (Stop-Loss & Take-Profit)</h3>
              <span className="text-[11px] px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 font-mono">
                {open_orders.length} ACTIVE ORDERS
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Guarding your open positions 24/7 on Binance Futures matching engine
            </p>
          </div>
        </div>

        {open_orders.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#161c28] text-slate-400 font-semibold border-b border-border">
                <tr>
                  <th className="py-3 px-4">Order ID</th>
                  <th className="py-3 px-4">Symbol</th>
                  <th className="py-3 px-4">Order Type</th>
                  <th className="py-3 px-4">Side</th>
                  <th className="py-3 px-4">Quantity</th>
                  <th className="py-3 px-4">Trigger Price</th>
                  <th className="py-3 px-4">Reduce Only</th>
                  <th className="py-3 px-4">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {open_orders.map((o) => {
                  const isStop = o.type.includes("STOP");
                  return (
                    <tr key={o.order_id} className="hover:bg-slate-800/40 transition">
                      <td className="py-3 px-4 font-mono text-slate-400">{o.order_id}</td>
                      <td className="py-3 px-4 font-bold text-white">{o.symbol}</td>
                      <td className="py-3 px-4">
                        <span className={`px-2 py-0.5 rounded text-[11px] font-mono font-semibold ${
                          isStop ? "bg-rose-500/20 text-rose-400" : "bg-emerald-500/20 text-emerald-400"
                        }`}>
                          {o.type}
                        </span>
                      </td>
                      <td className="py-3 px-4 font-mono text-slate-300 font-semibold">{o.side}</td>
                      <td className="py-3 px-4 font-mono text-slate-200">{Number(o.quantity).toFixed(4)}</td>
                      <td className={`py-3 px-4 font-mono font-bold ${isStop ? "text-rose-400" : "text-emerald-400"}`}>
                        ${Number(o.trigger_price).toLocaleString()}
                      </td>
                      <td className="py-3 px-4 font-mono text-slate-400">
                        {o.reduce_only ? "YES (Close Only)" : "NO"}
                      </td>
                      <td className="py-3 px-4">
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-blue-500/10 text-blue-400 border border-blue-500/20 uppercase">
                          {o.status}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-8 text-center text-xs text-slate-400">
            No open conditional orders waiting on Binance.
          </div>
        )}
      </div>
    </div>
  );
}
