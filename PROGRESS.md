# TradeSphere Pro — Build Progress

_Last updated: 2026-11-02_

---

## Stage 0: Repo and environment ✅

- [x] Folder structure created (all dirs in plan §3)
- [x] `.gitignore` (excludes `.env`, `__pycache__`, data dumps)
- [x] `.env.example` with all required keys, empty values
- [x] `docker-compose.yml` — services: `db`, `redis`, `api`, `worker`
- [x] `backend/Dockerfile`
- [x] `backend/requirements.txt`
- [x] `app/config.py` — pydantic-settings, `get_settings()`
- [x] `app/logging_setup.py` — structured logging to stdout
- [x] `app/main.py` — FastAPI app with `GET /health`
- [x] `app/worker.py` — stub process (real jobs in Stage 5)
- [x] `app/api/routes_health.py` — health endpoint
- [x] `app/api/routes_data.py` — read-only data/features/status endpoints (stubs until DB exists)
- [x] `app/db/session.py` — SQLAlchemy engine + `get_session`
- [x] `app/db/models.py` — Base (full models in Stage 2)
- [x] `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`
- [x] `data/scheduled_events.json` — example template
- [ ] ⏳ **MANUAL STEP**: owner installs Docker Desktop + Python 3.11+, copies `.env.example` → `.env`, fills password
- [ ] ⏳ **VERIFY**: `docker compose up -d` → `/health` returns `{"status":"ok"}`

---

## Stage 1: API discovery ⬜

- [ ] Discovery script calls every endpoint once
- [ ] Fixtures saved to `backend/tests/fixtures/`
- [ ] Deviations section updated in `DATA_PIPELINE_PLAN.md`
- [ ] Binance connectivity confirmed
- [ ] CryptoPanic key in `.env`

---

## Stage 2: Database and migrations ⬜

- [ ] All 11 SQLAlchemy models defined in `models.py`
- [ ] Alembic migration `001_initial_schema.py`
- [ ] `upsert.py` helper
- [ ] Idempotency test passes

---

## Stage 3: API clients ⬜

- [ ] `http.py` — shared httpx client with retries/backoff
- [ ] `binance_futures.py`, `binance_spot.py`
- [ ] `binance_ws.py` — WebSocket with auto-reconnect
- [ ] `cryptopanic.py`, `fear_greed.py`, `coingecko.py`
- [ ] Parser tests against fixtures pass

---

## Stage 4: Backfill ⬜

- [ ] `run_backfill.py` with `--symbols`, `--days`, `--only`
- [ ] 2 years of 4h + 1d candles (futures + spot) loaded
- [ ] `check_pipeline.py` reports no candle gaps

---

## Stage 5: Live collectors and worker ⬜

- [ ] All REST jobs implemented (candles, funding, OI, L/S, news, F&G, dominance)
- [ ] WebSocket tasks: markPrice + forceOrder
- [ ] Gap-filling at worker start
- [ ] `collector_status` updated on each success/failure
- [ ] Worker runs 30 min cleanly
- [ ] `liquidations` and `premium_snapshots` receiving rows
- [ ] `GET /collectors/status` shows all healthy

---

## Stage 6: Price-derived features ⬜

- [ ] F1 Momentum, F2 EMA trend, F3 RSI, F4 MACD, F10 Volume/SR, F12 Regime, F13 BTC correlation
- [ ] `common.py` helpers
- [ ] Unit tests pass

---

## Stage 7: Derivatives and sentiment features ⬜

- [ ] F5 Funding trend, F6 OI trend, F7 L/S ratio, F8 Basis, F9 Liquidation zones, F11 News
- [ ] As-of joins, missing-data policy, look-ahead test

---

## Stage 8: Feature pipeline + API ⬜

- [ ] `pipeline.py` — 4h feature job
- [ ] `FeatureVector` Pydantic model
- [ ] Redis cache + `features:updated` pub/sub
- [ ] API routes `/features/{symbol}/latest` and `/features/{symbol}`

---

## Stage 9: Quality, docs, final report ⬜

- [ ] `check_pipeline.py` all PASS
- [ ] Full pytest suite green
- [ ] `README.md` with architecture + setup guide
- [ ] Final report written

---

## Known issues / deviations

_None yet — Stage 1 will populate this._

