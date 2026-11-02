# TradeSphere Pro: Decision Layer Plan

**Scoring → Risk → Signal and trade logs → Backtest → LLM explanation → Dashboard → Testnet execution**

Prepared 2 November 2026. Save as `docs/DECISION_LAYER_PLAN.md`. This continues `docs/DATA_PIPELINE_PLAN.md` (Stages 0 to 9 are done). Stage numbers here continue from there (11 to 19). Stage 10 (server deployment) remains optional and can run in parallel.

---

## 0. How to use this file

- The agent reads this file and `docs/DATA_PIPELINE_PLAN.md` fully, then works through the stages in Section 11.
- The same working agreement as the data plan applies: explain every stage in plain language, small commits, tests for everything, update `PROGRESS.md`, never invent facts, record differences in "Deviations" at the end.
- Anything the agent cannot do itself is a **MANUAL STEP**. The agent stops with a block starting `MANUAL STEP NEEDED:` and waits.
- **No real-money trading code in this phase.** The execution engine (Stage 18) talks to an exchange **testnet** only. Going live is a separate, human decision (Section 13).

---

## 1. Goal and scope

**Goal:** turn the stored `features` rows into trade decisions that are explainable, risk-checked, logged and testable on history, then (on testnet) executed with strict safety rules.

**What the three resume bullets need from this phase**
1. Weighted scoring engine that outputs buy, sell or hold with volatility and Bitcoin-correlation filters, and an LLM that explains signals without controlling trades (Stages 12, 16).
2. Risk controls for position sizing, stop-loss, leverage and daily drawdown (Stage 13).
3. Backtesting and PostgreSQL-based trade logging (Stages 14, 15).

**Principles**
- One decision code path: the live signal job and the backtester call the **same** scoring and risk functions.
- Everything is logged, including HOLD decisions and every risk veto.
- The LLM never touches the decision. Its output is stored text only.
- No profit is promised anywhere. Results are reported only as measured, with baselines.

---

## 2. New database tables (Alembic migration)

```sql
CREATE TABLE signals (
  id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL, interval TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL,   -- candle close time
  direction TEXT NOT NULL,                   -- 'LONG' | 'SHORT' | 'HOLD'
  hold_reason TEXT,                          -- below_threshold | low_confidence | news_pause | volume_gate | missing_fields | sl_too_wide
  composite_score REAL, regime_factor REAL, corr_factor REAL, confidence REAL,
  entry_price NUMERIC(24,8), stop_loss NUMERIC(24,8), take_profit NUMERIC(24,8),
  sl_distance_atr REAL, rr REAL, size_multiplier REAL,
  contributions JSONB,                       -- per field: weight, score, weighted contribution
  features_snapshot JSONB,                   -- the FeatureVector used
  config_version TEXT NOT NULL,              -- hash of scoring + risk config
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (symbol, interval, ts)
);

CREATE TABLE signal_explanations (
  signal_id BIGINT PRIMARY KEY REFERENCES signals(id),
  provider TEXT, model TEXT, text JSONB, error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE trade_plans (                   -- risk-approved proposal built from a signal
  id BIGSERIAL PRIMARY KEY,
  signal_id BIGINT NOT NULL REFERENCES signals(id),
  symbol TEXT NOT NULL, side TEXT NOT NULL,  -- 'LONG' | 'SHORT'
  qty NUMERIC(30,8) NOT NULL, entry_price NUMERIC(24,8) NOT NULL,
  stop_loss NUMERIC(24,8) NOT NULL, take_profit NUMERIC(24,8) NOT NULL,
  leverage REAL NOT NULL, risk_amount NUMERIC(24,8) NOT NULL,
  status TEXT NOT NULL,                      -- proposed | approved | rejected | sent | filled | closed | cancelled | failed
  approved_by TEXT,                          -- 'manual' | 'auto'
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE risk_events (
  id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  symbol TEXT, signal_id BIGINT, plan_id BIGINT,
  rule TEXT NOT NULL,                        -- e.g. max_positions, daily_drawdown, leverage_cap
  action TEXT NOT NULL,                      -- veto | resize | kill_switch | critical | info
  details JSONB
);

CREATE TABLE kill_switch_state (
  id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  active BOOLEAN NOT NULL DEFAULT FALSE, reason TEXT,
  triggered_at TIMESTAMPTZ, reset_at TIMESTAMPTZ
);

CREATE TABLE orders (
  id BIGSERIAL PRIMARY KEY, plan_id BIGINT NOT NULL REFERENCES trade_plans(id),
  client_order_id TEXT NOT NULL UNIQUE, exchange_order_id TEXT,
  type TEXT NOT NULL,                        -- entry | stop | take_profit | exit
  side TEXT NOT NULL, qty NUMERIC(30,8) NOT NULL, price NUMERIC(24,8),
  status TEXT NOT NULL, filled_qty NUMERIC(30,8) DEFAULT 0,
  avg_fill_price NUMERIC(24,8), fee NUMERIC(24,8) DEFAULT 0, raw JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE positions (
  id BIGSERIAL PRIMARY KEY, plan_id BIGINT NOT NULL REFERENCES trade_plans(id),
  symbol TEXT NOT NULL, side TEXT NOT NULL, qty NUMERIC(30,8) NOT NULL,
  entry_price NUMERIC(24,8) NOT NULL, stop_loss NUMERIC(24,8), take_profit NUMERIC(24,8),
  opened_at TIMESTAMPTZ NOT NULL, closed_at TIMESTAMPTZ,
  exit_price NUMERIC(24,8), pnl NUMERIC(24,8), fees NUMERIC(24,8), funding NUMERIC(24,8),
  exit_reason TEXT, status TEXT NOT NULL     -- open | closed
);

CREATE TABLE equity_snapshots (
  ts TIMESTAMPTZ PRIMARY KEY, equity NUMERIC(24,8) NOT NULL,
  balance NUMERIC(24,8), unrealised_pnl NUMERIC(24,8), source TEXT   -- 'exchange' | 'backtest'
);

CREATE TABLE backtest_runs (
  id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL,
  mode TEXT NOT NULL,                        -- 'full' | 'reduced'
  params JSONB NOT NULL, symbols TEXT[] NOT NULL,
  start_ts TIMESTAMPTZ NOT NULL, end_ts TIMESTAMPTZ NOT NULL,
  metrics JSONB, report_path TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE backtest_trades (
  id BIGSERIAL PRIMARY KEY, run_id BIGINT NOT NULL REFERENCES backtest_runs(id),
  symbol TEXT NOT NULL, side TEXT NOT NULL,
  entry_ts TIMESTAMPTZ NOT NULL, entry_price NUMERIC(24,8) NOT NULL,
  exit_ts TIMESTAMPTZ, exit_price NUMERIC(24,8),
  exit_reason TEXT,                          -- stop_loss | take_profit | time_stop | end_of_data
  qty NUMERIC(30,8) NOT NULL, pnl NUMERIC(24,8), fees NUMERIC(24,8), funding NUMERIC(24,8),
  r_multiple REAL
);
```

---

## 3. Scoring engine specification

**Location:** `backend/app/scoring/`. Pure functions, no database calls inside the core logic (the caller passes a `FeatureVector`). Settings in `scoring_config.yaml`.

**Weights (percent, sum 100):**

| Field | Weight |
|-------|--------|
| F1 Momentum | 12 |
| F2 EMA trend | 12 |
| F3 RSI | 10 |
| F4 MACD | 10 |
| F5 Funding | 9 |
| F6 Open interest | 9 |
| F7 Long/short | 8 |
| F8 Basis | 8 |
| F10 Volume + S/R | 12 |
| F11 News | 10 |

**Composite score:** `CS = Σ (weight_i / 100) × score_i`, in -1 to +1.

**Missing fields (important):**
- **Full mode (live and recent backtests):** a NULL field contributes 0 (no renormalizing). If **more than 2** of the 10 scored fields are NULL, the decision is HOLD with `hold_reason = missing_fields`.
- **Reduced mode (long-history backtests only):** old history has no F6, F7 and probably no F11. Reduced mode ignores NULL fields and **renormalizes the remaining weights to 100%**. It never runs live. Every report states the mode and which fields were used.

**Decision rules (applied in this order, first failure gives HOLD with the reason):**
1. Missing fields rule (full mode).
2. `news_pause` is true.
3. Direction: LONG if `CS >= +0.35`, SHORT if `CS <= -0.35`, else HOLD (`below_threshold`).
4. `confidence = abs(CS) × regime_factor × corr_factor` must be `>= 0.40` (`low_confidence`).
5. Volume gate: `volume_ratio >= 1.2` (`volume_gate`). Configurable; the backtester must also run with the gate off so its effect is measured.
6. Stop-loss and take-profit computed (below). If the stop is too wide: HOLD (`sl_too_wide`).

**Correlation factor:** `corr_factor = 1.0 - 0.5 × clip((corr - 0.7) / 0.3, 0, 1)` if `corr >= 0.7` and the signal direction opposes `g13_btc_trend`; otherwise 1.0. BTCUSDT itself always 1.0.

**Entry, stop-loss, take-profit (all from the candle close and ATR14):**
- Entry reference = candle close (backtest fills at the next candle open; live uses the market price at execution).
- Stop distance = `1.5 × ATR14`.
- If a liquidation cluster (F9) lies between entry and the stop on the adverse side, move the stop beyond the cluster by `0.25 × ATR14`. If the resulting distance is more than `3 × ATR14`, HOLD (`sl_too_wide`).
- Take-profit = entry ± `2 × stop distance` (reward-to-risk 2:1, configurable).
- Time stop: close after 12 candles (2 days) if neither level is hit (configurable).

**Size multiplier (passed to the risk layer):** `size_multiplier = clip(confidence / 0.6, 0.4, 1.0)`.

**Signal object:** the row in `signals` (Section 2) including `contributions` showing weight, score and weighted contribution for every field. This is what the dashboard and the LLM explanation read.

**Required tests**
- The blueprint's worked example at the decision-rule level: composite score +0.47 with regime factor 0.9 and corr factor 1.0 gives confidence about 0.42 and direction LONG.
- HOLD for each `hold_reason`, one test per reason; SHORT mirror of LONG.
- NULL handling in full and reduced modes; renormalization sums to 100%.
- Stop-loss adjustment around a liquidation cluster, and the `sl_too_wide` case.
- Determinism: the same input and config always give the same signal.

---

## 4. Risk layer specification

**Location:** `backend/app/risk/`. Plain Python functions plus database state. Rules in `risk.yaml` (suggested starting values). **Never an LLM call.**

```yaml
risk_per_trade_pct: 1.0        # percent of equity risked if the stop is hit (hard max 2.0)
max_leverage: 3.0              # cap on notional / equity per position
max_open_positions: 3
max_total_exposure_pct: 30.0   # total margin used (notional / leverage) as percent of equity, see note below
max_positions_per_symbol: 1
daily_drawdown_pct: 3.0        # kill-switch trigger (UTC day, measured from start-of-day equity)
weekly_drawdown_pct: 6.0
min_stop_distance_pct: 0.3     # reject absurdly tight stops
max_same_direction_correlated: 2   # coins with corr >= 0.8 to each other in the same direction
cooldown_candles_after_loss: 3
```

Note on exposure: define it as total **margin used** (notional / leverage) as a percent of equity, so the 30% limit is meaningful. Document the exact definition in code.

**Sizing:** `risk_amount = equity × risk_per_trade_pct × size_multiplier`; `qty = risk_amount / stop_distance`; `notional = qty × entry`; if `notional / equity > max_leverage`, reduce `qty` (action `resize`).

**Checks (each veto or resize writes a `risk_events` row with the rule name and numbers):**
1. Stop-loss and take-profit present and on the correct side of entry.
2. Kill-switch not active.
3. Daily and weekly drawdown limits not breached. Breach sets `kill_switch_state.active = TRUE` and logs `kill_switch`.
4. Max open positions, one position per symbol, total exposure.
5. Leverage cap (resize), minimum stop distance.
6. Correlated same-direction exposure limit.
7. Cooldown after a losing trade on the same symbol.

**Kill-switch behaviour:** blocks all new entries until reset by `POST /killswitch/reset` (manual). Open positions keep their exchange stop-loss orders; closing them is a manual decision unless configured otherwise.

**Output:** a `trade_plans` row with status `proposed` (or no plan plus the logged veto).

**Required tests:** one test per rule (pass and fail case), sizing math with known numbers, drawdown trigger and manual reset, resize logic, and a test that no plan is ever produced without a valid stop-loss.

---

## 5. Signal job and logs

- A worker job listens for `features:updated` (or runs after the feature job) and, for each symbol: loads the latest `FeatureVector`, runs scoring, saves the `signals` row (including HOLD), then, for LONG or SHORT, runs the risk layer and saves a `trade_plans` row.
- Idempotent: `UNIQUE (symbol, interval, ts)` on `signals`; re-running does not duplicate.
- Equity for sizing: from the latest `equity_snapshots` row (exchange balance on testnet). Until Stage 18, use a configured starting equity in `risk.yaml` clearly marked as a placeholder.
- Every decision stores `config_version` (hash of both YAML files) so past results can be reproduced.

---

## 6. Backtester specification

**Location:** `backend/app/backtest/`. Replays rows from `features` and `candles` through the **same** scoring and risk functions. A CLI: `python -m app.backtest.run --mode full|reduced --symbols ... --start ... --end ... --name ...`.

**Simulation rules**
- Signal at candle `t` close fills at candle `t+1` open, adjusted by slippage.
- Fees: 0.05% per side (config). Slippage: 0.02% against you (config).
- Funding: for positions open across a funding time, apply `funding_rate × notional` using the stored `funding_rates` (longs pay when the rate is positive, shorts receive).
- Stops and targets: checked on each later candle's high and low. If both the stop and the target are touched in the same candle, **assume the stop was hit first** (pessimistic).
- Time stop after the configured number of candles; close any open position at the end of data (`end_of_data`).
- Risk layer applies: sizing, leverage cap, max positions, drawdown kill-switch (simulated per day), correlation limits.
- Equity marked to market each candle; starting equity from config.
- No look-ahead: only `features` rows with `ts <= t` and no data from later candles.

**Modes**
- `full`: needs all scored fields (F6 and F7 only exist for roughly the last 30 days plus whatever was collected since). Short window, so report it as indicative only.
- `reduced`: long history (1 to 2 years), renormalized weights over available fields. This is the main test of the price and funding-based part.

**Metrics:** total return, CAGR if the period is long enough, max drawdown, win rate, average win and loss, profit factor, expectancy in R, Sharpe-style ratio on daily equity returns, number of trades, average holding time, exposure percent, trades per symbol, and exit-reason counts.

**Baselines (required in every report):**
- Buy and hold of each symbol and of an equal-weight basket over the same period.
- Random entries: same number of trades, same stop and target rules, 100 random seeds. Report the median and the 5th to 95th percentile of the random results next to the strategy.

**Anti-overfitting protocol**
- Split history by time: **Period A** first 60% (exploration), **Period B** next 20% (validation), **Period C** last 20% (final test, run only once after the config is frozen).
- Change weights or thresholds only by looking at A and B. Never tune on C.
- Report results for A, B and C separately, plus results with the volume gate on and off, and with fees doubled.
- Save every run in `backtest_runs` and `backtest_trades`, and write `reports/backtest_<run_id>.md` (parameters, mode, fields used, metrics, baselines, equity curve data, limitations).

**Required tests:** hand-built tiny scenarios with known outcomes (stop hit, target hit, both in the same candle, time stop, funding payment, fees), reproducibility (same seed and config give identical results), and a no-look-ahead test.

---

## 7. LLM explanation layer

- **Location:** `backend/app/llm/`. Provider-agnostic: `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` in `.env`.
- **Input:** only the stored signal object (direction, composite score, confidence, factors, contributions, entry, stop, target, gates, hold reason). Nothing else, no keys, no account data.
- **Output (JSON, validated):** `summary` (2 to 3 sentences), `supporting_factors` (list), `conflicting_factors` (list), `main_risks` (list). Maximum about 120 words total.
- **Prompt rules:** use only the numbers provided, no price predictions, no instructions to the trader, no financial advice wording.
- Generated for LONG and SHORT signals and on demand for HOLD. Store in `signal_explanations`. Timeouts and failures store an `error` and show a simple template text instead; they **never block** a signal or an order.
- The LLM output is never parsed to make any decision.
- Required tests: with a mocked provider (valid output, invalid JSON, timeout), and a test proving the signal and trade plan are identical with and without the explanation.

---

## 8. API and dashboard

**New routes:** `GET /signals`, `GET /signals/{id}` (with explanation), `GET /plans`, `POST /plans/{id}/approve`, `POST /plans/{id}/reject`, `GET /positions`, `GET /risk/status` (limits, usage, kill-switch), `POST /killswitch/trigger`, `POST /killswitch/reset`, `GET /backtests`, `GET /backtests/{id}`, `GET /equity`, and `WS /stream` (pushes new signals, plan updates, position updates and risk events).

**Dashboard (React with Vite, charts with TradingView Lightweight Charts or Recharts):**
- **Market overview:** candles per symbol with signal markers; latest 13 field values.
- **Signal detail:** composite score breakdown (bar per field), gates, entry/stop/target, LLM explanation, hold reason.
- **Plans and positions:** pending plans with Approve and Reject buttons, open positions with P&L, today's drawdown versus the limit, kill-switch status and reset button.
- **Trade log and backtests:** tables, equity curve, backtest comparison against baselines.
- Keep it simple and readable; correctness matters more than polish.

---

## 9. Execution engine (testnet only in this phase)

**Location:** `backend/app/execution/`.

- **Exchange:** first confirm which exchange testnet is available and works from the owner's network. Options: Delta Exchange India testnet (the blueprint's live target) or Binance futures testnet or demo. Verify docs and a real call, then ask the owner to choose. Use `ccxt` if it supports the chosen testnet, otherwise the official SDK.
- **Mode:** `EXECUTION_MODE=TESTNET` only. The code must **refuse to start in any other mode**. A live adapter is intentionally not written in this phase.
- **Hard caps in code (not config):** maximum leverage 5, maximum notional per order set to a small constant, and no order without a stop-loss.
- **Flow:** plan `approved` (manual via API or dashboard; `AUTO_APPROVE=false` by default) → entry market order with a deterministic `client_order_id` (for example `{signal_id}-{symbol}-entry`) → when filled, place reduce-only stop-loss and take-profit orders → track fills in `orders` and `positions` → on exit, record P&L, fees and funding.
- **Protection rule:** if the stop-loss order cannot be placed after a fill, immediately close the position at market, log a `critical` risk event and activate the kill-switch.
- **Reconciliation:** every 60 seconds compare exchange positions, open orders and balance with the database. The exchange is the source of truth. Any mismatch is logged as a risk event and fixed in the database, and an unknown exchange position triggers the kill-switch.
- **Equity:** write `equity_snapshots` from the exchange balance at least every 5 minutes.
- **Idempotency and restarts:** after a restart, rebuild state from the exchange before doing anything else. Never send a duplicate entry (check `client_order_id`).
- **API key rules (manual):** trade permission on, withdrawal permission off, IP whitelist if available, keys only in `.env`.

**Required tests:** mocked exchange for the full order lifecycle, stop placement failure path, duplicate-order protection, reconciliation mismatch, restart recovery, kill-switch behaviour, and a test that `EXECUTION_MODE=LIVE` is refused.

---

## 10. Quality and monitoring additions

- Extend `scripts/check_pipeline.py` (or add `scripts/check_trading.py`) to report: last signal time per symbol, signals per day, vetoes by rule, open plans, kill-switch status, last reconciliation time, last equity snapshot.
- Alert-style logging at WARNING or ERROR for: stale features (no new row within 4h 15m), reconciliation mismatch, kill-switch triggered, LLM failures, stop-loss placement failure.
- Keep all tests runnable with `python -m pytest tests/ -p no:cacheprovider -v`.

---

## 11. Implementation stages

### Stage 11: Data-layer gate (do not skip)
Prove the data layer is trustworthy before building on it.
- Run `python -m scripts.check_pipeline` and the full test suite; show the output.
- Confirm the test suite includes parser, backfill and collector tests from Stages 3 to 5 (add missing ones).
- Confirm the 4h feature job runs **by itself** at a candle boundary: show `computed_at` versus candle `ts` in the `features` table and the worker logs for the last 2 boundaries.
- Run `recompute_history` for all 5 symbols and show row counts and the first and last `ts` per symbol, plus the share of NULL per field per month (this shows where history is thin).
- Read "Deviations" in the data plan. Explain why F11 mentions Messari instead of CryptoPanic, and record it if missing.
- Independent check: the owner compares RSI(14) and EMA 21/55 for BTCUSDT 4h on TradingView with the pipeline output for one chosen candle. The agent prints that candle's values to compare.
- Confirm the worker has restart-on-reboot behaviour and how long data has been collected without gaps.
- **MANUAL STEP:** the owner does the TradingView comparison and tells the agent the result.
- **Done when:** all of the above is shown and any problems are fixed or explicitly accepted by the owner.

### Stage 12: Scoring engine
Implement Section 3 with `scoring_config.yaml`, the `signals` migration, and all required tests.
**Done when:** tests pass and running the scorer on the latest `features` rows for 5 symbols prints readable signal objects with a per-field breakdown.

### Stage 13: Risk layer
Implement Section 4 with `risk.yaml`, `risk_events`, `kill_switch_state`, `trade_plans` and all required tests.
**Done when:** tests pass, a hand-made scenario shows each veto and resize reason correctly, and the kill-switch triggers and resets as designed.

### Stage 14: Signal job, logging and API basics
Implement Section 5, the read routes for signals, plans, risk status and kill-switch, and the extended check script.
**Done when:** after the next 4h candle closes, `signals` has a row per symbol (including HOLD rows with reasons), eligible signals have `trade_plans`, and the routes return them.

### Stage 15: Backtester
Implement Section 6 including baselines, the A/B/C split and reports. Run: reduced mode on all history, full mode on the recent window, volume gate on and off, fees doubled.
**Done when:** tests pass, runs are reproducible, reports exist in `reports/`, and the agent gives a plain-language summary of the results **including losses, weak spots, the baseline comparison and the limits of the data**. Do not tune weights to make Period C look better.

### Stage 16: LLM explanation layer
Implement Section 7 with mocks first, then a real call.
**MANUAL STEP:** the owner chooses the LLM provider and creates an API key in `.env`.
**Done when:** a real signal shows a stored explanation, and failure modes degrade gracefully.

### Stage 17: Dashboard
Implement Section 8 with the new API routes and `WS /stream`.
**Done when:** the owner can see signals, breakdowns, explanations, plans and risk status in the browser and can approve or reject a plan.

### Stage 18: Testnet execution engine
Implement Section 9 and all tests.
**MANUAL STEP:** the owner creates the exchange testnet account and keys (trade only, no withdrawal) and puts them in `.env`, and chooses the exchange.
**Done when:** on testnet, an approved plan places the entry, stop-loss and take-profit, fills are tracked, the position closes correctly, reconciliation runs, and the kill-switch has been triggered on purpose and reset.

### Stage 19: Validation, docs and go-live readiness report
- Run the system on testnet for at least 7 days with manual approval; keep a log of anything odd.
- Update the README (architecture diagram, how scoring, risk, backtest and execution work, limitations) and write `docs/VALIDATION_REPORT.md` with the backtest results, the testnet run summary, the checklist status (Section 13) and known weaknesses.
- Update the resume text with measured facts (Section 14).
**Done when:** the report exists, all tests pass, and the agent lists open risks honestly.

---

## 12. Manual steps checklist (owner)

- [ ] Complete the TradingView comparison for Stage 11.
- [ ] Decide on the server (Stage 10) or accept gaps while the PC is off; keep the worker running as much as possible.
- [ ] Choose an LLM provider and add the key to `.env` (Stage 16).
- [ ] Create exchange testnet account and keys: trade only, no withdrawal; add to `.env` (Stage 18).
- [ ] Approve terminal commands and push to GitHub when asked.
- [ ] Review each stage explanation and run its verification step once.
- [ ] Read the backtest report yourself; ask the agent to explain anything unclear.

---

## 13. Go-live checklist (human decision, after Stage 19)

Live trading is **not** part of these stages. Consider it only when every item is true:

- [ ] Stage 11 gate passed and data has been collected for a reasonable period with few gaps.
- [ ] All scoring and risk tests pass; the kill-switch has been triggered and reset on testnet on purpose.
- [ ] Backtests on Period C (run once) were reviewed honestly, alongside random and buy-and-hold baselines, with fees doubled.
- [ ] At least 7 days on testnet with no unreconciled positions, no duplicate orders and no unprotected position.
- [ ] You understand every rule the system uses and can explain it in an interview.
- [ ] The amount at risk is money you can afford to lose completely, at the smallest size the exchange allows, with manual approval on, and daily checks.
- [ ] Tax treatment checked with a qualified person (crypto derivatives rules in India are still unsettled).
- [ ] A separate request for a live adapter is made on purpose, with its own review of the code and safety limits.

No strategy guarantees profit and leveraged futures can lose money quickly.

---

## 14. Keeping the resume true

- Say **testnet** wherever execution ran on testnet. Use "live" only after a real-money run.
- Add only measured numbers, for example: backtested over X months on 5 symbols, Y trades, max drawdown Z%, compared against buy-and-hold and random-entry baselines.
- Remove "(In Progress)" only when Stages 12 to 17 are complete and the repo runs from the README.
- Do not write "generates profit". Describe the system and the measured results.

---

## Deviations (the agent fills this in)

_Nothing yet. Record every difference between this plan and reality, with the date and the fix applied._
