import React from "react";
import { Shield, ShieldAlert, Activity, Wifi, RefreshCw } from "lucide-react";
import { fetchJson } from "../api";

export default function Header({ riskStatus, onRefresh, wsConnected }) {
  const isKillSwitchActive = riskStatus?.kill_switch?.active;

  const handleToggleKillSwitch = async () => {
    try {
      if (isKillSwitchActive) {
        await fetchJson("/killswitch/reset", { method: "POST" });
      } else {
        await fetchJson("/killswitch/trigger", { method: "POST" });
      }
      onRefresh();
    } catch (err) {
      alert("Kill-Switch error: " + err.message);
    }
  };

  return (
    <header className="border-b border-border bg-surface px-6 py-4">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 max-w-7xl mx-auto">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-blue-600/20 border border-blue-500/30 flex items-center justify-center text-blue-400 font-bold text-xl">
            TSP
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold tracking-tight text-white">TradeSphere Pro</h1>
              <span className="text-xs px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 font-mono">
                TESTNET MODE
              </span>
            </div>
            <p className="text-xs text-slate-400">Futures Data Pipeline, Quantitative Scoring & Execution Engine</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-xs">
            <span className={`w-2.5 h-2.5 rounded-full ${wsConnected ? "bg-emerald-400 animate-pulse" : "bg-rose-500"}`} />
            <span className="text-slate-400 font-mono">{wsConnected ? "WS: CONNECTED" : "WS: DISCONNECTED"}</span>
          </div>

          <button
            onClick={onRefresh}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-[#18202f] hover:bg-[#1f293d] text-xs font-medium text-slate-300 transition"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh
          </button>

          <button
            onClick={handleToggleKillSwitch}
            className={`flex items-center gap-2 px-4 py-1.5 rounded-lg border text-xs font-semibold uppercase tracking-wider transition ${
              isKillSwitchActive
                ? "bg-rose-500/20 border-rose-500 text-rose-300 animate-pulse hover:bg-rose-500/30"
                : "bg-emerald-500/10 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20"
            }`}
          >
            {isKillSwitchActive ? (
              <>
                <ShieldAlert className="w-4 h-4 text-rose-400" />
                KILL-SWITCH ACTIVE (CLICK TO RESET)
              </>
            ) : (
              <>
                <Shield className="w-4 h-4 text-emerald-400" />
                SYSTEM ARMED (KILL-SWITCH READY)
              </>
            )}
          </button>
        </div>
      </div>
    </header>
  );
}

