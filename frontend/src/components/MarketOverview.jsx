import React from "react";
import { TrendingUp, TrendingDown, Minus, BarChart2 } from "lucide-react";

export default function MarketOverview({ marketData, onSelectSymbol, selectedSymbol }) {
  if (!marketData || marketData.length === 0) {
    return (
      <div className="p-8 text-center border border-border rounded-xl bg-surface text-slate-400">
        Loading market overview data...
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
      {marketData.map((item) => {
        const isSelected = selectedSymbol === item.symbol;
        const sig = item.latest_signal;
        const dir = sig?.direction || "HOLD";

        let badgeBg = "bg-amber-500/10 text-amber-400 border-amber-500/20";
        let Icon = Minus;
        if (dir === "LONG") {
          badgeBg = "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
          Icon = TrendingUp;
        } else if (dir === "SHORT") {
          badgeBg = "bg-rose-500/10 text-rose-400 border-rose-500/20";
          Icon = TrendingDown;
        }

        return (
          <div
            key={item.symbol}
            onClick={() => onSelectSymbol(item.symbol)}
            className={`p-4 rounded-xl border cursor-pointer transition flex flex-col justify-between ${
              isSelected
                ? "bg-blue-600/10 border-blue-500 ring-1 ring-blue-500/40"
                : "bg-surface border-border hover:border-slate-600"
            }`}
          >
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="font-bold text-white tracking-wide">{item.symbol}</span>
                <span className={`flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded border ${badgeBg}`}>
                  <Icon className="w-3 h-3" />
                  {dir}
                </span>
              </div>

              <div className="text-xl font-mono font-bold text-slate-100 mb-1">
                ${item.price ? item.price.toLocaleString(undefined, { minimumFractionDigits: 2 }) : "---"}
              </div>

              <div className="flex items-center justify-between text-xs text-slate-400 mb-3">
                <span>Funding:</span>
                <span className="font-mono text-slate-300">
                  {item.funding_rate !== null ? `${(item.funding_rate * 100).toFixed(4)}%` : "N/A"}
                </span>
              </div>
            </div>

            <div className="pt-2 border-t border-border/60">
              <div className="flex items-center justify-between text-[11px] text-slate-400">
                <span>Score: <b className="text-slate-200">{sig?.composite_score ? sig.composite_score.toFixed(3) : "0.00"}</b></span>
                <span>Conf: <b className="text-slate-200">{sig?.confidence ? sig.confidence.toFixed(2) : "0.00"}</b></span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

