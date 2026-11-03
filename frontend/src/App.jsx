import React, { useEffect, useState, useRef } from "react";
import Header from "./components/Header";
import MarketOverview from "./components/MarketOverview";
import SignalDetail from "./components/SignalDetail";
import TradePlans from "./components/TradePlans";
import PositionsRisk from "./components/PositionsRisk";
import BacktestResults from "./components/BacktestResults";
import { fetchJson } from "./api";
import { Layers, FileCheck, Shield, BarChart2 } from "lucide-react";

export default function App() {
  const [activeTab, setActiveTab] = useState("overview");
  const [marketData, setMarketData] = useState([]);
  const [selectedSymbol, setSelectedSymbol] = useState("BTCUSDT");
  const [plans, setPlans] = useState([]);
  const [positions, setPositions] = useState([]);
  const [riskStatus, setRiskStatus] = useState(null);
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef(null);

  const loadData = async () => {
    try {
      const [overview, pList, posList, rStat] = await Promise.all([
        fetchJson("/market_overview").catch(() => []),
        fetchJson("/plans").catch(() => []),
        fetchJson("/positions").catch(() => []),
        fetchJson("/risk/status").catch(() => null),
      ]);
      setMarketData(overview);
      setPlans(pList);
      setPositions(posList);
      setRiskStatus(rStat);
    } catch (err) {
      console.error("Dashboard data load error:", err);
    }
  };

  useEffect(() => {
    loadData();

    // WebSocket connection
    const connectWs = () => {
      try {
        const ws = new WebSocket("ws://localhost:8000/stream");
        wsRef.current = ws;

        ws.onopen = () => {
          setWsConnected(true);
        };

        ws.onmessage = (event) => {
          try {
            const msg = JSON.parse(event.data);
            if (msg.type === "plan_update" || msg.type === "kill_switch" || msg.type === "signals:new") {
              loadData();
            }
          } catch {}
        };

        ws.onclose = () => {
          setWsConnected(false);
          // Try reconnect in 3s
          setTimeout(connectWs, 3000);
        };
      } catch {
        setWsConnected(false);
      }
    };

    connectWs();
    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  return (
    <div className="min-h-screen flex flex-col bg-[#0b0e14] text-slate-100">
      <Header riskStatus={riskStatus} onRefresh={loadData} wsConnected={wsConnected} />

      <main className="flex-1 max-w-7xl w-full mx-auto p-6 space-y-6">
        {/* Navigation Tabs */}
        <div className="flex items-center gap-2 border-b border-border pb-3 text-xs font-medium">
          <button
            onClick={() => setActiveTab("overview")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition ${
              activeTab === "overview"
                ? "bg-blue-600 text-white shadow-lg shadow-blue-500/20"
                : "text-slate-400 hover:text-white hover:bg-surface"
            }`}
          >
            <Layers className="w-4 h-4" />
            Market & Signals
          </button>

          <button
            onClick={() => setActiveTab("plans")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition relative ${
              activeTab === "plans"
                ? "bg-blue-600 text-white shadow-lg shadow-blue-500/20"
                : "text-slate-400 hover:text-white hover:bg-surface"
            }`}
          >
            <FileCheck className="w-4 h-4" />
            Trade Proposals
            {plans.filter((p) => p.status === "proposed").length > 0 && (
              <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping absolute top-2 right-2" />
            )}
          </button>

          <button
            onClick={() => setActiveTab("risk")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition ${
              activeTab === "risk"
                ? "bg-blue-600 text-white shadow-lg shadow-blue-500/20"
                : "text-slate-400 hover:text-white hover:bg-surface"
            }`}
          >
            <Shield className="w-4 h-4" />
            Positions & Risk Health
          </button>

          <button
            onClick={() => setActiveTab("backtests")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition ${
              activeTab === "backtests"
                ? "bg-blue-600 text-white shadow-lg shadow-blue-500/20"
                : "text-slate-400 hover:text-white hover:bg-surface"
            }`}
          >
            <BarChart2 className="w-4 h-4" />
            Backtest Simulations
          </button>
        </div>

        {/* Tab Content */}
        {activeTab === "overview" && (
          <div className="space-y-6">
            <MarketOverview
              marketData={marketData}
              selectedSymbol={selectedSymbol}
              onSelectSymbol={setSelectedSymbol}
            />
            <SignalDetail selectedSymbol={selectedSymbol} />
          </div>
        )}

        {activeTab === "plans" && (
          <TradePlans plans={plans} onRefresh={loadData} />
        )}

        {activeTab === "risk" && (
          <PositionsRisk positions={positions} riskStatus={riskStatus} />
        )}

        {activeTab === "backtests" && (
          <BacktestResults />
        )}
      </main>
    </div>
  );
}

