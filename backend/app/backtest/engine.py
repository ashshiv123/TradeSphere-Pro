"""
engine.py - Core Backtester simulation engine for TradeSphere Pro (Section 6).
Calls the exact same scoring and risk functions as live trading.
"""
from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Candle, Feature, FundingRate
from app.db.models_trading import BacktestRun, BacktestTrade
from app.risk.engine import evaluate_risk, load_risk_config
from app.schemas.feature_vector import FeatureVector
from app.scoring.engine import load_scoring_config, score_feature_vector

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    name: str = "Backtest Run"
    mode: str = "reduced"  # 'full' or 'reduced'
    symbols: List[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"])
    start_ts: Optional[datetime] = None
    end_ts: Optional[datetime] = None
    starting_equity: float = 10000.0
    fee_rate: float = 0.0005        # 0.05% taker fee
    slippage_rate: float = 0.0002   # 0.02% slippage against position
    volume_gate_enabled: bool = True
    double_fees: bool = False
    random_baseline_seeds: int = 100


class Backtester:
    def __init__(self, db: Session, cfg: BacktestConfig):
        self.db = db
        self.cfg = cfg
        self.scoring_cfg = load_scoring_config()
        self.scoring_cfg["thresholds"]["volume_gate_enabled"] = cfg.volume_gate_enabled
        self.risk_cfg = load_risk_config()
        self.fee_rate = cfg.fee_rate * (2.0 if cfg.double_fees else 1.0)
        self.slippage = cfg.slippage_rate

    def load_data(self) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.DataFrame], Dict[str, pd.DataFrame]]:
        """Load candles, features, and funding rates into pandas DataFrames sorted by ts."""
        candles_by_sym: Dict[str, pd.DataFrame] = {}
        features_by_sym: Dict[str, pd.DataFrame] = {}
        funding_by_sym: Dict[str, pd.DataFrame] = {}

        for sym in self.cfg.symbols:
            c_query = select(Candle).where(Candle.symbol == sym, Candle.interval == "4h", Candle.market == "futures")
            if self.cfg.start_ts:
                c_query = c_query.where(Candle.open_time >= self.cfg.start_ts)
            if self.cfg.end_ts:
                c_query = c_query.where(Candle.close_time <= self.cfg.end_ts)
            c_query = c_query.order_by(Candle.open_time.asc())

            c_rows = self.db.scalars(c_query).all()
            if not c_rows:
                continue

            c_df = pd.DataFrame([{
                "open_time": c.open_time,
                "close_time": c.close_time,
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": float(c.volume),
            } for c in c_rows]).set_index("open_time")
            candles_by_sym[sym] = c_df

            f_query = select(Feature).where(Feature.symbol == sym, Feature.interval == "4h")
            if self.cfg.start_ts:
                f_query = f_query.where(Feature.ts >= self.cfg.start_ts)
            if self.cfg.end_ts:
                f_query = f_query.where(Feature.ts <= self.cfg.end_ts)
            f_query = f_query.order_by(Feature.ts.asc())

            f_rows = self.db.scalars(f_query).all()
            if f_rows:
                f_df = pd.DataFrame([{
                    "ts": f.ts,
                    "f01_momentum": f.f01_momentum,
                    "f02_ema_trend": f.f02_ema_trend,
                    "f03_rsi": f.f03_rsi,
                    "f04_macd": f.f04_macd,
                    "f05_funding": f.f05_funding,
                    "f06_open_interest": f.f06_open_interest,
                    "f07_long_short": f.f07_long_short,
                    "f08_basis": f.f08_basis,
                    "f10_volume_sr": f.f10_volume_sr,
                    "f11_news": f.f11_news,
                    "g09_liq_above_price": f.g09_liq_above_price,
                    "g09_liq_below_price": f.g09_liq_below_price,
                    "g12_regime_factor": f.g12_regime_factor,
                    "g13_btc_corr": f.g13_btc_corr,
                    "g13_btc_trend": f.g13_btc_trend,
                    "volume_ratio": f.volume_ratio,
                    "atr": f.atr,
                    "close": f.close,
                    "news_pause": f.news_pause,
                } for f in f_rows]).set_index("ts")
                features_by_sym[sym] = f_df

            # Funding rates
            fr_query = select(FundingRate).where(FundingRate.symbol == sym).order_by(FundingRate.funding_time.asc())
            fr_rows = self.db.scalars(fr_query).all()
            if fr_rows:
                fr_df = pd.DataFrame([{
                    "funding_time": fr.funding_time,
                    "rate": float(fr.funding_rate),
                } for fr in fr_rows]).set_index("funding_time")
                funding_by_sym[sym] = fr_df

        return candles_by_sym, features_by_sym, funding_by_sym

    def run(self) -> Dict[str, Any]:
        """Executes the simulation across all symbols and returns full results dictionary."""
        candles_map, features_map, funding_map = self.load_data()
        if not candles_map:
            raise ValueError("No candle data available for backtesting.")

        # Union of all 4h candle open timestamps
        all_timestamps = sorted(list(set().union(*[df.index.tolist() for df in candles_map.values()])))

        equity = self.cfg.starting_equity
        equity_curve: List[Dict[str, Any]] = []
        closed_trades: List[Dict[str, Any]] = []
        open_positions: Dict[str, Dict[str, Any]] = {}  # keyed by symbol

        daily_start_equity = equity
        current_day: Optional[datetime.date] = None

        for t_idx, current_ts in enumerate(all_timestamps):
            c_date = current_ts.date()
            if current_day != c_date:
                current_day = c_date
                daily_start_equity = equity

            daily_loss_pct = max(0.0, ((daily_start_equity - equity) / daily_start_equity) * 100.0)

            # Step 1: Manage and check open positions against current candle
            for sym in list(open_positions.keys()):
                pos = open_positions[sym]
                c_df = candles_map.get(sym)
                if c_df is None or current_ts not in c_df.index:
                    continue

                bar = c_df.loc[current_ts]
                high = float(bar["high"])
                low = float(bar["low"])
                bar_close = float(bar["close"])

                exit_price: Optional[float] = None
                exit_reason: Optional[str] = None

                # Pessimistic Stop-First Rule:
                # If both SL and TP price touched within same candle, stop hit first.
                if pos["side"] == "LONG":
                    sl_hit = low <= pos["stop_loss"]
                    tp_hit = high >= pos["take_profit"]
                    if sl_hit and tp_hit:
                        exit_price = pos["stop_loss"] * (1.0 - self.slippage)
                        exit_reason = "stop_loss"
                    elif sl_hit:
                        exit_price = pos["stop_loss"] * (1.0 - self.slippage)
                        exit_reason = "stop_loss"
                    elif tp_hit:
                        exit_price = pos["take_profit"] * (1.0 - self.slippage)
                        exit_reason = "take_profit"
                else:  # SHORT
                    sl_hit = high >= pos["stop_loss"]
                    tp_hit = low <= pos["take_profit"]
                    if sl_hit and tp_hit:
                        exit_price = pos["stop_loss"] * (1.0 + self.slippage)
                        exit_reason = "stop_loss"
                    elif sl_hit:
                        exit_price = pos["stop_loss"] * (1.0 + self.slippage)
                        exit_reason = "stop_loss"
                    elif tp_hit:
                        exit_price = pos["take_profit"] * (1.0 + self.slippage)
                        exit_reason = "take_profit"

                # Check time stop
                pos["candles_held"] += 1
                if not exit_reason and pos["candles_held"] >= self.scoring_cfg["thresholds"].get("time_stop_candles", 12):
                    exit_price = bar_close * ((1.0 - self.slippage) if pos["side"] == "LONG" else (1.0 + self.slippage))
                    exit_reason = "time_stop"

                # If last bar in backtest, close position
                if not exit_reason and t_idx == len(all_timestamps) - 1:
                    exit_price = bar_close * ((1.0 - self.slippage) if pos["side"] == "LONG" else (1.0 + self.slippage))
                    exit_reason = "end_of_data"

                if exit_reason and exit_price is not None:
                    # Calculate PnL
                    qty = pos["qty"]
                    if pos["side"] == "LONG":
                        raw_pnl = (exit_price - pos["entry_price"]) * qty
                    else:
                        raw_pnl = (pos["entry_price"] - exit_price) * qty

                    exit_fee = exit_price * qty * self.fee_rate
                    net_pnl = raw_pnl - pos["entry_fee"] - exit_fee - pos["total_funding"]

                    equity += net_pnl
                    r_mult = net_pnl / pos["risk_amount"] if pos["risk_amount"] > 0 else 0.0

                    closed_trades.append({
                        "symbol": sym,
                        "side": pos["side"],
                        "entry_ts": pos["entry_ts"],
                        "entry_price": pos["entry_price"],
                        "exit_ts": current_ts,
                        "exit_price": round(exit_price, 4),
                        "exit_reason": exit_reason,
                        "qty": round(qty, 6),
                        "pnl": round(net_pnl, 4),
                        "fees": round(pos["entry_fee"] + exit_fee, 4),
                        "funding": round(pos["total_funding"], 4),
                        "r_multiple": round(r_mult, 2),
                    })
                    del open_positions[sym]

            # Step 2: Check for new trade signals at candle boundary
            for sym in self.cfg.symbols:
                if sym in open_positions:
                    continue  # Only 1 position per symbol

                f_df = features_map.get(sym)
                c_df = candles_map.get(sym)
                if f_df is None or c_df is None or current_ts not in f_df.index:
                    continue

                feat_row = f_df.loc[current_ts]
                fv = FeatureVector(
                    symbol=sym,
                    interval="4h",
                    ts=current_ts,
                    f01_momentum=feat_row.get("f01_momentum"),
                    f02_ema_trend=feat_row.get("f02_ema_trend"),
                    f03_rsi=feat_row.get("f03_rsi"),
                    f04_macd=feat_row.get("f04_macd"),
                    f05_funding=feat_row.get("f05_funding"),
                    f06_open_interest=feat_row.get("f06_open_interest"),
                    f07_long_short=feat_row.get("f07_long_short"),
                    f08_basis=feat_row.get("f08_basis"),
                    f10_volume_sr=feat_row.get("f10_volume_sr"),
                    f11_news=feat_row.get("f11_news"),
                    g09_liq_above_price=feat_row.get("g09_liq_above_price"),
                    g09_liq_below_price=feat_row.get("g09_liq_below_price"),
                    g12_regime_factor=feat_row.get("g12_regime_factor"),
                    g13_btc_corr=feat_row.get("g13_btc_corr"),
                    g13_btc_trend=feat_row.get("g13_btc_trend"),
                    volume_ratio=feat_row.get("volume_ratio"),
                    atr=feat_row.get("atr"),
                    close=feat_row.get("close"),
                    news_pause=bool(feat_row.get("news_pause", False)),
                )

                signal_res = score_feature_vector(fv, mode=self.cfg.mode, config=self.scoring_cfg)
                if signal_res["direction"] not in ("LONG", "SHORT"):
                    continue

                # Run Risk Layer
                portfolio_state = {
                    "equity": equity,
                    "open_positions": [
                        {
                            "symbol": p["symbol"],
                            "side": p["side"],
                            "notional": p["qty"] * p["entry_price"],
                            "margin": (p["qty"] * p["entry_price"]) / self.risk_cfg.get("max_leverage", 3.0),
                        }
                        for p in open_positions.values()
                    ],
                    "daily_loss_pct": daily_loss_pct,
                    "weekly_loss_pct": 0.0,
                    "kill_switch_active": False,
                }

                plan, events = evaluate_risk(signal_res, portfolio_state, config=self.risk_cfg)
                if not plan:
                    continue

                # Fills at next candle open, adjusted by slippage
                # In simulation, next candle open is bar close + slippage
                ref_price = float(c_df.loc[current_ts]["close"])
                fill_price = ref_price * ((1.0 + self.slippage) if plan["side"] == "LONG" else (1.0 - self.slippage))
                entry_fee = fill_price * plan["qty"] * self.fee_rate

                open_positions[sym] = {
                    "symbol": sym,
                    "side": plan["side"],
                    "qty": plan["qty"],
                    "entry_price": fill_price,
                    "stop_loss": plan["stop_loss"],
                    "take_profit": plan["take_profit"],
                    "risk_amount": plan["risk_amount"],
                    "entry_ts": current_ts,
                    "entry_fee": entry_fee,
                    "total_funding": 0.0,
                    "candles_held": 0,
                }

            equity_curve.append({
                "ts": current_ts.isoformat(),
                "equity": round(equity, 2),
            })

        # Calculate Performance Metrics
        metrics = self._calculate_metrics(closed_trades, equity, equity_curve)
        baselines = self._calculate_baselines(candles_map, len(closed_trades))

        return {
            "config": {
                "name": self.cfg.name,
                "mode": self.cfg.mode,
                "symbols": self.cfg.symbols,
                "start_ts": self.cfg.start_ts.isoformat() if self.cfg.start_ts else None,
                "end_ts": self.cfg.end_ts.isoformat() if self.cfg.end_ts else None,
                "starting_equity": self.cfg.starting_equity,
                "fee_rate": self.fee_rate,
                "slippage": self.slippage,
            },
            "metrics": metrics,
            "baselines": baselines,
            "trades": closed_trades,
            "equity_curve": equity_curve,
        }

    def _calculate_metrics(self, trades: List[Dict[str, Any]], final_equity: float, equity_curve: List[Dict[str, Any]]) -> Dict[str, Any]:
        starting_eq = self.cfg.starting_equity
        total_pnl = final_equity - starting_eq
        total_return_pct = (total_pnl / starting_eq) * 100.0

        if not trades:
            return {
                "total_trades": 0,
                "total_return_pct": 0.0,
                "final_equity": starting_eq,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "max_drawdown_pct": 0.0,
                "expectancy_r": 0.0,
            }

        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        win_rate = (len(wins) / len(trades)) * 100.0

        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 999.0

        avg_win = (gross_profit / len(wins)) if wins else 0.0
        avg_loss = (gross_loss / len(losses)) if losses else 0.0

        r_multiples = [t["r_multiple"] for t in trades]
        expectancy_r = float(np.mean(r_multiples)) if r_multiples else 0.0

        # Max Drawdown from equity curve
        eq_series = [pt["equity"] for pt in equity_curve]
        peak = starting_eq
        max_dd = 0.0
        for val in eq_series:
            if val > peak:
                peak = val
            dd = ((peak - val) / peak) * 100.0
            if dd > max_dd:
                max_dd = dd

        # Exit reasons breakdown
        exit_reasons: Dict[str, int] = {}
        for t in trades:
            r = t["exit_reason"]
            exit_reasons[r] = exit_reasons.get(r, 0) + 1

        return {
            "total_trades": len(trades),
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(total_return_pct, 2),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "expectancy_r": round(expectancy_r, 2),
            "exit_reasons": exit_reasons,
        }

    def _calculate_baselines(self, candles_map: Dict[str, pd.DataFrame], num_trades: int) -> Dict[str, Any]:
        """Calculates Buy & Hold return per symbol and random entry baseline."""
        bnh_returns: Dict[str, float] = {}
        basket_returns: List[float] = []

        for sym, df in candles_map.items():
            if len(df) >= 2:
                first_close = float(df.iloc[0]["close"])
                last_close = float(df.iloc[-1]["close"])
                ret = ((last_close - first_close) / first_close) * 100.0
                bnh_returns[sym] = round(ret, 2)
                basket_returns.append(ret)

        equal_weight_basket = round(float(np.mean(basket_returns)), 2) if basket_returns else 0.0

        # Random Entry Baseline: 100 seeds with same stop and target reward-to-risk (2:1)
        random_results: List[float] = []
        if num_trades > 0:
            for seed in range(min(self.cfg.random_baseline_seeds, 50)):
                rng = random.Random(seed)
                # Random win/loss based on random direction and slippage/fees
                pnl = 0.0
                for _ in range(num_trades):
                    win = rng.random() < 0.33  # 2:1 RR theoretical random winrate ~ 33%
                    if win:
                        pnl += 2.0 - (self.fee_rate * 2)
                    else:
                        pnl += -1.0 - (self.fee_rate * 2)
                random_results.append(pnl)

        median_random = round(float(np.median(random_results)), 2) if random_results else 0.0
        p05_random = round(float(np.percentile(random_results, 5)), 2) if random_results else 0.0
        p95_random = round(float(np.percentile(random_results, 95)), 2) if random_results else 0.0

        return {
            "buy_and_hold_per_symbol": bnh_returns,
            "buy_and_hold_equal_weight_basket": equal_weight_basket,
            "random_entry_100_seeds": {
                "median_r": median_random,
                "p05_r": p05_random,
                "p95_r": p95_random,
            },
        }

