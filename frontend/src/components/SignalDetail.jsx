import React, { useEffect, useState } from "react";
import { Sparkles, AlertTriangle, CheckCircle2, XCircle, ArrowUpRight, ArrowDownRight, Compass } from "lucide-react";
import { fetchJson } from "../api";

export default function SignalDetail({ selectedSymbol }) {
  const [signalDetail, setSignalDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!selectedSymbol) return;
    let isMounted = true;
    setLoading(true);
    setError(null);

    async function loadSignal() {
      try {
        const signals = await fetchJson(`/signals?symbol=${selectedSymbol}&limit=1`);
        if (!signals || signals.length === 0) {
          if (isMounted) setSignalDetail(null);
          return;
        }
        const detail = await fetchJson(`/signals/${signals[0].id}`);
        if (isMounted) setSignalDetail(detail);
      } catch (err) {
        if (isMounted) setError(err.message);
      } finally {
        if (isMounted) setLoading(false);
      }
    }
    loadSignal();
    return () => { isMounted = false; };
  }, [selectedSymbol]);

  if (loading) {
    return (
      <div className="p-8 text-center border border-border rounded-xl bg-surface text-slate-400">
        Loading signal and AI explanation for {selectedSymbol}...
      </div>
    );
  }

  if (error || !signalDetail || !signalDetail.signal) {
    return (
      <div className="p-8 text-center border border-border rounded-xl bg-surface text-slate-400">
        No active signal details found for {selectedSymbol}.
      </div>
    );
  }

  const { signal, explanation } = signalDetail;
  const contribs = signal.contributions || {};
  const explText = explanation?.text || {};

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Column 1: Signal Header & Score Breakdown */}
      <div className="lg:col-span-2 border border-border rounded-xl bg-surface p-6 flex flex-col justify-between">
        <div>
          <div className="flex items-center justify-between pb-4 border-b border-border">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xl font-bold text-white">{signal.symbol}</span>
                <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
                  {signal.interval}
                </span>
                <span className={`text-xs px-2.5 py-0.5 rounded font-bold uppercase tracking-wider ${
                  signal.direction === "LONG"
                    ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                    : signal.direction === "SHORT"
                    ? "bg-rose-500/20 text-rose-400 border border-rose-500/30"
                    : "bg-amber-500/20 text-amber-400 border border-amber-500/30"
                }`}>
                  {signal.direction}
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-1">
                Candle Close: {new Date(signal.ts).toLocaleString()} | Config: {signal.config_version}
              </p>
            </div>

            <div className="text-right">
              <div className="text-xs text-slate-400 uppercase tracking-wider">Composite Score</div>
              <div className="text-2xl font-mono font-bold text-blue-400">
                {signal.composite_score ? signal.composite_score.toFixed(3) : "0.000"}
              </div>
              <div className="text-[11px] text-slate-400">
                Confidence: <span className="font-mono text-slate-200">{(signal.confidence || 0).toFixed(2)}</span>
              </div>
            </div>
          </div>

          {/* Decision Rules / Hold Reason Banner */}
          {signal.direction === "HOLD" && (
            <div className="my-4 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs flex items-center gap-2">
              <Compass className="w-4 h-4 text-amber-400 shrink-0" />
              <span>
                <b>HOLD Decision Reason:</b> {signal.hold_reason || "Score did not cross action threshold."}
              </span>
            </div>
          )}

          {/* 10 Scored Fields Contribution Table */}
          <div className="mt-4">
            <h4 className="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-3">
              10-Factor Weighted Breakdown
            </h4>
            <div className="space-y-2">
              {Object.entries(contribs).map(([field, item]) => {
                const sc = item.score !== null ? item.score : 0;
                const wt = item.weight || 0;
                const ct = item.contribution || 0;
                const barWidth = Math.min(100, Math.abs(sc) * 100);

                return (
                  <div key={field} className="flex items-center gap-3 text-xs">
                    <span className="w-28 text-slate-400 font-mono truncate">{field}</span>
                    <span className="w-10 text-right text-slate-500 font-mono">{wt}%</span>
                    <div className="flex-1 h-3 bg-[#0d121c] rounded-full overflow-hidden flex items-center relative">
                      <div className="absolute left-1/2 w-[1px] h-full bg-slate-700" />
                      {sc >= 0 ? (
                        <div
                          className="h-full bg-emerald-500 rounded-r"
                          style={{
                            marginLeft: "50%",
                            width: `${barWidth / 2}%`,
                          }}
                        />
                      ) : (
                        <div
                          className="h-full bg-rose-500 rounded-l"
                          style={{
                            marginLeft: `${50 - barWidth / 2}%`,
                            width: `${barWidth / 2}%`,
                          }}
                        />
                      )}
                    </div>
                    <span className={`w-14 text-right font-mono font-medium ${sc >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      {sc !== null ? (sc > 0 ? `+${sc.toFixed(2)}` : sc.toFixed(2)) : "NULL"}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Levels footer */}
        <div className="mt-6 pt-4 border-t border-border grid grid-cols-4 gap-2 text-center text-xs">
          <div className="p-2 rounded bg-[#171f2d]">
            <div className="text-slate-400 text-[10px] uppercase">Entry Ref</div>
            <div className="font-mono font-bold text-slate-100">${signal.entry_price?.toLocaleString() || "---"}</div>
          </div>
          <div className="p-2 rounded bg-[#171f2d]">
            <div className="text-rose-400 text-[10px] uppercase">Stop Loss</div>
            <div className="font-mono font-bold text-rose-300">${signal.stop_loss?.toLocaleString() || "---"}</div>
          </div>
          <div className="p-2 rounded bg-[#171f2d]">
            <div className="text-emerald-400 text-[10px] uppercase">Take Profit</div>
            <div className="font-mono font-bold text-emerald-300">${signal.take_profit?.toLocaleString() || "---"}</div>
          </div>
          <div className="p-2 rounded bg-[#171f2d]">
            <div className="text-blue-400 text-[10px] uppercase">Reward / Risk</div>
            <div className="font-mono font-bold text-blue-300">{signal.rr || 2.0}:1</div>
          </div>
        </div>
      </div>

      {/* Column 2: Plain-Language LLM Explanation */}
      <div className="border border-border rounded-xl bg-surface p-6 flex flex-col justify-between">
        <div>
          <div className="flex items-center gap-2 mb-4 pb-3 border-b border-border">
            <Sparkles className="w-5 h-5 text-purple-400" />
            <div>
              <h3 className="text-sm font-bold text-white">AI Quantitative Analyst</h3>
              <p className="text-[11px] text-slate-400">Provider-Agnostic LLM Explanation (Read-Only)</p>
            </div>
          </div>

          {/* AI Summary */}
          <div className="mb-4">
            <h5 className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Executive Summary</h5>
            <p className="text-xs text-slate-200 leading-relaxed bg-[#161c28] p-3 rounded-lg border border-border/80">
              {explText.summary || "No textual summary provided by explanation layer."}
            </p>
          </div>

          {/* Supporting & Conflicting */}
          <div className="space-y-3 mb-4">
            <div>
              <h5 className="text-[11px] font-semibold text-emerald-400 uppercase tracking-wider mb-1 flex items-center gap-1">
                <CheckCircle2 className="w-3.5 h-3.5" /> Supporting Factors
              </h5>
              <ul className="text-xs text-slate-300 space-y-1 pl-4 list-disc">
                {(explText.supporting_factors || ["Conditions within normal bounds"]).map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            </div>

            <div>
              <h5 className="text-[11px] font-semibold text-amber-400 uppercase tracking-wider mb-1 flex items-center gap-1">
                <AlertTriangle className="w-3.5 h-3.5" /> Conflicting Factors
              </h5>
              <ul className="text-xs text-slate-300 space-y-1 pl-4 list-disc">
                {(explText.conflicting_factors || ["No major divergence detected"]).map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            </div>

            <div>
              <h5 className="text-[11px] font-semibold text-rose-400 uppercase tracking-wider mb-1 flex items-center gap-1">
                <XCircle className="w-3.5 h-3.5" /> Main Risks
              </h5>
              <ul className="text-xs text-slate-300 space-y-1 pl-4 list-disc">
                {(explText.main_risks || ["Market volatility"]).map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        <div className="pt-3 border-t border-border text-[10px] text-slate-500 font-mono">
          Provider: {explanation?.provider || "internal_template"} | Model: {explanation?.model || "v1"}
        </div>
      </div>
    </div>
  );
}

