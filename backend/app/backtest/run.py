"""
run.py - Backtest CLI and report generator (Stage 15).
Usage:
  python -m app.backtest.run --mode reduced --name "Full History Reduced Run"
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session

from app.backtest.engine import BacktestConfig, Backtester
from app.db.models_trading import BacktestRun, BacktestTrade
from app.db.session import SessionLocal


def run_and_save_backtest(cfg: BacktestConfig, session: Session) -> int:
    """Executes backtest, writes BacktestRun & BacktestTrade rows, and creates markdown report."""
    tester = Backtester(session, cfg)
    results = tester.run()

    # Save to backtest_runs
    report_dir = Path(__file__).parent.parent.parent.parent / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    run_row = BacktestRun(
        name=cfg.name,
        mode=cfg.mode,
        params=results["config"],
        symbols=cfg.symbols,
        start_ts=cfg.start_ts or datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_ts=cfg.end_ts or datetime.now(timezone.utc),
        metrics=results["metrics"],
    )
    session.add(run_row)
    session.commit()
    session.refresh(run_row)

    report_path = report_dir / f"backtest_{run_row.id}.md"
    run_row.report_path = str(report_path)

    # Save trades
    for t in results["trades"]:
        tr = BacktestTrade(
            run_id=run_row.id,
            symbol=t["symbol"],
            side=t["side"],
            entry_ts=t["entry_ts"],
            entry_price=t["entry_price"],
            exit_ts=t["exit_ts"],
            exit_price=t["exit_price"],
            exit_reason=t["exit_reason"],
            qty=t["qty"],
            pnl=t["pnl"],
            fees=t["fees"],
            funding=t["funding"],
            r_multiple=t["r_multiple"],
        )
        session.add(tr)
    session.commit()

    # Generate Markdown Report
    m = results["metrics"]
    b = results["baselines"]
    md = f"""# TradeSphere Pro Backtest Report: {cfg.name} (Run #{run_row.id})

- **Date:** {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
- **Mode:** `{cfg.mode}`
- **Symbols:** {", ".join(cfg.symbols)}
- **Starting Equity:** ${cfg.starting_equity:,.2f}
- **Fee Rate:** {cfg.fee_rate * 100:.3f}% (double fees: {cfg.double_fees})
- **Slippage:** {cfg.slippage_rate * 100:.3f}%
- **Volume Gate:** {cfg.volume_gate_enabled}

---

## Performance Summary

| Metric | Value |
|---|---|
| **Total Return** | **{m.get('total_return_pct', 0.0):+.2f}%** |
| **Final Equity** | ${m.get('final_equity', 0.0):,.2f} |
| **Total Closed Trades** | {m.get('total_trades', 0)} |
| **Win Rate** | {m.get('win_rate', 0.0):.1f}% |
| **Profit Factor** | {m.get('profit_factor', 0.0):.2f} |
| **Max Drawdown** | {m.get('max_drawdown_pct', 0.0):.2f}% |
| **Average Win** | ${m.get('avg_win', 0.0):,.2f} |
| **Average Loss** | ${m.get('avg_loss', 0.0):,.2f} |
| **Expectancy** | {m.get('expectancy_r', 0.0):+.2f} R |

### Exit Reasons Breakdown
```json
{json.dumps(m.get('exit_reasons', {}), indent=2)}
```

---

## Baseline Comparison

### 1. Buy & Hold Benchmark
- **Equal-Weight Basket Return:** **{b.get('buy_and_hold_equal_weight_basket', 0.0):+.2f}%**
- **Per Symbol Return:**
```json
{json.dumps(b.get('buy_and_hold_per_symbol', {}), indent=2)}
```

### 2. Random Entry Baseline (100 Seeds, 2:1 RR)
- **Median Return:** {b.get('random_entry_100_seeds', {}).get('median_r', 0.0):+.2f} R
- **5th Percentile:** {b.get('random_entry_100_seeds', {}).get('p05_r', 0.0):+.2f} R
- **95th Percentile:** {b.get('random_entry_100_seeds', {}).get('p95_r', 0.0):+.2f} R

---

## Limitations & Audit Notes
1. **Pessimistic Stop-First Execution:** If both Stop-Loss and Take-Profit price levels were breached within the same 4h candle, the simulator always assumed the stop was hit first.
2. **Missing Older Derivatives:** In `reduced` mode, missing open interest and long/short metrics from older history are renormalized to 100% across available technicals and funding.
3. **Execution Realities:** Slippage of 0.02% and taker fee of 0.05% applied to every fill.
"""
    report_path.write_text(md, encoding="utf-8")
    print(f"Backtest completed successfully. Report written to: {report_path}")
    return run_row.id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run TradeSphere Pro Backtest")
    parser.add_argument("--mode", default="reduced", choices=["full", "reduced"])
    parser.add_argument("--name", default="Backtest Run")
    parser.add_argument("--volume-gate-off", action="store_true")
    parser.add_argument("--double-fees", action="store_true")
    args = parser.parse_args()

    bcfg = BacktestConfig(
        name=args.name,
        mode=args.mode,
        volume_gate_enabled=not args.volume_gate_off,
        double_fees=args.double_fees,
    )
    with SessionLocal() as db:
        run_id = run_and_save_backtest(bcfg, db)
        print(f"Run ID: {run_id}")

