# TradeSphere Pro — Build Progress

_Last updated: 2026-11-02_

---

## Stage 0: Repo and environment ✅
- [x] Folder structure created (all dirs in plan §3)
- [x] `.gitignore` (excludes `.env`, `__pycache__`, data dumps)
- [x] `.env.example` with all required keys, empty values
- [x] `docker-compose.yml` — services: `db`, `redis`, `api`, `worker`
- [x] `backend/Dockerfile` & `backend/requirements.txt`
- [x] `app/config.py` — pydantic-settings, `get_settings()`
- [x] `app/logging_setup.py` — structured logging to stdout
- [x] `app/main.py` — FastAPI app with `GET /health`
- [x] `app/worker.py` — APScheduler + Binance WebSocket runner
- [x] `app/api/routes_health.py` — health endpoint
- [x] `app/api/routes_data.py` — read-only data/features/status endpoints
- [x] `app/db/session.py` — SQLAlchemy engine + `get_session`
- [x] `app/db/models.py` — Models and Base
- [x] `alembic.ini`, `alembic/env.py`, `001_initial_schema.py`
- [x] Docker stack up: `db`, `redis`, `api`, `worker` running healthy

---

## Stage 1: API discovery & Deviations ✅
- [x] Verified all Binance Futures, Spot, Fear & Greed, and CoinGecko endpoints
- [x] Recorded DEV-001 through DEV-008 in `docs/DATA_PIPELINE_PLAN.md`
- [x] Binance connectivity confirmed with zero region blocks

---

## Stage 2: Database and migrations ✅
- [x] 12 tables created via Alembic `001_initial_schema.py`
- [x] Idempotent upsert logic verified across all models

---

## Stage 3: API clients ✅
- [x] `http.py` — resilient HTTP client with exponential backoff and rate-limit handling
- [x] Typed clients: `binance_futures.py`, `binance_spot.py`, `fear_greed.py`, `coingecko.py`, `messari.py`
- [x] `binance_ws.py` — combined WebSocket runner for markPrice and forceOrder with auto-reconnect
- [x] Unit tests in `test_stage3_parsers.py` pass (9/9)

---

## Stage 4: Backfill ✅
- [x] `run_backfill.py` with multi-dataset support and resume capability
- [x] Backfilled 4,200 candles, 900 funding rates, 930 OI, 1,860 L/S ratios, 3,193 Fear & Greed rows
- [x] Zero candle gaps verified for BTCUSDT 4h

---

## Stage 5: Live collectors and worker ✅
- [x] Live collectors: `candles.py`, `funding.py`, `open_interest.py`, `long_short.py`, `news.py`, `fear_greed.py`, `btc_dominance.py`, `events.py`, `ws_handler.py`
- [x] `worker.py` running with 9 registered APScheduler jobs + Binance WebSocket runner
- [x] `collector_status` tracking live successes and row counts

---

## Stage 6: Price-derived features ✅
- [x] F1 Momentum, F2 EMA trend, F3 RSI, F4 MACD, F10 Volume/SR, F12 Regime, F13 BTC correlation
- [x] Independent verification of F2 & F3 on real BTCUSDT data (0.00000000 difference, PASS)

---

## Stage 7: Derivatives and sentiment features ✅
- [x] F5 Funding, F6 OI, F7 L/S, F8 Basis, F9 Liquidation zones, F11 News
- [x] As-of joins and missing-data policy verified
- [x] Look-ahead bias test passed

---

## Stage 8: Feature pipeline + API ✅
- [x] `pipeline.py`: master calculation and `recompute_history`
- [x] `FeatureVector` schema with `.scored_fields()` and `.gates()`
- [x] Redis cache and `features:updated` pub/sub
- [x] Read-only API routes active

---

## Stage 9: Quality, docs, final report ✅
- [x] `scripts/check_pipeline.py` audit tool
- [x] Pytest test suite passing (57/57 tests green)
- [x] Comprehensive `README.md`

---

## Stage 11: Data-Layer Gate ⏳ (In Progress / Manual Check)
- [x] Run `check_pipeline.py` on PostgreSQL: Overall Pipeline Health ✅ PASS
- [x] Full test suite: 57 passed, 0 failed
- [x] 4h feature job scheduled at candle boundaries UTC (00:01, 04:01, 08:01, 12:01, 16:01, 20:01)
- [x] Recomputed history for all 5 symbols (1,800 feature rows populated)
- [x] Monthly NULL share table generated: proves older history needs Reduced Mode (F6/F7 NULL >30d ago) while recent window is 100% complete
- [x] DEV-001 explains why F11 uses Messari + VADER (CryptoPanic dropped free tier)
- [x] TradingView reference values printed for BTCUSDT 4h candle closing 2026-11-02 15:59:59 UTC
- [ ] ⏳ **MANUAL STEP**: Owner compares TradingView BTCUSDT 4h chart with printed reference numbers

---

## Stage 12: Scoring Engine ⬜
- [x] Database migration `002_decision_layer.py` applied to PostgreSQL (`signals`, `trade_plans`, etc.)
- [x] SQLAlchemy models in `models_trading.py`
- [ ] `scoring_config.yaml`
- [ ] Core scoring functions in `backend/app/scoring/` (full and reduced modes, decision rules, SL/TP)
- [ ] Unit tests for scoring engine

---

## Stage 13: Risk Layer ⬜
- [ ] `risk.yaml`
- [ ] Sizing math, leverage caps, 7 safety rules, kill-switch logic in `backend/app/risk/`
- [ ] Unit tests for risk rules

---

## Stage 14: Signal Job & Logging ⬜
- [ ] Worker signal job listening after feature computation
- [ ] Trade plans logging and status transitions
- [ ] Read-only trading API routes (`/signals`, `/plans`, `/risk/status`, `/killswitch`)
- [ ] Extended audit script

---

## Stage 15: Backtester ⬜
- [ ] Simulation engine with slippage (0.02%), fees (0.05%), funding rate settlements
- [ ] Pessimistic stop-first rule
- [ ] Baselines (Buy & Hold + 100 random seeds)
- [ ] Period A (60%), B (20%), C (20%) time split
- [ ] Markdown reports generator in `reports/`
