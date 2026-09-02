"""
triangular_scanner.py

PAPER MODE ONLY -- this script does not place any real orders and needs no
API keys. It reads Binance's public market data, automatically discovers
EVERY possible triangular arbitrage loop through USDT (using all currently
tradable coins, old and new), and logs how often/how large a theoretical
profitable spread appears after fees.

Read this before trusting any numbers it produces:
    Real triangular arbitrage windows on Binance typically close in well
    under a second. This script runs on a cron schedule (every few minutes),
    so it CANNOT actually capture these opportunities live -- by the time it
    runs, the prices have moved on. What it's good for is measuring how
    often and how large these spreads appear over time.
    It is not a live trading signal.

How triangle discovery works:
    1. Fetch Binance's full list of tradable symbols (exchangeInfo).
    2. Find every asset X that has a direct USDT pair (X/USDT).
    3. For every pair of such assets (X, Y), check if a direct X/Y pair also
       exists. If so, USDT -> X -> Y -> USDT is a valid triangle.
    4. This naturally includes brand-new listings (as soon as Binance adds
       the pair) and long-established coins alike -- nothing is hardcoded.

Liquidity safety filter:
    Newly-listed or low-volume coins can have wide, unreliable bid/ask
    spreads that make a triangle LOOK profitable purely because the quote
    is stale or thin, not because a real opportunity exists. Any leg with
    a bid/ask spread wider than MAX_LEG_SPREAD_PCT is treated as unusable
    and that triangle is skipped, to cut down on this false-positive noise.

Env vars (all optional):
    FEE_RATE            - per-trade taker fee as a decimal. Default 0.001 (0.1%).
                           Use 0.00075 if you have BNB fee discount enabled.
    MIN_PROFIT_PCT       - minimum net profit % to log as an "opportunity".
                           Default 0.05 (ignores noise near breakeven).
    MAX_LEG_SPREAD_PCT   - skip any leg whose bid/ask spread exceeds this %.
                           Default 2.0.
"""

import csv
import os
from datetime import datetime, timezone

import requests

FEE_RATE = float(os.getenv("FEE_RATE", "0.001"))
MIN_PROFIT_PCT = float(os.getenv("MIN_PROFIT_PCT", "0.05"))
MAX_LEG_SPREAD_PCT = float(os.getenv("MAX_LEG_SPREAD_PCT", "2.0"))

OPPORTUNITIES_LOG = "opportunities.csv"
SCAN_LOG = "scan_log.csv"

# data-api.binance.vision is Binance's dedicated public market-data mirror.
# GitHub Actions runners are hosted in US datacenters, and api.binance.com
# blocks requests from US IPs (HTTP 451) regardless of where you personally
# are -- this mirror serves the same data without that restriction. The
# other two are kept as fallbacks in case one endpoint has a hiccup.
EXCHANGE_INFO_URLS = [
    "https://data-api.binance.vision/api/v3/exchangeInfo",
    "https://api1.binance.com/api/v3/exchangeInfo",
    "https://api.binance.com/api/v3/exchangeInfo",
]
BOOK_TICKER_URLS = [
    "https://data-api.binance.vision/api/v3/ticker/bookTicker",
    "https://api1.binance.com/api/v3/ticker/bookTicker",
    "https://api.binance.com/api/v3/ticker/bookTicker",
]


def fetch_with_fallback(urls, timeout=15):
    last_error = None
    for url in urls:
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_error = e
            print(f"  (fetch from {url} failed: {e}, trying next endpoint...)")
            continue
    raise RuntimeError(f"All endpoints failed. Last error: {last_error}")


def fetch_exchange_info():
    """Returns {symbol: (base_asset, quote_asset)} for every currently
    tradable spot pair on Binance -- old and newly-listed alike."""
    data = fetch_with_fallback(EXCHANGE_INFO_URLS)
    pairs = {}
    for s in data.get("symbols", []):
        if s.get("status") != "TRADING":
            continue
        if not s.get("isSpotTradingAllowed", True):
            continue
        pairs[s["symbol"]] = (s["baseAsset"], s["quoteAsset"])
    return pairs


def fetch_order_books():
    """One request gets best bid/ask for every symbol on Binance."""
    data = fetch_with_fallback(BOOK_TICKER_URLS)
    book = {}
    for row in data:
        try:
            book[row["symbol"]] = {
                "bid": float(row["bidPrice"]),
                "ask": float(row["askPrice"]),
            }
        except (KeyError, ValueError):
            continue
    return book


def discover_triangles(pairs):
    """
    Dynamically builds every valid USDT -> X -> Y -> USDT triangle from the
    current set of tradable pairs. Returns a list of (path, symbols, hops)
    where hops is a small {symbol: (base, quote)} lookup for that triangle.
    """
    usdt_pair = {}   # asset -> symbol, for X/USDT pairs
    all_pairs = {}   # frozenset({assetA, assetB}) -> (symbol, base, quote)

    for symbol, (base, quote) in pairs.items():
        all_pairs[frozenset((base, quote))] = (symbol, base, quote)
        if quote == "USDT":
            usdt_pair[base] = symbol
        elif base == "USDT":
            usdt_pair[quote] = symbol  # rare, but handle USDT-as-base too

    assets = sorted(usdt_pair.keys())
    triangles = []
    seen = set()

    for i, x in enumerate(assets):
        for y in assets[i + 1:]:
            key = frozenset((x, y))
            if key in seen or key not in all_pairs:
                continue
            seen.add(key)
            cross_symbol, cross_base, cross_quote = all_pairs[key]
            symbols = [usdt_pair[x], cross_symbol, usdt_pair[y]]
            triangles.append((["USDT", x, y, "USDT"], symbols))

    return triangles


def leg_spread_ok(price):
    if price["bid"] <= 0 or price["ask"] <= 0:
        return False
    spread_pct = (price["ask"] - price["bid"]) / price["bid"] * 100
    return spread_pct <= MAX_LEG_SPREAD_PCT


def walk_triangle(path, symbols, book, hops):
    """
    Walk a triangle path using the given symbols for each hop. Returns the
    ending amount starting from 1 unit of path[0], or None if any leg is
    missing, delisted mid-run, or fails the liquidity sanity filter.
    """
    amount = 1.0
    for i, symbol in enumerate(symbols):
        if symbol not in book or symbol not in hops:
            return None
        price = book[symbol]
        if not leg_spread_ok(price):
            return None

        base, quote = hops[symbol]
        from_asset, to_asset = path[i], path[i + 1]

        if from_asset == quote and to_asset == base:
            amount = amount / price["ask"]
        elif from_asset == base and to_asset == quote:
            amount = amount * price["bid"]
        else:
            return None

        amount = amount * (1 - FEE_RATE)

    return amount


def log_row(filename, fieldnames, row):
    file_exists = os.path.exists(filename)
    with open(filename, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def main():
    timestamp = datetime.now(timezone.utc).isoformat()

    pairs = fetch_exchange_info()
    book = fetch_order_books()
    triangles = discover_triangles(pairs)

    print(f"Discovered {len(triangles)} triangles from {len(pairs)} tradable pairs.")

    results = []
    for path, symbols in triangles:
        for direction_path, direction_symbols in (
            (path, symbols),
            (list(reversed(path)), list(reversed(symbols))),
        ):
            name = "->".join(direction_path)
            ending_amount = walk_triangle(direction_path, direction_symbols, book, pairs)
            if ending_amount is None:
                continue
            profit_pct = (ending_amount - 1.0) * 100
            results.append({
                "name": name,
                "symbols": ",".join(direction_symbols),
                "ending_amount": ending_amount,
                "profit_pct": profit_pct,
            })

    if not results:
        print("No valid triangles could be evaluated this run.")
        return

    results.sort(key=lambda r: r["profit_pct"], reverse=True)
    best = results[0]

    scan_fields = ["timestamp_utc", "triangles_discovered", "directions_evaluated",
                   "best_triangle", "best_profit_pct", "fee_rate"]
    log_row(SCAN_LOG, scan_fields, {
        "timestamp_utc": timestamp,
        "triangles_discovered": len(triangles),
        "directions_evaluated": len(results),
        "best_triangle": best["name"],
        "best_profit_pct": round(best["profit_pct"], 5),
        "fee_rate": FEE_RATE,
    })

    print(f"Evaluated {len(results)} triangle directions. Best: {best['name']} "
          f"= {best['profit_pct']:.4f}% net of fees.")

    opp_fields = ["timestamp_utc", "triangle", "symbols_used", "net_profit_pct", "fee_rate"]
    opportunity_count = 0
    for r in results:
        if r["profit_pct"] > MIN_PROFIT_PCT:
            log_row(OPPORTUNITIES_LOG, opp_fields, {
                "timestamp_utc": timestamp,
                "triangle": r["name"],
                "symbols_used": r["symbols"],
                "net_profit_pct": round(r["profit_pct"], 5),
                "fee_rate": FEE_RATE,
            })
            opportunity_count += 1

    if opportunity_count:
        print(f"  Logged {opportunity_count} opportunities above {MIN_PROFIT_PCT}% net profit.")


if __name__ == "__main__":
    main()
