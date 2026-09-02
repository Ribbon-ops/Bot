"""
triangular_scanner.py

PAPER MODE ONLY -- this script does not place any real orders and needs no
API keys. It reads Binance's public order book data, scans several
triangular arbitrage loops, and logs how often/how large a theoretical
profitable spread appears after fees.

Read this before trusting any numbers it produces:
    Real triangular arbitrage windows on Binance typically close in well
    under a second. This script runs on a cron schedule (every few minutes),
    so it CANNOT actually capture these opportunities live -- by the time it
    runs, the prices have moved on. What it's good for is measuring how
    often and how large these spreads appear over time, which tells you
    whether pursuing real-time execution would even be worth the effort.
    It is not a live trading signal.

How it works:
    1. One API call fetches best bid/ask for every symbol on Binance.
    2. For each triangle (three assets forming a loop, e.g. USDT->BTC->ETH->USDT)
       in both directions, it walks the loop starting from 1 unit of the
       first asset, applying the appropriate bid/ask price at each hop and
       a trading fee, and sees what it ends up with.
    3. If ending amount > starting amount (after fees), that's a theoretical
       arbitrage opportunity. It's logged to opportunities.csv.
    4. Every run's best result (whether profitable or not) is logged to
       scan_log.csv, so you have a continuous record the bot is alive.

Env vars (all optional):
    FEE_RATE            - per-trade taker fee as a decimal. Default 0.001 (0.1%).
                           Use 0.00075 if you have BNB fee discount enabled.
    MIN_PROFIT_PCT      - minimum net profit % to log as an "opportunity".
                           Default 0.0 (log anything net-positive).
"""

import csv
import os
from datetime import datetime, timezone

import requests

BOOK_TICKER_URL = "https://api.binance.com/api/v3/ticker/bookTicker"

FEE_RATE = float(os.getenv("FEE_RATE", "0.001"))
MIN_PROFIT_PCT = float(os.getenv("MIN_PROFIT_PCT", "0.0"))

OPPORTUNITIES_LOG = "opportunities.csv"
SCAN_LOG = "scan_log.csv"

# Each hop names the Binance symbol and which asset is the "base" (the thing
# you're buying/selling) vs. the "quote" (what you're pricing it in).
# e.g. for BTCUSDT: base=BTC, quote=USDT. Buying BTC with USDT uses the ask
# price; selling BTC for USDT uses the bid price.
HOPS = {
    "BTCUSDT": ("BTC", "USDT"),
    "ETHUSDT": ("ETH", "USDT"),
    "BNBUSDT": ("BNB", "USDT"),
    "ETHBTC": ("ETH", "BTC"),
    "BNBBTC": ("BNB", "BTC"),
    "BNBETH": ("BNB", "ETH"),
    "SOLUSDT": ("SOL", "USDT"),
    "SOLBTC": ("SOL", "BTC"),
    "XRPUSDT": ("XRP", "USDT"),
    "XRPBTC": ("XRP", "BTC"),
    "ADAUSDT": ("ADA", "USDT"),
    "ADABTC": ("ADA", "BTC"),
    "LTCUSDT": ("LTC", "USDT"),
    "LTCBTC": ("LTC", "BTC"),
    "DOGEUSDT": ("DOGE", "USDT"),
    "DOGEBTC": ("DOGE", "BTC"),
}

# Base triangles as asset cycles. Each will be scanned in both directions
# (forward and reverse) using the same three pairs.
TRIANGLE_CYCLES = [
    (["USDT", "BTC", "ETH", "USDT"], ["BTCUSDT", "ETHBTC", "ETHUSDT"]),
    (["USDT", "BTC", "BNB", "USDT"], ["BTCUSDT", "BNBBTC", "BNBUSDT"]),
    (["USDT", "ETH", "BNB", "USDT"], ["ETHUSDT", "BNBETH", "BNBUSDT"]),
    (["USDT", "BTC", "SOL", "USDT"], ["BTCUSDT", "SOLBTC", "SOLUSDT"]),
    (["USDT", "BTC", "XRP", "USDT"], ["BTCUSDT", "XRPBTC", "XRPUSDT"]),
    (["USDT", "BTC", "ADA", "USDT"], ["BTCUSDT", "ADABTC", "ADAUSDT"]),
    (["USDT", "BTC", "LTC", "USDT"], ["BTCUSDT", "LTCBTC", "LTCUSDT"]),
    (["USDT", "BTC", "DOGE", "USDT"], ["BTCUSDT", "DOGEBTC", "DOGEUSDT"]),
]


def fetch_order_books():
    """One request gets best bid/ask for every symbol on Binance."""
    resp = requests.get(BOOK_TICKER_URL, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    book = {}
    for row in data:
        book[row["symbol"]] = {
            "bid": float(row["bidPrice"]),
            "ask": float(row["askPrice"]),
        }
    return book


def walk_triangle(path, symbols, book):
    """
    Walk a triangle path (e.g. USDT->BTC->ETH->USDT) using the given symbols
    for each hop. Returns the ending amount starting from 1 unit of path[0],
    or None if any required symbol is missing from the order book snapshot
    (e.g. a pair got delisted).
    """
    amount = 1.0
    for i, symbol in enumerate(symbols):
        if symbol not in book or symbol not in HOPS:
            return None
        base, quote = HOPS[symbol]
        from_asset, to_asset = path[i], path[i + 1]
        price = book[symbol]

        if from_asset == quote and to_asset == base:
            # buying base with quote -> pay the ask price
            amount = amount / price["ask"]
        elif from_asset == base and to_asset == quote:
            # selling base for quote -> receive the bid price
            amount = amount * price["bid"]
        else:
            # path doesn't match this symbol's base/quote -- bad triangle definition
            return None

        amount = amount * (1 - FEE_RATE)  # apply trading fee for this hop

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
    book = fetch_order_books()

    results = []
    for path, symbols in TRIANGLE_CYCLES:
        for direction_path, direction_symbols in (
            (path, symbols),
            (list(reversed(path)), list(reversed(symbols))),
        ):
            name = "->".join(direction_path)
            ending_amount = walk_triangle(direction_path, direction_symbols, book)
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
        print("No valid triangles could be evaluated this run (missing symbols?).")
        return

    results.sort(key=lambda r: r["profit_pct"], reverse=True)
    best = results[0]

    scan_fields = ["timestamp_utc", "triangles_scanned", "best_triangle", "best_profit_pct", "fee_rate"]
    log_row(SCAN_LOG, scan_fields, {
        "timestamp_utc": timestamp,
        "triangles_scanned": len(results),
        "best_triangle": best["name"],
        "best_profit_pct": round(best["profit_pct"], 5),
        "fee_rate": FEE_RATE,
    })

    print(f"Scanned {len(results)} triangle directions. Best: {best['name']} "
          f"= {best['profit_pct']:.4f}% net of fees.")

    opp_fields = ["timestamp_utc", "triangle", "symbols_used", "net_profit_pct", "fee_rate"]
    for r in results:
        if r["profit_pct"] > MIN_PROFIT_PCT:
            log_row(OPPORTUNITIES_LOG, opp_fields, {
                "timestamp_utc": timestamp,
                "triangle": r["name"],
                "symbols_used": r["symbols"],
                "net_profit_pct": round(r["profit_pct"], 5),
                "fee_rate": FEE_RATE,
            })
            print(f"  OPPORTUNITY: {r['name']} -> {r['profit_pct']:.4f}% net profit")


if __name__ == "__main__":
    main()
