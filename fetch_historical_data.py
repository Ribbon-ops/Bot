"""
fetch_historical_data.py

Pulls several months of 5-minute historical candles for XAUUSD (gold) and
optionally other symbols from Twelve Data's free API, and saves them as CSV
files for backtesting. Run this ONCE (or occasionally to refresh), not on a
schedule -- it's not meant to run continuously.

Twelve Data's free tier: 800 requests/day, 8/minute. Each request returns
up to 5000 candles. This script paginates backwards in time automatically
and pauses between requests to respect the rate limit.

Required environment variable:
    TWELVEDATA_API_KEY

Optional:
    SYMBOLS       - comma-separated, Twelve Data format. Default "XAU/USD"
    INTERVAL      - default "5min"
    MONTHS_BACK   - how many months of history to pull. Default 3.
"""

import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

API_KEY = os.getenv("TWELVEDATA_API_KEY")
SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "XAU/USD").split(",")]
INTERVAL = os.getenv("INTERVAL", "5min")
MONTHS_BACK = int(os.getenv("MONTHS_BACK", "3"))

BASE_URL = "https://api.twelvedata.com/time_series"
OUTPUT_DIR = "data"
MAX_CANDLES_PER_REQUEST = 5000
SECONDS_BETWEEN_REQUESTS = 8  # stay safely under 8 requests/minute


def fetch_page(symbol, end_date):
    """Fetch up to MAX_CANDLES_PER_REQUEST candles ending at end_date."""
    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "outputsize": MAX_CANDLES_PER_REQUEST,
        "end_date": end_date.strftime("%Y-%m-%d %H:%M:%S"),
        "apikey": API_KEY,
        "format": "JSON",
        "order": "ASC",
    }
    resp = requests.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") == "error":
        raise RuntimeError(f"Twelve Data error for {symbol}: {data.get('message')}")

    values = data.get("values", [])
    return values


def fetch_symbol_history(symbol):
    print(f"Fetching {MONTHS_BACK} months of {INTERVAL} history for {symbol}...")
    cutoff = datetime.now(timezone.utc) - timedelta(days=MONTHS_BACK * 30)
    end_date = datetime.now(timezone.utc)
    all_candles = []
    seen_timestamps = set()

    while end_date > cutoff:
        page = fetch_page(symbol, end_date)
        if not page:
            print(f"  No more data returned, stopping at {end_date.date()}.")
            break

        new_count = 0
        for candle in page:
            ts = candle["datetime"]
            if ts not in seen_timestamps:
                seen_timestamps.add(ts)
                all_candles.append(candle)
                new_count += 1

        print(f"  Got {len(page)} candles ({new_count} new), oldest so far: {min(c['datetime'] for c in page)}")

        oldest_in_page = min(datetime.strptime(c["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) for c in page)
        if oldest_in_page >= end_date:
            print("  No progress made (page didn't move backward), stopping to avoid infinite loop.")
            break
        end_date = oldest_in_page - timedelta(minutes=1)

        if len(page) < MAX_CANDLES_PER_REQUEST:
            print("  Received fewer candles than max page size -- reached start of available history.")
            break

        time.sleep(SECONDS_BETWEEN_REQUESTS)

    all_candles.sort(key=lambda c: c["datetime"])
    return all_candles


def save_to_csv(symbol, candles):
    if not candles:
        print(f"  No candles to save for {symbol}.")
        return

    safe_name = symbol.replace("/", "")
    filepath = os.path.join(OUTPUT_DIR, f"{safe_name}_{INTERVAL}_history.csv")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["datetime", "open", "high", "low", "close"])
        writer.writeheader()
        for c in candles:
            writer.writerow({
                "datetime": c["datetime"],
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
            })

    print(f"  Saved {len(candles)} candles to {filepath}")


def main():
    if not API_KEY:
        print("ERROR: TWELVEDATA_API_KEY is not set.")
        sys.exit(1)

    for symbol in SYMBOLS:
        candles = fetch_symbol_history(symbol)
        save_to_csv(symbol, candles)


if __name__ == "__main__":
    main()
