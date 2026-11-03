import React, { useEffect, useState, useRef } from "react";
import Header from "./components/Header";
import LivePortfolio from "./components/LivePortfolio";
import MarketOverview from "./components/MarketOverview";
import SignalDetail from "./components/SignalDetail";
import TradePlans from "./components/TradePlans";
import PositionsRisk from "./components/PositionsRisk";
import BacktestResults from "./components/BacktestResults";
import { fetchJson } from "./api";
import { Wallet, Layers, FileCheck, Shield, BarChart2, TrendingUp, TrendingDown, ArrowRight } from "lucide-react";

export default function App() {
  const [activeTab, setActiveTab] = useState("portfolio"); // Default to user's real Binance portfolio!
  const [portfolio, setPortfolio] = useState(null);
  const [marketData, setMarketData] = useState([]);
  const [selectedSymbol, setSelectedSymbol] = useState("BTCUSDT");
  const [plans, setPlans] = useState([]);
  const [positions, setPositions] = useState([]);
  const [riskStatus, setRiskStatus] = useState(null);
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef(null);

  const loadData = async () => {
    try {
      const [port, overview, pList, posList, rStat] = await Promise.all([
        fetchJson("/portfolio").catch(() => null),
        fetchJson("/market_overview").catch(() => []),
        fetchJson("/plans").catch(() => []),
        fetchJson("/positions").catch(() => []),
        fetchJson("/risk/status").catch(() => null),
      ]);
      setPortfolio(port);
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

    // Set polling interval for live portfolio & market (every 5 seconds)
    const timer = setInterval(() => {
      fetchJson("/portfolio")
        .then((p) => setPortfolio(p))
        .catch(() => {});
    }, 5000);

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
          setTimeout(connectWs, 3000);
        };
      } catch {
        setWsConnected(false);
      }
    };

    connectWs();
    return () => {
      clearInterval(timer);
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  const pnl = portfolio?.unrealized_pnl || 0;
  const isProfit = pnl >= 0;
  const proposedCount = plans.filter((p) => p.status === "proposed").length;

  return (
    <div className="min-h-screen flex flex-col bg-[#0b0e14] text-slate-100">
      <Header riskStatus={riskStatus} onRefresh={loadData} wsConnected={wsConnected} />

      {/* Global Quick-Glance Live Binance Bar */}
      {portfolio && (
        <div className="border-b border-border bg-[#101622] px-6 py-2.5">
          <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4 text-xs font-mono">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 text-[11px] font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                BINANCE TESTNET
              </span>
              <span className="text-slate-400">Equity:</span>
              <span className="font-bold text-white">${Number(portfolio.total_equity).toLocaleString()} USDT</span>
            </div>

            <div className="flex items-center gap-6">
              <div className="flex items-center gap-1.5">
                <span className="text-slate-400">Cash:</span>
                <span className="text-slate-200 font-semibold">${Number(portfolio.wallet_balance).toLocaleString()}</span>
              </div>

              <div className="flex items-center gap-1.5">
                <span className="text-slate-400">Live PnL:</span>
                <span className={`font-bold flex items-center gap-1 ${isProfit ? "text-emerald-400" : "text-rose-400"}`}>
                  {isProfit ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
                  {isProfit ? "+" : ""}${Number(pnl).toFixed(2)} USDT
                </span>
              </div>

              <div className="flex items-center gap-1.5">
                <span className="text-slate-400">Open Trades:</span>
                <span className="px-1.5 py-0.2 rounded bg-slate-800 text-slate-200 font-bold">
                  {portfolio.positions?.length || 0}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      <main className="flex-1 max-w-7xl w-full mx-auto p-6 space-y-6">
        {/* Navigation Tabs */}
        <div className="flex flex-wrap items-center gap-2 border-b border-border pb-3 text-xs font-medium">
          {/* Real Binance Portfolio Tab */}
          <button
            onClick={() => setActiveTab("portfolio")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition relative ${
              activeTab === "portfolio"
                ? "bg-blue-600 text-white shadow-lg shadow-blue-500/20"
                : "text-slate-400 hover:text-white hover:bg-surface"
            }`}
          >
            <Wallet className="w-4 h-4 text-emerald-400" />
            <span>Live Binance Portfolio</span>
            {portfolio?.positions?.length > 0 && (
              <span className={`px-1.5 py-0.2 rounded text-[10px] font-mono font-bold ${
                isProfit ? "bg-emerald-500/20 text-emerald-400" : "bg-rose-500/20 text-rose-400"
              }`}>
                {isProfit ? "+" : ""}${Number(pnl).toFixed(2)}
              </span>
            )}
          </button>

          {/* Market Overview Tab */}
          <button
            onClick={() => setActiveTab("overview")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition ${
              activeTab === "overview"
                ? "bg-blue-600 text-white shadow-lg shadow-blue-500/20"
                : "text-slate-400 hover:text-white hover:bg-surface"
            }`}
          >
            <Layers className="w-4 h-4" />
            <span>Market & Signals</span>
          </button>

          {/* Trade Proposals Tab */}
          <button
            onClick={() => setActiveTab("plans")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition relative ${
              activeTab === "plans"
                ? "bg-blue-600 text-white shadow-lg shadow-blue-500/20"
                : "text-slate-400 hover:text-white hover:bg-surface"
            }`}
          >
            <FileCheck className="w-4 h-4" />
            <span>Trade Proposals</span>
            {proposedCount > 0 && (
              <span className="px-1.5 py-0.2 rounded-full bg-amber-500 text-slate-950 font-bold text-[10px] animate-pulse">
                {proposedCount} Pending
              </span>
            )}
          </button>

          {/* Positions & Risk Health Tab */}
          <button
            onClick={() => setActiveTab("risk")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition ${
              activeTab === "risk"
                ? "bg-blue-600 text-white shadow-lg shadow-blue-500/20"
                : "text-slate-400 hover:text-white hover:bg-surface"
            }`}
          >
            <Shield className="w-4 h-4" />
            <span>Risk Rules & Audit</span>
          </button>

          {/* Backtest Simulations Tab */}
          <button
            onClick={() => setActiveTab("backtests")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg transition ${
              activeTab === "backtests"
                ? "bg-blue-600 text-white shadow-lg shadow-blue-500/20"
                : "text-slate-400 hover:text-white hover:bg-surface"
            }`}
          >
            <BarChart2 className="w-4 h-4" />
            <span>Historical Backtests</span>
          </button>
        </div>

        {/* Tab Content */}
        {activeTab === "portfolio" && (
          <LivePortfolio portfolio={portfolio} onRefresh={loadData} />
        )}

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
          <div className="space-y-4">
            <div className="p-4 border border-blue-500/20 rounded-xl bg-blue-950/20 text-xs text-slate-300">
              <span className="font-bold text-white">What are Backtest Simulations?</span>
              <p className="mt-1 text-slate-400 leading-relaxed">
                Backtests are <strong>historical laboratory simulations</strong>. They test our 10 quantitative scoring rules against 3 months of past candle data with exchange fees (0.05%), slippage (0.02%), and funding rates to verify that the mathematical model has positive expectancy before live capital is risked.
              </p>
            </div>
            <BacktestResults />
          </div>
        )}
      </main>
    </div>
  );
}
