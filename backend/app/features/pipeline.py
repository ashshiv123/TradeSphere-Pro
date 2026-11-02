"""
pipeline.py — Master feature computation pipeline and query interfaces.

Implements DATA_PIPELINE_PLAN.md §8 and §9:
- Computes the 13 fields for a closed 4h candle.
- Upserts to `features` table.
- Caches to Redis: key `features:latest:<symbol>`.
- Publishes to Redis pub/sub channel: `features:updated`.
- Exposes:
    get_latest_features(symbol, interval="4h") -> FeatureVector
    get_feature_history(symbol, interval, start, end) -> pd.DataFrame
    recompute_history(symbols, interval="4h", db=None)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    BtcDominance,
    Candle,
    FearGreed,
    Feature,
    FundingRate,
    Liquidation,
    LongShortRatio,
    NewsItem,
    OpenInterest,
    ScheduledEvent,
)
from app.db.session import SessionLocal
from app.db.upsert import upsert_row
from app.features.common import atr
from app.features.f01_momentum import compute_f01_latest
from app.features.f02_ema_trend import compute_f02_latest
from app.features.f03_rsi import compute_f03_latest
from app.features.f04_macd import compute_f04_latest
from app.features.f05_funding import compute_f05_latest
from app.features.f06_open_interest import compute_f06_latest
from app.features.f07_long_short import compute_f07_latest
from app.features.f08_basis import compute_f08_latest
from app.features.f09_liquidations import compute_f09_latest
from app.features.f10_volume_sr import compute_f10_latest
from app.features.f11_news import compute_f11_latest
from app.features.f12_regime import compute_f12_latest
from app.features.f13_btc_correlation import compute_f13_latest
from app.schemas.feature_vector import FeatureVector

logger = logging.getLogger(__name__)


def _publish_redis(symbol: str, fv: FeatureVector) -> None:
    """Cache latest FeatureVector in Redis and publish update event."""
    try:
        import redis as redis_lib

        settings = get_settings()
        if not settings.redis_url:
            return

        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        # 1. Cache latest row
        cache_key = f"features:latest:{symbol.upper()}"
        r.set(cache_key, fv.model_dump_json())

        # 2. Publish event to pub/sub channel
        channel = "features:updated"
        payload = json.dumps({"symbol": symbol.upper(), "ts": fv.ts.isoformat()})
        r.publish(channel, payload)
    except Exception as exc:
        logger.debug("Redis cache/publish notice (non-fatal): %s", exc)


def load_candles_df(
    db: Session,
    symbol: str,
    market: str = "futures",
    interval: str = "4h",
    limit: int = 1200,
    up_to_time: Optional[datetime] = None,
) -> pd.DataFrame:
    """Load historical candles up to up_to_time as a pandas DataFrame."""
    q = (
        select(Candle)
        .where(
            Candle.market == market,
            Candle.symbol == symbol.upper(),
            Candle.interval == interval,
        )
    )
    if up_to_time:
        q = q.where(Candle.close_time <= up_to_time)

    q = q.order_by(Candle.open_time.desc()).limit(limit)
    rows = db.execute(q).scalars().all()
    if not rows:
        return pd.DataFrame()

    data = [
        {
            "open_time": r.open_time,
            "close_time": r.close_time,
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "volume": float(r.volume),
        }
        for r in reversed(rows)
    ]
    return pd.DataFrame(data)


def compute_features_for_candle(
    db: Session,
    symbol: str,
    interval: str = "4h",
    candle_close_time: Optional[datetime] = None,
) -> FeatureVector:
    """
    Compute all 13 feature values for a symbol as of candle_close_time.
    If candle_close_time is None, uses the newest closed 4h candle in DB.
    """
    sym = symbol.upper()

    # 1. Load Futures Candles
    f_df = load_candles_df(db, sym, market="futures", interval=interval, limit=1200, up_to_time=candle_close_time)
    if f_df.empty:
        raise ValueError(f"No futures candles found for {sym} {interval}")

    current_close_time = f_df["close_time"].iloc[-1]
    current_close = float(f_df["close"].iloc[-1])

    # Calculate ATR14 for current candle
    atr14_series = atr(f_df, 14)
    current_atr = float(atr14_series.iloc[-1]) if not pd.isna(atr14_series.iloc[-1]) else None

    # Load BTC candles for F13
    if sym == "BTCUSDT":
        btc_df = f_df
    else:
        btc_df = load_candles_df(db, "BTCUSDT", market="futures", interval=interval, limit=1200, up_to_time=current_close_time)

    missing: List[str] = []
    raw_debug: Dict[str, Any] = {}

    # ── Price-Derived Features (Stage 6) ──────────────────────────────────────
    f01 = compute_f01_latest(f_df)
    if f01 is None:
        missing.append("f01_momentum")

    f02 = compute_f02_latest(f_df)
    if f02 is None:
        missing.append("f02_ema_trend")

    f03 = compute_f03_latest(f_df)
    if f03 is None:
        missing.append("f03_rsi")

    f04 = compute_f04_latest(f_df)
    if f04 is None:
        missing.append("f04_macd")

    f10, vol_ratio = compute_f10_latest(f_df)
    if f10 is None:
        missing.append("f10_volume_sr")

    g12 = compute_f12_latest(f_df)
    if g12 is None:
        missing.append("g12_regime_factor")

    # Latest BTC dominance
    dom_row = db.execute(
        select(BtcDominance).where(BtcDominance.ts <= current_close_time).order_by(BtcDominance.ts.desc()).limit(1)
    ).scalar_one_or_none()
    btc_dom = float(dom_row.dominance_pct) if dom_row else None

    g13_corr, g13_beta, g13_trend, _ = compute_f13_latest(
        f_df, btc_df, symbol=sym, latest_dominance=btc_dom
    )
    if g13_corr is None:
        missing.append("g13_btc_corr")

    # ── Derivatives & Sentiment Features (Stage 7) ────────────────────────────

    # F5 Funding
    funding_rows = db.execute(
        select(FundingRate)
        .where(FundingRate.symbol == sym, FundingRate.funding_time <= current_close_time)
        .order_by(FundingRate.funding_time.desc())
        .limit(300)
    ).scalars().all()
    if funding_rows:
        funding_df = pd.DataFrame([
            {"funding_time": r.funding_time, "funding_rate": float(r.funding_rate)}
            for r in reversed(funding_rows)
        ])
        f05 = compute_f05_latest(funding_df, as_of_time=current_close_time)
    else:
        f05 = None
    if f05 is None:
        missing.append("f05_funding")

    # F6 Open Interest
    oi_rows = db.execute(
        select(OpenInterest)
        .where(OpenInterest.symbol == sym, OpenInterest.period == interval, OpenInterest.ts <= current_close_time)
        .order_by(OpenInterest.ts.desc())
        .limit(20)
    ).scalars().all()
    if oi_rows:
        oi_df = pd.DataFrame([
            {"ts": r.ts, "sum_open_interest_value": float(r.sum_open_interest_value or 0)}
            for r in reversed(oi_rows)
        ])
        f06 = compute_f06_latest(f_df, oi_df, as_of_time=current_close_time)
    else:
        f06 = None
    if f06 is None:
        missing.append("f06_open_interest")

    # F7 Long/Short Ratio
    ls_rows = db.execute(
        select(LongShortRatio)
        .where(LongShortRatio.symbol == sym, LongShortRatio.period == interval, LongShortRatio.ts <= current_close_time)
        .order_by(LongShortRatio.ts.desc())
        .limit(30)
    ).scalars().all()
    if ls_rows:
        ls_df = pd.DataFrame([
            {
                "ts": r.ts,
                "ratio_type": r.ratio_type,
                "long_share": float(r.long_share or 0.5),
                "short_share": float(r.short_share or 0.5),
            }
            for r in reversed(ls_rows)
        ])
        f07 = compute_f07_latest(ls_df, as_of_time=current_close_time)
    else:
        f07 = None
    if f07 is None:
        missing.append("f07_long_short")

    # F8 Basis (Spot vs Futures)
    s_df = load_candles_df(db, sym, market="spot", interval=interval, limit=600, up_to_time=current_close_time)
    if not s_df.empty:
        f08 = compute_f08_latest(f_df, s_df, as_of_time=current_close_time)
    else:
        f08 = None
    if f08 is None:
        missing.append("f08_basis")

    # F9 Liquidations
    liq_rows = db.execute(
        select(Liquidation)
        .where(
            Liquidation.symbol == sym,
            Liquidation.ts <= current_close_time,
            Liquidation.ts >= (current_close_time - pd.Timedelta(days=7)),
        )
        .limit(1000)
    ).scalars().all()
    liq_df = pd.DataFrame([
        {"ts": r.ts, "price": float(r.price), "notional": float(r.notional)}
        for r in liq_rows
    ]) if liq_rows else pd.DataFrame()

    g09_above_p, g09_above_n, g09_below_p, g09_below_n, g09_src = compute_f09_latest(
        liq_df, f_df, atr14_val=current_atr or 0.0, as_of_time=current_close_time
    )

    # F11 News, Events, and Fear & Greed
    news_rows = db.execute(
        select(NewsItem)
        .where(
            NewsItem.published_at <= current_close_time,
            NewsItem.published_at >= (current_close_time - pd.Timedelta(hours=24)),
        )
        .limit(200)
    ).scalars().all()
    news_df = pd.DataFrame([
        {
            "currency": r.currency,
            "published_at": r.published_at,
            "source": r.source,
            "vader_compound": float(r.vader_compound or 0),
            "votes_important": r.votes_important,
        }
        for r in news_rows
    ]) if news_rows else pd.DataFrame()

    fg_row = db.execute(
        select(FearGreed).where(FearGreed.ts <= current_close_time).order_by(FearGreed.ts.desc()).limit(1)
    ).scalar_one_or_none()
    fg_val = int(fg_row.value) if fg_row else None

    ev_rows = db.execute(select(ScheduledEvent)).scalars().all()
    events_df = pd.DataFrame([
        {"name": r.name, "event_time": r.event_time, "impact": r.impact}
        for r in ev_rows
    ]) if ev_rows else pd.DataFrame()

    f11, news_pause, is_news_missing = compute_f11_latest(
        news_df, fg_val, events_df, coin=sym, candle_close_time=current_close_time
    )
    if is_news_missing:
        missing.append("f11_news")

    computed_now = datetime.now(timezone.utc)

    fv = FeatureVector(
        symbol=sym,
        interval=interval,
        ts=current_close_time,
        f01_momentum=f01,
        f02_ema_trend=f02,
        f03_rsi=f03,
        f04_macd=f04,
        f05_funding=f05,
        f06_open_interest=f06,
        f07_long_short=f07,
        f08_basis=f08,
        f10_volume_sr=f10,
        f11_news=f11,
        g09_liq_above_price=g09_above_p,
        g09_liq_above_notional=g09_above_n,
        g09_liq_below_price=g09_below_p,
        g09_liq_below_notional=g09_below_n,
        g09_source=g09_src,
        g12_regime_factor=g12,
        g13_btc_corr=g13_corr,
        g13_btc_beta=g13_beta,
        g13_btc_trend=g13_trend,
        g13_btc_dominance=btc_dom,
        volume_ratio=vol_ratio,
        atr=current_atr,
        close=current_close,
        news_pause=news_pause,
        raw=raw_debug,
        missing=missing,
        computed_at=computed_now,
    )

    # Upsert row into DB
    row_dict = fv.model_dump()
    upsert_row(db, Feature, row_dict, conflict_cols=["symbol", "interval", "ts"])
    db.commit()

    # Redis cache and event
    _publish_redis(sym, fv)

    return fv


def get_latest_features(
    symbol: str, interval: str = "4h", db: Optional[Session] = None
) -> Optional[FeatureVector]:
    """Retrieve the most recent computed FeatureVector for a symbol."""
    sym = symbol.upper()

    def _query(s: Session) -> Optional[FeatureVector]:
        row = (
            s.execute(
                select(Feature)
                .where(Feature.symbol == sym, Feature.interval == interval)
                .order_by(Feature.ts.desc())
                .limit(1)
            )
            .scalar_one_or_none()
        )
        if not row:
            return None
        return FeatureVector(
            symbol=row.symbol,
            interval=row.interval,
            ts=row.ts,
            f01_momentum=row.f01_momentum,
            f02_ema_trend=row.f02_ema_trend,
            f03_rsi=row.f03_rsi,
            f04_macd=row.f04_macd,
            f05_funding=row.f05_funding,
            f06_open_interest=row.f06_open_interest,
            f07_long_short=row.f07_long_short,
            f08_basis=row.f08_basis,
            f10_volume_sr=row.f10_volume_sr,
            f11_news=row.f11_news,
            g09_liq_above_price=float(row.g09_liq_above_price) if row.g09_liq_above_price else None,
            g09_liq_above_notional=float(row.g09_liq_above_notional) if row.g09_liq_above_notional else None,
            g09_liq_below_price=float(row.g09_liq_below_price) if row.g09_liq_below_price else None,
            g09_liq_below_notional=float(row.g09_liq_below_notional) if row.g09_liq_below_notional else None,
            g09_source=row.g09_source,
            g12_regime_factor=row.g12_regime_factor,
            g13_btc_corr=row.g13_btc_corr,
            g13_btc_beta=row.g13_btc_beta,
            g13_btc_trend=row.g13_btc_trend,
            g13_btc_dominance=row.g13_btc_dominance,
            volume_ratio=row.volume_ratio,
            atr=row.atr,
            close=float(row.close) if row.close else None,
            news_pause=row.news_pause,
            raw=row.raw,
            missing=row.missing,
            computed_at=row.computed_at,
        )

    if db is not None:
        return _query(db)
    with SessionLocal() as s:
        return _query(s)


def get_feature_history(
    symbol: str,
    interval: str = "4h",
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: Optional[Session] = None,
) -> pd.DataFrame:
    """Retrieve historical features as a pandas DataFrame."""
    sym = symbol.upper()

    def _query(s: Session) -> pd.DataFrame:
        stmt = (
            select(Feature)
            .where(Feature.symbol == sym, Feature.interval == interval)
            .order_by(Feature.ts.asc())
        )
        if start:
            stmt = stmt.where(Feature.ts >= pd.to_datetime(start, utc=True))
        if end:
            stmt = stmt.where(Feature.ts <= pd.to_datetime(end, utc=True))

        rows = s.execute(stmt).scalars().all()
        if not rows:
            return pd.DataFrame()

        dicts = [
            {
                "symbol": r.symbol,
                "interval": r.interval,
                "ts": r.ts,
                "f01_momentum": r.f01_momentum,
                "f02_ema_trend": r.f02_ema_trend,
                "f03_rsi": r.f03_rsi,
                "f04_macd": r.f04_macd,
                "f05_funding": r.f05_funding,
                "f06_open_interest": r.f06_open_interest,
                "f07_long_short": r.f07_long_short,
                "f08_basis": r.f08_basis,
                "f10_volume_sr": r.f10_volume_sr,
                "f11_news": r.f11_news,
                "g09_liq_above_price": float(r.g09_liq_above_price) if r.g09_liq_above_price else None,
                "g09_liq_below_price": float(r.g09_liq_below_price) if r.g09_liq_below_price else None,
                "g09_source": r.g09_source,
                "g12_regime_factor": r.g12_regime_factor,
                "g13_btc_corr": r.g13_btc_corr,
                "g13_btc_beta": r.g13_btc_beta,
                "g13_btc_trend": r.g13_btc_trend,
                "g13_btc_dominance": r.g13_btc_dominance,
                "volume_ratio": r.volume_ratio,
                "atr": r.atr,
                "close": float(r.close) if r.close else None,
                "news_pause": r.news_pause,
            }
            for r in rows
        ]
        return pd.DataFrame(dicts)

    if db is not None:
        return _query(db)
    with SessionLocal() as s:
        return _query(s)


def recompute_history(
    symbols: List[str], interval: str = "4h", db: Optional[Session] = None
) -> int:
    """
    Recompute features for all closed candles across the given symbols.
    Useful for historical backfilling and backtesting.
    """
    def _run(s: Session) -> int:
        count = 0
        for sym in symbols:
            # Query distinct closed candle close_times
            c_times = s.execute(
                select(Candle.close_time)
                .where(Candle.market == "futures", Candle.symbol == sym.upper(), Candle.interval == interval)
                .order_by(Candle.close_time.asc())
            ).scalars().all()

            logger.info("Recomputing %d candles for %s %s", len(c_times), sym, interval)
            for ct in c_times:
                try:
                    compute_features_for_candle(s, sym, interval=interval, candle_close_time=ct)
                    count += 1
                except Exception as exc:
                    logger.warning("Error computing %s at %s: %s", sym, ct, exc)
        return count

    if db is not None:
        return _run(db)
    with SessionLocal() as s:
        return _run(s)

