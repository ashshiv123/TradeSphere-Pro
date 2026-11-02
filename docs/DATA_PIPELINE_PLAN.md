# TradeSphere Pro: Data Pipeline Plan

**Collect → Transform → Store → Serve to the algorithm**

Prepared 2 November 2026. Put this file at `docs/DATA_PIPELINE_PLAN.md` in the project repo. An AI coding agent and the project owner (a student who wants to understand every step) will both work from it.

---

## 0. How to use this file

- The agent reads this whole file before writing code, then works through the stages in Section 11 in order.
- After each stage the agent writes a short plain-language explanation (what it built, why, how to check it) and updates `PROGRESS.md`.
- Anything the agent cannot do alone (accounts, API keys, installs, server access) is marked **MANUAL STEP**. The agent stops, tells the owner exactly what to do, and waits.
- Facts about API endpoints and response fields below were written from memory. **Stage 1 must verify each one with a real call** and record differences in the "Deviations" section at the bottom of this file.

---

## 1. Goal and scope

**Goal:** collect the data for the 13 predictive fields, clean and reshape it, store it in PostgreSQL, and expose a ready-to-use feature table that the scoring algorithm (built later) can read.

**In scope**
- Collecting raw data from exchange REST and WebSocket APIs and from news and sentiment sources.
- Storing raw data in PostgreSQL with safe, repeatable inserts.
- Transforming raw data into 13 field values per coin per 4-hour candle (the `features` table).
- Data quality checks, monitoring, tests, and running it 24/7 on a server.

**Out of scope for this file** (later phases): the scoring engine, risk layer, order execution, LLM explanations, dashboard, and backtester. Section 9 defines the output contract those parts will use.

**Hard rule for this phase:** no order-placing code, and no exchange keys with trading permission. This phase only reads public market data.

**Starting universe:** BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT
**Main interval:** 4h candles (also collect 1d candles for later context)
**Time standard:** every timestamp stored in UTC (`TIMESTAMPTZ`)

---

## 2. Working agreement for the AI agent

1. Read this file fully first. Do not skip stages or merge them silently.
2. Keep the code simple and readable. The owner is learning; prefer clear names, short functions and comments that explain why.
3. After every stage, tell the owner in 5 to 10 plain-language lines: what was built, why it exists, and how to verify it themselves (a command to run or a table to look at).
4. Never invent an API endpoint or field. Call it once, save the real response to `backend/tests/fixtures/`, and build from that.
5. Never put secrets in code or in git. Use `.env` (listed in `.gitignore`) and keep `.env.example` with empty values.
6. All inserts must be **idempotent** (running the same job twice must not create duplicates). Use `INSERT ... ON CONFLICT`.
7. Write tests for every feature calculation and every parser. A stage is not done until its tests pass.
8. Make small git commits with clear messages after each stage.
9. When blocked, print a block starting with `MANUAL STEP NEEDED:` that lists the exact steps, then stop and wait for the owner.
10. Ask before running anything that installs system software or changes things outside the project folder.
11. If an API behaves differently from this plan, adapt, and add a line to "Deviations" at the end of this file.

---

## 3. Tech stack and project structure

**Stack:** Python 3.11+, FastAPI, SQLAlchemy 2 with Alembic migrations, PostgreSQL 16, Redis 7, `httpx` (REST), `websockets` (WebSocket), `pandas` and `numpy` (calculations), `APScheduler` (scheduled jobs), `pydantic-settings` (config), `vaderSentiment` (headline sentiment), `pytest`. Run everything with Docker Compose.

**Docker Compose services:** `db` (Postgres), `redis`, `api` (FastAPI, read-only endpoints), `worker` (collectors and feature job). Keep the worker separate from the API so restarting one does not stop data collection.

```
TradeSphere-Pro/
  docs/DATA_PIPELINE_PLAN.md
  PROGRESS.md
  docker-compose.yml
  .env.example
  .gitignore
  data/scheduled_events.json
  backend/
    requirements.txt
    alembic.ini
    alembic/versions/
    app/
      main.py                  # FastAPI app (health + read endpoints)
      worker.py                # starts scheduler, WebSocket tasks, feature job
      config.py                # settings loaded from .env
      logging_setup.py
      db/        session.py, models.py, upsert.py
      clients/   binance_futures.py, binance_spot.py, binance_ws.py,
                 cryptopanic.py, fear_greed.py, coingecko.py, http.py
      collectors/ candles.py, funding.py, open_interest.py, long_short.py,
                 premium_ws.py, liquidations_ws.py, news.py, fear_greed.py,
                 btc_dominance.py, events.py, status.py
      backfill/  run_backfill.py
      features/  common.py, f01_momentum.py ... f13_btc_correlation.py,
                 pipeline.py
      schemas/   feature_vector.py
      api/       routes_health.py, routes_data.py
    scripts/     check_pipeline.py
    tests/       fixtures/, test_*.py
```

---

## 4. Configuration

`.env.example` (values left empty, the owner fills `.env`):

```
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DB=tradesphere
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@db:5432/tradesphere
REDIS_URL=redis://redis:6379/0
CRYPTOPANIC_API_KEY=
COINGECKO_API_KEY=            # optional, only if the free tier needs a key
BINANCE_FUTURES_REST=https://fapi.binance.com
BINANCE_SPOT_REST=https://api.binance.com
BINANCE_FUTURES_WS=wss://fstream.binance.com
SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT
INTERVALS=4h,1d
LOG_LEVEL=INFO
```

All tunable numbers (windows, thresholds, weights of sub-parts) live in one `config.py` or `feature_params.yaml` file, not scattered in code.

---

## 5. Data source map: the 13 fields

Public Binance market-data endpoints need no API key. Check current docs for exact names.

| # | Field | Raw data needed | Source (Binance USDⓈ-M futures unless noted) | How collected |
|---|-------|-----------------|---------------------------------------------|---------------|
| 1 | Momentum | futures candles | `GET /fapi/v1/klines` | REST backfill + poll |
| 2 | EMA trend | futures candles | same | same |
| 3 | RSI + divergence | futures candles | same | same |
| 4 | MACD | futures candles | same | same |
| 5 | Funding trend | funding rate history | `GET /fapi/v1/fundingRate` | REST backfill + hourly poll |
| 6 | Open interest trend | OI history | `GET /futures/data/openInterestHist` (about 30 days only) | REST, poll and accumulate |
| 7 | Long/short ratio | global and top-trader ratios | `GET /futures/data/globalLongShortAccountRatio`, `topLongShortAccountRatio`, `topLongShortPositionRatio` (about 30 days only) | REST, poll and accumulate |
| 8 | Perp-spot basis | futures candles + spot candles; live mark/index price | spot `GET /api/v3/klines`; `GET /fapi/v1/premiumIndex`; WebSocket `<symbol>@markPrice@1s` | REST backfill + WebSocket |
| 9 | Liquidation zones | forced-liquidation events | WebSocket `<symbol>@forceOrder` | WebSocket, stored from day one |
| 10 | Volume + support/resistance | futures candles (volume) | same as fields 1 to 4 | derived |
| 11 | News and event sentiment | headlines, votes, Fear & Greed, scheduled events | CryptoPanic API (key needed, check current docs for URL and limits); `https://api.alternative.me/fng/?limit=0`; `data/scheduled_events.json` (hand-kept) | REST poll |
| 12 | Regime filter | futures candles | same as 1 to 4 | derived |
| 13 | BTC correlation and dominance | candles for the coin and BTC; BTC dominance | candles as above; CoinGecko `GET https://api.coingecko.com/api/v3/global` (field `data.market_cap_percentage.btc`) | REST poll |

**Why start collection immediately:** exchange history for open interest and long/short ratio is limited to about 30 days, liquidations and BTC dominance have no usable history, and news only goes back a short time. Anything not recorded now is lost for backtesting.

**Fields 9 and 12 and 13 are gates, not votes.** They are stored but not part of the weighted sum later.

---

## 6. Database schema

Use Alembic migrations. Every table below has a primary key that makes inserts safe to repeat.

```sql
-- Candles for both markets
CREATE TABLE candles (
  market      TEXT NOT NULL,           -- 'futures' | 'spot'
  symbol      TEXT NOT NULL,
  interval    TEXT NOT NULL,           -- '4h' | '1d'
  open_time   TIMESTAMPTZ NOT NULL,
  close_time  TIMESTAMPTZ NOT NULL,
  open NUMERIC(24,8) NOT NULL, high NUMERIC(24,8) NOT NULL,
  low  NUMERIC(24,8) NOT NULL, close NUMERIC(24,8) NOT NULL,
  volume NUMERIC(30,8) NOT NULL, quote_volume NUMERIC(30,8),
  trades INT, taker_buy_base NUMERIC(30,8), taker_buy_quote NUMERIC(30,8),
  is_closed   BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (market, symbol, interval, open_time)
);

CREATE TABLE funding_rates (
  symbol TEXT NOT NULL, funding_time TIMESTAMPTZ NOT NULL,
  funding_rate NUMERIC(18,10) NOT NULL, mark_price NUMERIC(24,8),
  PRIMARY KEY (symbol, funding_time)
);

CREATE TABLE open_interest (
  symbol TEXT NOT NULL, period TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL,
  sum_open_interest NUMERIC(30,8), sum_open_interest_value NUMERIC(30,8),
  PRIMARY KEY (symbol, period, ts)
);

CREATE TABLE long_short_ratio (
  symbol TEXT NOT NULL,
  ratio_type TEXT NOT NULL,     -- 'global_account' | 'top_account' | 'top_position'
  period TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL,
  long_share NUMERIC(10,6), short_share NUMERIC(10,6), long_short_ratio NUMERIC(14,6),
  PRIMARY KEY (symbol, ratio_type, period, ts)
);

-- One row per minute per symbol, written from the markPrice WebSocket
CREATE TABLE premium_snapshots (
  symbol TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL,
  mark_price NUMERIC(24,8), index_price NUMERIC(24,8),
  funding_rate NUMERIC(18,10), next_funding_time TIMESTAMPTZ,
  PRIMARY KEY (symbol, ts)
);

CREATE TABLE liquidations (
  id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL,
  side TEXT NOT NULL,           -- 'SELL' = a long was liquidated, 'BUY' = a short was liquidated
  price NUMERIC(24,8) NOT NULL, avg_price NUMERIC(24,8),
  quantity NUMERIC(30,8) NOT NULL, notional NUMERIC(30,8) NOT NULL,
  UNIQUE (symbol, ts, side, price, quantity)
);
CREATE INDEX ON liquidations (symbol, ts);

CREATE TABLE news_items (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL, external_id TEXT NOT NULL,
  currency TEXT,                -- 'BTC', 'ETH', ... or NULL for market-wide
  title TEXT NOT NULL, url TEXT, published_at TIMESTAMPTZ NOT NULL,
  votes_positive INT, votes_negative INT, votes_important INT,
  vader_compound REAL,
  raw JSONB,
  UNIQUE (source, external_id, currency)
);
CREATE INDEX ON news_items (currency, published_at);

CREATE TABLE fear_greed (
  ts TIMESTAMPTZ PRIMARY KEY, value INT NOT NULL, classification TEXT
);

CREATE TABLE btc_dominance (
  ts TIMESTAMPTZ PRIMARY KEY, dominance_pct NUMERIC(8,4) NOT NULL
);

CREATE TABLE scheduled_events (
  id SERIAL PRIMARY KEY, name TEXT NOT NULL, event_time TIMESTAMPTZ NOT NULL,
  impact TEXT NOT NULL,         -- 'high' | 'medium'
  UNIQUE (name, event_time)
);

-- The table the algorithm will read
CREATE TABLE features (
  symbol TEXT NOT NULL, interval TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL,                  -- candle close_time the values belong to
  f01_momentum REAL, f02_ema_trend REAL, f03_rsi REAL, f04_macd REAL,
  f05_funding REAL, f06_open_interest REAL, f07_long_short REAL, f08_basis REAL,
  f10_volume_sr REAL, f11_news REAL,        -- scored fields, each in -1..+1
  g09_liq_above_price NUMERIC(24,8), g09_liq_above_notional NUMERIC(30,8),
  g09_liq_below_price NUMERIC(24,8), g09_liq_below_notional NUMERIC(30,8),
  g09_source TEXT,                          -- 'liquidation_clusters' | 'swing_proxy'
  g12_regime_factor REAL,                   -- 0.2 .. 1.0
  g13_btc_corr REAL, g13_btc_beta REAL,
  g13_btc_trend SMALLINT,                   -- +1 / -1 / 0
  g13_btc_dominance REAL,
  volume_ratio REAL, atr REAL, close NUMERIC(24,8),
  news_pause BOOLEAN NOT NULL DEFAULT FALSE,
  raw JSONB,                                -- the raw values used (rsi, ema21, funding, ...)
  missing JSONB,                            -- list of field names that could not be computed
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (symbol, interval, ts)
);

CREATE TABLE collector_status (
  name TEXT PRIMARY KEY, last_success_at TIMESTAMPTZ, last_error_at TIMESTAMPTZ,
  last_error TEXT, rows_written_total BIGINT NOT NULL DEFAULT 0
);
```

Store numbers as `NUMERIC` in raw tables (no rounding surprises) and convert to float only inside the feature calculations.

---

## 7. Collection design

### 7.1 Backfill (one-time scripts, safe to re-run)

| Data | How far back | Notes |
|------|--------------|-------|
| Futures candles 4h and 1d | 2 years | page with `startTime` and `limit=1500`, move forward until now |
| Spot candles 4h and 1d | 2 years | same, from the spot API |
| Funding rate history | everything available | `limit=1000`, page by `startTime` |
| Open interest history | about 30 days | period `4h` |
| Long/short ratios (3 types) | about 30 days | period `4h` |
| Fear & Greed | full history | one call |
| News | whatever the API gives | small window |

Sleep a short time between pages (for example 0.2 s) and log progress per symbol.

### 7.2 Live collection (worker process)

| Job | Method | Frequency | Writes to |
|-----|--------|-----------|-----------|
| Candles (futures and spot, 4h and 1d) | REST, fetch last 3 candles | every 5 min | `candles` |
| Funding rate | REST, last 20 records | every hour | `funding_rates` |
| Open interest history | REST, `limit=30`, period 4h | every 30 min | `open_interest` |
| Long/short ratios (3 types) | REST, `limit=30`, period 4h | every 30 min | `long_short_ratio` |
| Mark price and index price | **WebSocket** `<symbol>@markPrice@1s`, keep latest, write one snapshot per minute | continuous | `premium_snapshots`, Redis `price:<symbol>` |
| Liquidations | **WebSocket** `<symbol>@forceOrder`, write every event | continuous | `liquidations` |
| News per coin | REST | every 15 min | `news_items` |
| Fear & Greed | REST | every 6 hours | `fear_greed` |
| BTC dominance | REST | every 30 min | `btc_dominance` |
| Scheduled events | read `data/scheduled_events.json` | at start and hourly | `scheduled_events` |
| Feature job | compute fields for the newest closed 4h candle | at 00, 04, 08, 12, 16, 20 UTC plus 60 seconds | `features` |

Use one combined WebSocket connection (`/stream?streams=...`) with lowercase symbols for both stream types (10 streams for 5 symbols).

### 7.3 Resilience rules

- **Retries:** up to 5 attempts with exponential backoff and random jitter. On HTTP 429, wait for `Retry-After`. On HTTP 418 (IP ban), stop that client and report. On HTTP 451 or 403 (region block), report as a MANUAL STEP.
- **Timeouts:** 10 s for REST calls.
- **WebSockets:** reconnect automatically with backoff. Binance closes connections after about 24 hours, so reconnect deliberately before that. Log every reconnect.
- **Gap filling:** at worker start and after any outage, compare the newest stored `open_time` with the expected one and backfill the missing candles. Funding, open interest and ratios are refilled the same way within the 30-day limit.
- **Validation before insert:** parse with pydantic, reject NaN or negative prices, check `high >= low`, store everything in UTC.
- **Status tracking:** every collector updates `collector_status` on success or failure.

---

## 8. Transformation: how each field becomes a number

**Pipeline step:** for each symbol and each closed 4h candle, read the raw tables, compute the 13 values, and upsert one row into `features` for `ts = candle close_time`.

**Common helpers (`features/common.py`)**
- `clip(x, -1, 1)`
- `rolling_z(series, window)` = (value - rolling mean) / rolling std
- `squash(z) = clip(z / 2, -1, 1)`
- `ema(series, span)` using `ewm(span=span, adjust=False)`
- `atr14`, `rsi14` use Wilder smoothing (`ewm(alpha=1/14, adjust=False)`)
- `asof_join` to attach the latest slower-frequency value (funding, ratios, news) that was available at or before the candle close. **Never use data from after the candle close** (this prevents look-ahead bias in backtests).

**Data windows:** 1 candle = 4 hours, 6 candles = 1 day. `Z-window` = 1080 candles (180 days).

### Scored fields (each output is in -1 to +1)

**F1 Momentum.** `r = close[t - 6] / close[t - 6 - 84] - 1` (14-day return, skipping the latest day). Score = `squash(rolling_z(r, 1080))`.

**F2 EMA trend.** `ema21`, `ema55`. `gap = (ema21 - ema55) / ATR14`. Score = `clip(gap / 2, -1, 1)`. If the sign of the gap disagrees with the slope of `ema21` over the last 3 candles, multiply the score by 0.5.

**F3 RSI with divergence.** `rsi = RSI14`.
- If 30 ≤ rsi ≤ 70: `base = (rsi - 50) / 50`.
- If rsi > 70: `base = 0.4 - (rsi - 70) / 30`.
- If rsi < 30: `base = -0.4 + (30 - rsi) / 30`.
- Divergence over the last 30 candles using swing points (local highs and lows with window 3): bearish (price higher high, RSI lower high) adds -0.3, bullish (price lower low, RSI higher low) adds +0.3.
- Score = `clip(base + divergence, -1, 1)`. (RSI 61 gives about +0.22, matching the blueprint's example.)

**F4 MACD.** `hist = MACD(12,26,9).histogram`. `slope = hist - hist.shift(1)`. Score = `clip(0.6 * squash(rolling_z(hist / close)) + 0.4 * squash(rolling_z(slope / close)), -1, 1)`.

**F5 Funding trend.** Funding points come every 8 hours. Take the last 12 points (4 days), compute the linear-regression slope, divide by its rolling standard deviation over 90 days, and `squash`. If the latest funding rate has the same sign as the score and `abs(funding) >= 0.0005`, multiply the score by 0.5 (crowded trade dampener).

**F6 Open interest trend.** Over the last 6 candles: `price_change` and `oi_change` (from `sum_open_interest_value`). If `abs(price_change) < 0.2%` or `abs(oi_change) < 0.5%`, score 0. Otherwise: price up and OI up = +1, price up and OI down = +0.3, price down and OI up = -1, price down and OI down = -0.3.

**F7 Long/short ratio.** `x = global_account long_share - 0.5`. Dead zone 0.06, full scale at 0.20: `s = -sign(x) * clip((abs(x) - 0.06) / 0.14, 0, 1)` (contrarian). If the `top_position` long share is on the opposite side of 0.5 from retail by more than 0.05, add 0.2 in the top-trader direction. Clip to -1 to +1.

**F8 Perp-spot basis.** `basis = (futures_close - spot_close) / spot_close` per candle. Score = `squash(rolling_z(slope of basis over the last 18 candles (3 days), 540))`.

**F10 Volume and support/resistance.**
- `volume_ratio = volume / SMA20(volume)`.
- `vol_component = sign(close - close[t - 6]) * clip(volume_ratio - 1, 0, 1)`.
- Find swing highs and lows over the last 60 candles. If the close is within 1 ATR above a support level, `sr_component = +0.3`; within 1 ATR below a resistance level, `-0.3`; otherwise 0.
- Score = `clip(0.6 * vol_component + 0.4 * sr_component, -1, 1)`.
- Also store `volume_ratio`; the scoring engine will use `volume_ratio >= 1.2` as a confirmation gate.

**F11 News and event sentiment.** Take news for the coin and market-wide news in the last 24 hours before the candle close.
- Per item: `item = 0.5 * vader_compound + 0.5 * (pos - neg) / (pos + neg + 1)`.
- Weight: `w = exp(-age_hours / 12)`, times 1.5 if the item has 3 or more "important" votes or is marked high-importance.
- `news_score = sum(w * item) / sum(w)`; 0 if no items (record it in `missing`).
- `fg = (fear_greed_value - 50) / 50`.
- Score = `clip(0.8 * news_score + 0.2 * fg, -1, 1)`.
- `news_pause = TRUE` if the candle close time is inside the window from 30 minutes before to 60 minutes after any `scheduled_events` row with impact `high`.

### Gate fields (stored, not scored)

**F9 Liquidation zones.**
- Take the last 7 days of `liquidations` for the symbol.
- Bucket prices into bins of width `0.25 * ATR14`. Sum `notional` per bin.
- A cluster is a bin at or above the 90th percentile of non-empty bins.
- Store the nearest cluster above and below the close (price and notional) and `g09_source = 'liquidation_clusters'`.
- If there are fewer than 200 events in the window (not enough data yet), fall back to the nearest swing high and swing low and set `g09_source = 'swing_proxy'`.
- Limitation to state in the README: these are clusters of **recent actual liquidations**, not a predicted heatmap.

**F12 Regime factor.** `atr_pct` = percentile rank of ATR14 over the last 540 candles (90 days). `bb_pct` = percentile rank of Bollinger width `(upper - lower) / middle` (20, 2) over the same window. `m = (atr_pct + bb_pct) / 2`. `regime_factor = 0.2 + 0.8 * clip((m - 0.2) / 0.6, 0, 1)`.

**F13 BTC correlation and dominance.**
- Use 4h log returns over the last 180 candles (30 days) for the coin and for BTCUSDT.
- `g13_btc_corr` = correlation, `g13_btc_beta` = covariance / BTC variance.
- `g13_btc_trend` = sign of (BTC ema21 - BTC ema55), or 0 if the gap is tiny.
- `g13_btc_dominance` = latest `btc_dominance` at or before the candle close (NULL before collection started).
- For BTCUSDT itself: corr 1, beta 1.
- The scoring engine computes the final factor later: if `corr >= 0.7` and the signal direction disagrees with `g13_btc_trend`, `factor = 1.0 - 0.5 * clip((corr - 0.7) / 0.3, 0, 1)`; otherwise 1.0.

### Missing data policy

- If an input is missing, store NULL for that field and add its name to `missing`. Never fill with a fake value.
- Fields 5 to 8 and 9 and 11 will be NULL for old history before collection started. That is expected.
- Rule for the later scoring engine: do not fire a signal if more than 2 of the 10 scored fields are NULL.

---

## 9. Algorithm-ready output (the contract)

The scoring engine will only read through these interfaces:

1. **Pydantic model `FeatureVector`** (`schemas/feature_vector.py`) with the same fields as the `features` table, plus helpers:
   - `scored_fields() -> dict[str, float | None]` for the 10 scored fields
   - `gates() -> dict` for fields 9, 12, 13, `news_pause` and `volume_ratio`
2. **Python functions** in `features/pipeline.py`:
   - `get_latest_features(symbol, interval="4h") -> FeatureVector`
   - `get_feature_history(symbol, interval, start, end) -> pandas.DataFrame`
3. **Read-only API routes:**
   - `GET /health` (database and Redis status)
   - `GET /collectors/status` (rows from `collector_status` with a stale flag)
   - `GET /features/{symbol}/latest`
   - `GET /features/{symbol}?start=&end=`
   - `GET /data/{table}/latest?symbol=` (for inspecting raw tables)
4. **Redis:** `features:latest:<symbol>` (JSON of the newest row) and a pub/sub channel `features:updated` that publishes `{symbol, ts}` after each feature job.

---

## 10. Data quality, monitoring and tests

**Automated checks (`scripts/check_pipeline.py`)** prints one line per table with row count, newest timestamp and PASS or FAIL:
- Candle continuity: no missing 4h `open_time` between the first and last candle (per symbol and market).
- Freshness: each collector's `last_success_at` is within 3 times its schedule interval.
- Feature sanity: all scored fields within -1 to +1 and not NaN; `g12_regime_factor` within 0.2 to 1.0.
- Duplicates: none (guaranteed by primary keys, but verify).
- Liquidation stream: at least some events in the last 24 hours (otherwise warn that the WebSocket may be silent).

**Unit tests**
- Indicators (EMA, RSI, MACD, ATR) against small hand-calculated examples.
- Each field function with synthetic data that has a known expected sign (rising prices give positive F1 and F2, and so on).
- Parsers for each API using the saved fixtures in `tests/fixtures/`.
- Idempotency: running an upsert twice leaves the row count unchanged.
- Look-ahead check: features for candle `t` do not change when data after `t` is added.

**Logging:** structured logs to stdout with the collector name, symbol and rows written.

---

## 11. Implementation stages

Each stage lists tasks and **Done when**. The agent updates `PROGRESS.md` (checklist) at the end of each stage.

### Stage 0: Repo and environment
- Create the folder structure, `.gitignore` (include `.env`, `__pycache__`, data dumps), `.env.example`, `requirements.txt`.
- Write `docker-compose.yml` with `db`, `redis`, `api`, `worker`.
- FastAPI app with `GET /health`; logging setup; `config.py` loading `.env`.
- **MANUAL STEP:** the owner installs Docker Desktop (or Docker Engine) and Python 3.11+, copies `.env.example` to `.env`, and chooses a database password.
- **Done when:** `docker compose up -d` starts all services and `/health` returns OK.

### Stage 1: API discovery (verify before building)
- Write a small script that calls each endpoint in Section 5 once per symbol (and the news, Fear & Greed and CoinGecko endpoints) and saves the raw JSON under `backend/tests/fixtures/`.
- Compare the real field names with Sections 5 and 6 and record differences in "Deviations".
- Test connectivity to Binance futures from this machine.
- **MANUAL STEP:** the owner creates a CryptoPanic account and API key (and a CoinGecko key if the free tier requires one) and puts them in `.env`. If Binance returns 451 or 403 (region block), stop and report; the owner decides the next step (for example, running from a server in another region).
- **Done when:** a fixture file exists for every endpoint and "Deviations" is up to date.

### Stage 2: Database and migrations
- SQLAlchemy models and an Alembic migration for every table in Section 6.
- `upsert.py` helper that does `INSERT ... ON CONFLICT` for any model.
- **Done when:** `alembic upgrade head` creates all tables, and a test proves upserts are idempotent.

### Stage 3: API clients
- `http.py`: shared `httpx` client with timeout, retries, backoff, and rate-limit handling from Section 7.3.
- One client module per source with typed parsers (pydantic) tested against the fixtures.
- `binance_ws.py`: a reusable WebSocket runner with auto-reconnect and a callback per message.
- **Done when:** all parser tests pass using fixtures (no live network needed).

### Stage 4: Backfill
- `run_backfill.py` with options `--symbols`, `--days`, `--only <dataset>`. Follows the table in Section 7.1. Resumes from the newest stored row if interrupted.
- Run it for all 5 symbols.
- **Done when:** about 2 years of 4h and 1d candles exist for futures and spot, and `check_pipeline.py` reports no candle gaps.

### Stage 5: Live collectors and worker
- Implement every job in Section 7.2, the WebSocket tasks, gap filling at start, and `collector_status` updates.
- `worker.py` starts everything (APScheduler plus asyncio tasks) and shuts down cleanly.
- **MANUAL STEP:** the owner creates `data/scheduled_events.json` with upcoming high-impact dates (format below) and confirms the worker runs on their machine.
- **Done when:** the worker runs for 30 minutes with no errors, `liquidations` and `premium_snapshots` are receiving rows, and `GET /collectors/status` shows every collector healthy.

### Stage 6: Price-derived features (F1, F2, F3, F4, F10, F12, F13)
- Implement `common.py` and the field modules with unit tests (Section 8).
- Add a function that computes the whole history at once (vectorised) for backtests, and a function that computes only the newest candle.
- **Done when:** tests pass, and for a chosen symbol the computed F2 and F3 values match a manual check against an independent source (for example a charting site or a quick separate calculation) within a small tolerance.

### Stage 7: Derivatives and sentiment features (F5, F6, F7, F8, F9, F11)
- Implement per Section 8, using as-of joins and the missing-data policy.
- **Done when:** tests pass, NULL handling is verified for periods before collection started, and the look-ahead test passes.

### Stage 8: Feature pipeline, contract and API
- `pipeline.py`: the 4h feature job, `--recompute-history` option, `FeatureVector`, `get_latest_features`, `get_feature_history`.
- Redis cache and `features:updated` event; API routes from Section 9.
- **Done when:** after a 4h candle closes, a new `features` row appears automatically for all 5 symbols, and `GET /features/BTCUSDT/latest` returns it.

### Stage 9: Quality, docs and report
- Finish `scripts/check_pipeline.py` and all tests; run the whole suite.
- Write `README.md` sections: architecture diagram (text or Mermaid), setup steps, how to run the worker, table descriptions, known limitations.
- Produce a final report for the owner: what was built, how to check each part, what is not done yet, and what the next phase needs.
- **Done when:** the full test suite passes and `check_pipeline.py` shows all PASS (or explained WARN).

### Stage 10 (optional): Run on a server
See Section 13.

`scheduled_events.json` format:

```json
[
  {"name": "FOMC rate decision", "event_time": "2026-12-16T19:00:00Z", "impact": "high"},
  {"name": "US CPI release", "event_time": "2026-11-12T13:30:00Z", "impact": "high"}
]
```

(The dates above are examples only. The owner must enter real dates from an official calendar.)

---

## 12. Manual steps checklist (for the owner)

- [ ] Install Docker Desktop (or Docker Engine) and Python 3.11+.
- [ ] Copy `.env.example` to `.env` and fill the database password.
- [ ] Create a CryptoPanic API key (and CoinGecko key if needed) and add them to `.env`.
- [ ] Approve terminal commands when the agent asks (Docker, pip, alembic, tests).
- [ ] Confirm Binance futures endpoints work from your network (Stage 1). If blocked, decide with the agent: server in another region or a different data source.
- [ ] Create `data/scheduled_events.json` with real upcoming dates.
- [ ] Push to GitHub when asked (the agent should not store your credentials).
- [ ] (Optional) Provision a Linux server (VPS) and give the agent SSH steps to follow, or run the commands yourself from the agent's instructions.
- [ ] Read each stage explanation the agent writes and run the "how to verify" step yourself at least once.

---

## 13. Running on a server

Data must be collected 24/7. A laptop that sleeps creates gaps that cannot be recovered for liquidations, news and snapshots (candles, funding and the 30-day derivatives data can be gap-filled).

- Use the same `docker-compose.yml` on a Linux VPS. Set `restart: unless-stopped` on all services.
- Keep Postgres and Redis on the internal Docker network only. Do not publish ports 5432 or 6379 to the internet.
- Open only SSH (key login, no password) and, if the API must be reachable, the API port behind a firewall.
- Secrets only in the server's `.env`.
- Daily backup: cron job running `pg_dump` to a compressed file, keeping the last 7 days, and copying one copy off the server weekly.
- Check disk space: `liquidations` and `news_items` grow over time; plan for a few GB.
- Verify with `check_pipeline.py` on the server and `docker compose logs -f worker`.

---

## 14. Glossary (plain language)

- **OHLCV candle:** open, high, low, close price and volume for one time period (here 4 hours).
- **Perpetual future:** a futures contract with no expiry. Its price is kept near the spot price by the funding rate.
- **Funding rate:** a payment between long and short traders every 8 hours. High positive funding means longs are crowded.
- **Open interest (OI):** total value of open futures positions. Rising OI with rising price means new money is entering.
- **Long/short ratio:** share of accounts or positions that are long versus short.
- **Basis:** the gap between the futures price and the spot price.
- **Liquidation:** the exchange force-closes a leveraged position when its margin is gone.
- **EMA, RSI, MACD, ATR:** common price indicators (trend average, overbought and oversold gauge, momentum shift, average price range).
- **Z-score:** how many standard deviations a value is from its recent average; makes different numbers comparable.
- **Normalization:** converting each field to the same -1 to +1 scale.
- **Idempotent / upsert:** doing the same insert twice gives the same result (no duplicates).
- **Backfill:** loading past data to fill the history.
- **Look-ahead bias:** accidentally using future data in a calculation, which makes backtests look better than reality.
- **As-of join:** attaching the most recent value that was known at a given moment.

---

## 15. Appendix: example calls (verify in Stage 1)

```
GET https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=4h&limit=1500
GET https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=4h&limit=1000
GET https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1000
GET https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=4h&limit=500
GET https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=4h&limit=500
GET https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol=BTCUSDT&period=4h&limit=500
GET https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT
GET https://api.alternative.me/fng/?limit=0
GET https://api.coingecko.com/api/v3/global
WS  wss://fstream.binance.com/stream?streams=btcusdt@markPrice@1s/btcusdt@forceOrder
```

Expected kline row order (REST): open time, open, high, low, close, volume, close time, quote volume, number of trades, taker buy base volume, taker buy quote volume, ignore.

---

## Deviations (the agent fills this in)

### DEV-001 — CryptoPanic replaced by Messari API (2026-11-02)

**Original plan:** `CryptoPanic API` for coin-specific headlines and community vote counts (positive/negative/important).

**Reality:** CryptoPanic no longer offers a free API tier. The API key page requires a paid subscription.

**Fix applied:**
- Replaced `cryptopanic.py` client with `messari.py` client.
- Messari `/v1/news` endpoint returns professional crypto-specific news with title, published_at, tags (coins), and content.
- **F11 formula adaptation:** community vote fraction `0.5 * (pos - neg) / (pos + neg + 1)` is dropped. Instead:
  - `item_score = vader_compound` (VADER on the title text — same as before)
  - Source credibility weight added: Messari = 1.3×, all others = 1.0×
  - Final formula: `item = item_score * source_weight`
  - Recency decay and Fear & Greed blending unchanged.
- `news_items` table keeps all columns; `votes_positive`, `votes_negative`, `votes_important` will be NULL for Messari items (expected, documented).
- `.env.example` updated: `CRYPTOPANIC_API_KEY` → `MESSARI_API_KEY`.

**Messari free tier limits:** 20 requests/minute, ~1,000/day. Our 15-minute polling schedule uses ~96 requests/day — well within limits.

---

### DEV-002 - Funding rate: extra field rateType (2026-11-02)

**Endpoint:** GET /fapi/v1/fundingRate

**Plan said fields:** symbol, fundingTime, fundingRate, markPrice

**Real response fields:** symbol, fundingTime, fundingRate, markPrice, rateType

**Fix:** Added rate_type TEXT column to funding_rates table. Values like "Regular". Stored for future use.

---

### DEV-003 - Open interest history: extra field CMCCirculatingSupply (2026-11-02)

**Endpoint:** GET /futures/data/openInterestHist

**Real response adds:** CMCCirculatingSupply field (circulating supply from CoinMarketCap)

**Fix:** Added cmc_circulating_supply NUMERIC(30,8) column to open_interest table.

---

### DEV-004 - Long/short ratios: field names are longAccount/shortAccount not long_share/short_share (2026-11-02)

**All three L/S endpoints** return: longAccount, shortAccount, longShortRatio, symbol, timestamp

**Plan used:** long_share, short_share. These are the same values, just different names.

**Fix:** ORM keeps long_share/short_share internally. Parser maps longAccount->long_share, shortAccount->short_share.

---

### DEV-005 - Premium index: extra fields estimatedSettlePrice and interestRate (2026-11-02)

**Real fields:** symbol, markPrice, indexPrice, estimatedSettlePrice, lastFundingRate, interestRate, nextFundingTime, time

**Fix:** Only markPrice, indexPrice, lastFundingRate, nextFundingTime used. Timestamp field is named "time" (Unix ms).

---

### DEV-006 - Klines return 12 elements. Plan appendix listed 12, confirmed correct.

Both futures (/fapi/v1/klines) and spot (/api/v3/klines) return 12-element arrays.
Index mapping: [0]=open_time [1]=open [2]=high [3]=low [4]=close [5]=volume
[6]=close_time [7]=quote_vol [8]=trades [9]=taker_buy_base [10]=taker_buy_quote [11]=ignore(always "0")

---

### DEV-007 - Fear & Greed: timestamp and value are strings, not integers (2026-11-02)

**Fix:** Parser casts value=int(value), timestamp=int(timestamp) before storing.

---

### DEV-008 - Binance connectivity confirmed, no region block (2026-11-02)

42/43 endpoints returned HTTP 200. Only skip was Messari (key not yet set).
