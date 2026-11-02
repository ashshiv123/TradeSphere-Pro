# TradeSphere Pro: Build Plan

Prepared 2 November 2026 | Rebuilt from AI Trading Copilot Blueprint v2 | Scope matches the resume entry

## 1. Goal and scope

This plan turns the blueprint into a project you can finish in about four weeks, starting today. The scope is fixed by the three resume bullets, so every claim on the resume is true when the plan is done:

- **Data pipeline:** a multi-source pipeline using exchange REST and WebSocket APIs plus news and sentiment sources, computing 13 technical, derivatives, liquidity and sentiment features per coin.
- **Scoring engine:** weighted scoring that produces buy, sell or hold signals, with volatility and Bitcoin-correlation filters. An LLM API explains each signal and never controls the decision.
- **Risk and records:** risk controls for position sizing, stop-loss, leverage and daily drawdown, plus backtesting and PostgreSQL trade logging.

Starting universe: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT and XRPUSDT. Main timeframe: 4-hour candles, with daily candles for trend context. Signals are computed after each 4-hour candle closes. This fits the swing horizon in the blueprint and keeps API rate limits and compute small.

## 2. What changes from Blueprint v2

- **Paper-trading engine removed.** Layer 7 is replaced by one Execution Engine that places real orders through the exchange API. Before real money, it runs against the exchange's testnet (a fake-money sandbox run by the exchange). The order code is identical; only the API keys and base URL change. This is a safety step, because a bug in leveraged order code can empty an account in minutes.
- **React with Vite instead of Next.js.** The resume says React.
- **The LLM only explains.** News sentiment is scored without the LLM (CryptoPanic votes, the Fear & Greed Index, and a simple lexicon scorer such as VADER on headlines), so the LLM stays outside the decision path exactly as the resume says.
- **Cut from the first version:** on-chain flow data (Etherscan), FinBERT, options, spot trading, the tax module and the future ML model. All of these can come after the resume version works.
- **Added: a data collector that starts on Day 1.** Exchange history for open interest and long/short ratio only goes back about 30 days, so to backtest all 13 fields later we have to start recording now.
- **One app, not microservices.** One FastAPI app with background workers, one Postgres, one Redis and one React frontend, all in Docker Compose.

## 3. Architecture

Data flow: Exchange and news APIs → Ingestion workers → Postgres (raw data) → Feature engine (13 fields) → Scoring engine → Risk layer → Signal log → LLM explanation and Execution engine → Orders and positions in Postgres → API and WebSocket → React dashboard.

Backend modules (folders under backend/app):

- **ingestion:** REST pollers and WebSocket listeners, one file per source.
- **features:** one function per field, each returning a score from -1 to +1 or a gate factor.
- **scoring:** weights, composite score, thresholds and the signal object.
- **risk:** rule checks loaded from a config file; can veto or resize any signal.
- **execution:** exchange adapter, order lifecycle, reconciliation and kill-switch.
- **llm:** builds the prompt from the signal object, calls the API and stores the text.
- **backtest:** replays stored candles and features through the same scoring and risk code.
- **api:** FastAPI routes and the WebSocket endpoint.
- **db:** SQLAlchemy models and Alembic migrations.

Postgres tables: candles, funding\_rates, open\_interest, long\_short\_ratio, liquidations, news\_items, features, signals, orders, positions, risk\_events, backtest\_runs, equity\_snapshots.

Redis holds the latest features and signals per symbol for fast dashboard reads, a pub/sub channel that pushes updates to the browser over WebSocket, and rate-limit counters for exchange calls.

One rule matters most: the backtester calls the same scoring and risk functions as live mode. Do not write a second copy of the logic.

## 4. The 13 fields: sources and computation

Each field is computed per symbol per 4-hour candle and stored in the features table.

- **1 Momentum:** return over roughly the last 14 days of 4h candles, skipping the most recent 1 to 2 days, converted to a rolling z-score and clipped to -1..+1. Source: candles.
- **2 EMA trend:** 21/55 EMA. +1 when fast is above slow and rising, -1 for the inverse, scaled by the EMA gap divided by ATR. Source: candles.
- **3 RSI with divergence:** RSI(14) mapped so overbought is negative and oversold is positive; divergence adds or subtracts 0.3. Source: candles.
- **4 MACD:** MACD(12,26,9) histogram direction and slope, scaled to -1..+1. Source: candles.
- **5 Funding trend:** slope of the funding rate over the last 3 to 5 days (8-hour data); extreme absolute funding dampens the score. Source: exchange funding-rate endpoint.
- **6 Open interest trend:** price direction against OI direction using the blueprint matrix (price up and OI up +1, price up and OI down +0.3, price down and OI up -1, price down and OI down -0.3). Source: open-interest endpoints.
- **7 Long/short ratio:** retail ratio as a contrarian score near extremes and close to 0 when balanced, compared against the top-trader ratio. Source: exchange long/short ratio endpoints.
- **8 Perp-spot basis:** (perp price - spot price) / spot price, and its 3-day slope. Source: perpetual and spot prices; the mark/index price endpoint is the quickest route.
- **9 Liquidation zones:** collect forced-liquidation events from the exchange liquidation WebSocket stream, bin them by price level and mark clusters. Not scored; used to move stop-loss and entry away from clusters. Fallback if short on time: use recent swing highs and lows as the cluster proxy and say so in the README.
- **10 Volume and support/resistance:** volume against its 20-candle average, plus distance to recent swing highs and lows and Fibonacci levels. Scored from -1 to +1, and also used as a final gate before a signal fires.
- **11 News and event sentiment:** CryptoPanic posts for the coin (votes plus VADER on headlines) with recency decay and an impact multiplier for high-importance items, with the Fear & Greed Index as a market-wide input. A hand-kept list of scheduled events (for example FOMC and CPI dates) sets the news-pause flag.
- **12 Regime filter:** ATR percentile and Bollinger Band width percentile over the last 90 days. Output factor from 0.2 (choppy) to 1.0 (trending). It multiplies position size, not the score.
- **13 BTC correlation and beta:** rolling 30-day correlation and beta of the coin against BTC, plus BTC dominance from CoinGecko's global endpoint. Confidence multiplier of 0.5 to 1.0 when the coin's signal fights BTC's trend at high correlation.

Check exact endpoint names and limits in the Binance futures and Delta Exchange docs on Day 1; they change.

## 5. Scoring engine

Weights (sum to 100%): Momentum 12, EMA trend 12, RSI 10, MACD 10, Funding 9, Open interest 9, Long/short 8, Basis 8, Volume and support/resistance 12, News 10. Liquidation zones, regime and correlation are gates, not votes.

- Composite score CS = sum of (weight x score) over those 10 fields, between -1 and +1.
- Adjusted confidence = |CS| x RegimeFactor x CorrelationFactor.
- LONG if CS >= +0.35 and confidence >= 0.40. SHORT if CS <= -0.35 and confidence >= 0.40. Otherwise HOLD. Always HOLD inside a news-pause window.
- Position size = min(leverage cap, base risk unit x adjusted confidence), where the base risk unit comes from the risk-per-trade rule and the distance to the stop-loss.
- A signal object is saved on every run, including HOLD: symbol, time, direction, CS, confidence, all 13 field values, entry, stop-loss, take-profit, leverage, size and reason tags.

Your first unit test should reproduce the blueprint's worked example (CS = +0.47, regime factor 0.9, confidence 0.42, result LONG). It is a free, written-down test case. Then add tests for HOLD, SHORT and the news-pause override.

Treat all weights and thresholds as starting values to test, not tuned results.

## 6. Risk layer

Rules live in one config file so they are visible and auditable. Suggested starting values:

- **Risk per trade:** 1% of equity, never above 2%.
- **Leverage cap:** 3x, whatever the exchange offers.
- **Mandatory stop-loss:** no order is sent without one, and the stop sits outside the nearest liquidation cluster.
- **Exposure:** at most 3 open positions and 30% of equity in total.
- **Daily drawdown limit:** 3% of equity. At the limit, the kill-switch blocks new entries until you reset it manually. Weekly limit 6%.
- **News pause:** no new entries from 30 minutes before to 60 minutes after scheduled high-impact events.
- **Regime scaling:** size multiplied by the regime factor, and zero in extreme chop.
- **Correlation check:** apply the Field 13 multiplier.
- **Audit trail:** every veto or resize writes a row to risk\_events with the rule name and reason.

The risk layer is plain Python with unit tests, never an LLM call.

## 7. Execution engine and going live

- **Exchange adapter:** built on ccxt (which supports Binance and Delta Exchange) or the exchange's own SDK. Market data from Binance, orders on Delta Exchange India as in the blueprint, if its API covers your symbols. Confirm this on Day 1.
- **Order lifecycle:** place the entry, attach stop-loss and take-profit, track fills, update the positions table, and reconcile against the exchange every few minutes. If the app and the exchange disagree, the exchange wins and a risk event is logged.
- **Modes:** an environment variable selects TESTNET or LIVE. Start with manual approval (the signal appears in the dashboard and you click approve). Switch to automatic only after the checklist below.
- **API key safety:** keys only in .env, never committed; trade permission on, withdrawal permission off; IP whitelist if the exchange supports it.

Go-live checklist before any real money:

- All risk rules have passing unit tests, and the kill-switch has been triggered on purpose on testnet.
- At least 7 days on testnet with no unreconciled positions and no order errors.
- Backtest results reviewed across more than one market period, including a choppy one.
- Starting capital is an amount you can afford to lose completely, at the smallest size the exchange allows.

Be realistic about outcomes: no strategy guarantees profit, and leveraged futures can lose money fast. The goal of this build is a correct, safe, auditable system. Whether it is profitable is something backtests and live results will show, and the resume should only state results you actually measured.

## 8. Backtesting

- Replay stored candles and features through the same scoring and risk code, filling at the next candle open, with fee (for example 0.05% per side) and slippage assumptions in config.
- Price-derived fields (1 to 4, 10, 12, 13) can be backtested over 1 to 2 years. Fields 5 to 8 are limited by exchange history (about 30 days for open interest and long/short ratio), so extend them with your own recorded data and report which window each test used.
- Metrics: total return, max drawdown, win rate, profit factor, number of trades and a Sharpe-style ratio. Save each run in backtest\_runs.
- Do not tune weights until they look good on one period. Compare one fixed weight set across periods and report the results honestly.

## 9. Dashboard and API

Frontend pages (React with Vite, TradingView Lightweight Charts):

- **Market overview:** price chart per symbol with signal markers.
- **Signal detail:** the 13 field scores with their contribution to CS, the gates, and the LLM explanation.
- **Risk and positions:** open positions, exposure, today's drawdown and kill-switch status.
- **Trade log and backtests:** tables and an equity curve.

Main API routes: GET /signals, GET /signals/{id}, GET /features/{symbol}, GET /positions, POST /signals/{id}/approve, POST /killswitch/reset, GET /backtests, POST /backtests/run, and WS /stream.

## 10. Build schedule (4 weeks)

**Week 1: data and features (2 to 8 Nov)**

- **Day 1 (today):** create the repo, Docker Compose with Postgres and Redis, a FastAPI skeleton, and the DB models and migration. Write the collectors for candles, funding, open interest, long/short ratio and mark/index price, and start them running so history builds up. Push to GitHub.
- **Day 2:** backfill 1 to 2 years of 4h and daily candles. Build Fields 1 to 4 with unit tests.
- **Day 3:** Fields 10, 12 and 13 (volume and support/resistance, regime, BTC correlation and dominance).
- **Day 4:** Fields 5 to 8 from the collected derivatives data.
- **Day 5:** Field 11 (CryptoPanic, Fear & Greed, VADER, event calendar) and Field 9 (liquidation stream and clusters).
- **Days 6 to 7:** normalization, scoring engine, signal object and tests including the blueprint example. Run end to end on all 5 symbols and store the signals.

**Week 2: risk, backtest and dashboard (9 to 15 Nov)**

- **Days 8 to 9:** risk layer and risk\_events, with full unit tests.
- **Days 10 to 11:** backtester and first runs, with metrics saved.
- **Days 12 to 14:** API routes, Redis pub/sub, WebSocket, and the first React pages (market overview and signal detail).

**Week 3: LLM and execution (16 to 22 Nov)**

- **Days 15 to 16:** LLM explanation layer. The structured signal object goes in, a short explanation comes out and is stored with the signal. If the API fails, show the signal without text.
- **Days 17 to 20:** execution engine on testnet with stop-loss and take-profit orders, fill tracking, reconciliation, kill-switch and the manual approval flow.
- **Day 21:** risk and positions page, and the trade log page.

**Week 4: validate and present (23 to 29 Nov)**

- **Days 22 to 24:** backtests across periods, fix the bugs they reveal, and keep the testnet run going.
- **Days 25 to 26:** README with architecture diagram, setup steps, screenshots, backtest table and limitations. One-command start with Docker Compose.
- **Day 27:** update the resume with only what is built and measured (see section 12).
- **Day 28:** go-live checklist review, then an optional smallest-size live pilot with manual approval.

**If you have only 10 days:** compress Week 1 into 4 days, then do scoring, risk, backtester, a minimal dashboard and testnet execution. Leave the live pilot, Field 9 clusters (use swing levels) and dashboard polish for later.

## 11. Today's checklist (first 3 to 4 hours)

- Create the repo structure above and commit it.
- Get Docker Compose running with Postgres and Redis, and a FastAPI health route working.
- Create the exchange testnet account and API keys, a CryptoPanic API key and an LLM API key. Put them in .env and add .env to .gitignore.
- Read the endpoint docs for candles, funding rate, open interest history, long/short ratio, mark/index price and the liquidation stream, and confirm they respond from your network.
- Write the first collector (candles for 5 symbols) and see rows land in Postgres.
- Start the derivatives collectors in the background before you finish for the day.

## 12. Keeping the resume true

The current wording is accurate for work in progress. Update it as you finish:

- Remove (In Progress) only when Weeks 1 to 3 are done and the repo runs from the README.
- After backtests, add real numbers: symbols covered, test period, number of trades and max drawdown, for example: Backtested over X months on 5 symbols with Y% max drawdown.
- Mention automated order execution only once the execution engine works. Say testnet if that is where it ran, and say live only after a real-money run.
- Commit regularly and keep the repo public with a clear README, because recruiters open the link.

## 13. Cut order if time runs short

- 1. Live pilot with real money (not needed for the resume).
- 2. Field 9 liquidation clusters (replace with the swing-level proxy and say so).
- 3. Dashboard polish and extra pages.
- 4. LLM explanation (use simple template text and add the LLM last).

Do not cut: scoring tests, risk-layer tests, the backtester and trade logging. These are what the resume claims.

## 14. Notes

- India tax treatment of crypto derivatives is unsettled as of mid-2026 per the blueprint. Get a CA's written opinion before live trading.
- This is an engineering plan, not financial advice.
