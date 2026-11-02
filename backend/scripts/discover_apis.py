# Stage 1: API Discovery Script
# ================================
# Calls every endpoint from DATA_PIPELINE_PLAN.md section 5 once per symbol,
# saves raw JSON to backend/tests/fixtures/, and prints a summary.
#
# Run from the repo root (your own terminal, not inside Docker):
#
#   cd "C:\Users\peepr\OneDrive\Desktop\TradeSpere Pro"
#   pip install httpx
#   python backend/scripts/discover_apis.py
#
# The Messari key is read from .env in the repo root.
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Allow running from any working directory
REPO_ROOT = Path(__file__).resolve().parents[2]  # scripts/ -> backend/ -> root
FIXTURES = REPO_ROOT / "backend" / "tests" / "fixtures"
FIXTURES.mkdir(parents=True, exist_ok=True)


def _load_env() -> dict:
    """Read .env file manually (no external deps needed)."""
    env: dict = {}
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        print(f"WARNING: .env not found at {env_path}")
        return env
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().split("#")[0].strip()
    return env


ENV = _load_env()
MESSARI_KEY = ENV.get("MESSARI_API_KEY", "") or ENV.get("messari_api_key", "")

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
COIN_SLUGS = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "SOLUSDT": "solana",
    "BNBUSDT": "binance-coin",
    "XRPUSDT": "xrp",
}

results: list[dict] = []


def save(name: str, data) -> Path:
    path = FIXTURES / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def call(client: httpx.Client, label: str, url: str, params=None, headers=None):
    """Make one GET request, print result, return JSON or None."""
    try:
        r = client.get(url, params=params or {}, headers=headers or {}, timeout=15)
        ok = r.status_code == 200
        try:
            data = r.json()
        except Exception:
            data = r.text

        status = r.status_code
        note = ""
        if status == 451:
            note = "REGION BLOCK (HTTP 451)"
        elif status == 403:
            note = "FORBIDDEN (HTTP 403) - possible region block"
        elif status == 429:
            note = "RATE LIMITED (HTTP 429)"
        elif not ok:
            note = f"HTTP {status}: {str(data)[:120]}"

        results.append({"endpoint": label, "status": status, "ok": ok, "note": note})
        marker = "OK" if ok else "!!"
        print(f"  [{marker}] [{status}] {label}")
        if note:
            print(f"       NOTE: {note}")
        return data if ok else None
    except Exception as exc:
        results.append({"endpoint": label, "status": "ERR", "ok": False, "note": str(exc)})
        print(f"  [!!] [ERR] {label} - {exc}")
        return None


def main():
    print("=" * 60)
    print("TradeSphere Pro - Stage 1: API Discovery")
    print("=" * 60)

    with httpx.Client(follow_redirects=True) as client:

        # 1. Binance Futures: klines (candles)
        print("\n[1] Binance Futures klines (4h, last 3 candles)")
        for sym in SYMBOLS:
            data = call(client,
                f"futures_klines_{sym}",
                "https://fapi.binance.com/fapi/v1/klines",
                {"symbol": sym, "interval": "4h", "limit": 3},
            )
            if data:
                save(f"futures_klines_{sym}", data)
                print(f"       Columns per row: {len(data[0])}")
            time.sleep(0.3)

        # 2. Binance Spot: klines
        print("\n[2] Binance Spot klines (4h, last 3 candles)")
        for sym in SYMBOLS:
            data = call(client,
                f"spot_klines_{sym}",
                "https://api.binance.com/api/v3/klines",
                {"symbol": sym, "interval": "4h", "limit": 3},
            )
            if data:
                save(f"spot_klines_{sym}", data)
            time.sleep(0.3)

        # 3. Binance Futures: funding rate history
        print("\n[3] Binance Futures funding rates")
        for sym in SYMBOLS:
            data = call(client,
                f"futures_funding_{sym}",
                "https://fapi.binance.com/fapi/v1/fundingRate",
                {"symbol": sym, "limit": 10},
            )
            if data:
                save(f"futures_funding_{sym}", data)
                if data:
                    print(f"       Keys: {list(data[0].keys())}")
            time.sleep(0.3)

        # 4. Binance Futures: open interest history
        print("\n[4] Binance Futures open interest history (4h)")
        for sym in SYMBOLS:
            data = call(client,
                f"futures_oi_hist_{sym}",
                "https://fapi.binance.com/futures/data/openInterestHist",
                {"symbol": sym, "period": "4h", "limit": 5},
            )
            if data:
                save(f"futures_oi_hist_{sym}", data)
                if data:
                    print(f"       Keys: {list(data[0].keys())}")
            time.sleep(0.3)

        # 5. Binance Futures: global long/short account ratio
        print("\n[5] Binance Futures global long/short account ratio")
        for sym in SYMBOLS:
            data = call(client,
                f"futures_ls_global_{sym}",
                "https://fapi.binance.com/futures/data/globalLongShortAccountRatio",
                {"symbol": sym, "period": "4h", "limit": 5},
            )
            if data:
                save(f"futures_ls_global_{sym}", data)
                if data:
                    print(f"       Keys: {list(data[0].keys())}")
            time.sleep(0.3)

        # 6. Binance Futures: top trader long/short account ratio
        print("\n[6] Binance Futures top trader account ratio")
        for sym in SYMBOLS:
            data = call(client,
                f"futures_ls_top_account_{sym}",
                "https://fapi.binance.com/futures/data/topLongShortAccountRatio",
                {"symbol": sym, "period": "4h", "limit": 5},
            )
            if data:
                save(f"futures_ls_top_account_{sym}", data)
            time.sleep(0.3)

        # 7. Binance Futures: top trader long/short position ratio
        print("\n[7] Binance Futures top trader position ratio")
        for sym in SYMBOLS:
            data = call(client,
                f"futures_ls_top_position_{sym}",
                "https://fapi.binance.com/futures/data/topLongShortPositionRatio",
                {"symbol": sym, "period": "4h", "limit": 5},
            )
            if data:
                save(f"futures_ls_top_position_{sym}", data)
            time.sleep(0.3)

        # 8. Binance Futures: premium index (mark price / index price)
        print("\n[8] Binance Futures premium index (mark/index price)")
        for sym in SYMBOLS:
            data = call(client,
                f"futures_premium_{sym}",
                "https://fapi.binance.com/fapi/v1/premiumIndex",
                {"symbol": sym},
            )
            if data:
                save(f"futures_premium_{sym}", data)
                print(f"       Keys: {list(data.keys())}")
            time.sleep(0.3)

        # 9. Fear & Greed Index
        print("\n[9] Alternative.me Fear & Greed Index")
        data = call(client,
            "fear_greed_full",
            "https://api.alternative.me/fng/",
            {"limit": 10},
        )
        if data:
            save("fear_greed_full", data)
            if "data" in data and data["data"]:
                print(f"       Row keys: {list(data['data'][0].keys())}")
        time.sleep(0.5)

        # 10. CoinGecko: global market data (BTC dominance)
        print("\n[10] CoinGecko global market data (BTC dominance)")
        cg_headers = {}
        cg_key = ENV.get("COINGECKO_API_KEY", "")
        if cg_key:
            cg_headers["x-cg-demo-api-key"] = cg_key
        data = call(client,
            "coingecko_global",
            "https://api.coingecko.com/api/v3/global",
            headers=cg_headers,
        )
        if data:
            save("coingecko_global", data)
            if "data" in data:
                btc_dom = data["data"].get("market_cap_percentage", {}).get("btc")
                if btc_dom is not None:
                    print(f"       BTC dominance: {btc_dom:.2f}%")
        time.sleep(0.5)

        # 11. Messari: news feed
        print("\n[11] Messari news")
        if not MESSARI_KEY:
            print("  [--] MESSARI_API_KEY not set in .env - skipping")
            results.append({
                "endpoint": "messari_news",
                "status": "SKIP",
                "ok": False,
                "note": "MESSARI_API_KEY missing from .env",
            })
        else:
            messari_headers = {"x-messari-api-key": MESSARI_KEY}
            data = call(client,
                "messari_news_feed",
                "https://data.messari.io/api/v1/news",
                {"limit": 10},
                messari_headers,
            )
            if data:
                save("messari_news_feed", data)
                if "data" in data and data["data"]:
                    print(f"       Row keys: {list(data['data'][0].keys())}")
            time.sleep(0.4)

            for sym in ["BTCUSDT", "ETHUSDT"]:
                slug = COIN_SLUGS[sym]
                data = call(client,
                    f"messari_news_{sym}",
                    f"https://data.messari.io/api/v1/news/{slug}",
                    {"limit": 5},
                    messari_headers,
                )
                if data:
                    save(f"messari_news_{sym}", data)
                time.sleep(0.5)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    ok_count = sum(1 for r in results if r["ok"])
    total = len(results)
    print(f"  {ok_count}/{total} endpoints returned HTTP 200")

    failures = [r for r in results if not r["ok"]]
    if failures:
        print("\n  FAILURES / NOTES:")
        for f in failures:
            print(f"    [{f['status']}] {f['endpoint']}: {f['note']}")
    else:
        print("  All endpoints OK!")

    save("_discovery_summary", results)
    print(f"\n  Fixtures saved to: {FIXTURES}")
    print("Done. Paste this output to the AI to continue Stage 1.")


if __name__ == "__main__":
    main()
