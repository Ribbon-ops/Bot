"""
signal_scanner.py

PAPER SIGNAL TRACKING for forex scalping -- no real orders are placed.
This script:
    1. Connects to your Headway account via MetaApi (read-only use: candles
       and current prices only -- it never calls any order-placing method).
    2. For each configured symbol, checks M5 candles for an EMA9/EMA21
       crossover + RSI(14) filter (the same logic style as the earlier
       trading_bot.py, but signal-only).
    3. If there's no already-open signal for that symbol, and a new signal
       fires, it records an entry price, stop-loss, and take-profit and
       saves it as "open."
    4. If there IS an open signal for that symbol, it checks whether the
       current price would have hit the take-profit or stop-loss, and if
       so, closes it out and logs the hypothetical pips/percent result.
    5. State (which signals are currently open) persists in open_signals.json,
       committed back to the repo each run so it survives between GitHub
       Actions runs.

Required environment variables (same secrets as test_connection.py):
    METAAPI_TOKEN
    METAAPI_ACCOUNT_ID

Optional:
    SYMBOLS          - comma-separated list. Default "EURUSD,GBPUSD,USDJPY,XAUUSD"
    TIMEFRAME        - default "5m"

IMPORTANT ON GOLD (XAUUSD):
    Pip/point conventions for gold vary by broker. The defaults below
    (pip = 0.1, i.e. a $0.10 move) are a common convention but NOT
    guaranteed to match Headway's exact contract specification. Before
    trusting these numbers, open Headway's symbol specification for
    XAUUSD (or ask their support) and adjust SYMBOL_CONFIG below if needed.
    The same caution applies loosely to any unusual pairs you add.

This script never calls create_market_buy_order / create_market_sell_order
or any other order-placing method -- it only reads candles and prices.
"""

import asyncio
import csv
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from metaapi_cloud_sdk import MetaApi

TOKEN = os.getenv("METAAPI_TOKEN")
ACCOUNT_ID = os.getenv("METAAPI_ACCOUNT_ID")
SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "EURUSD,GBPUSD,USDJPY,XAUUSD").split(",")]
TIMEFRAME = os.getenv("TIMEFRAME", "5m")
CANDLE_COUNT = 100

OPEN_SIGNALS_FILE = "open_signals.json"
SIGNALS_LOG = "signals_log.csv"       # every signal fired, entry conditions
CLOSED_TRADES_LOG = "closed_trades.csv"  # every signal resolved, win/loss + pips

# Per-symbol trading parameters. pip_size = the price movement that counts
# as "1 pip" for that symbol. tp_pips/sl_pips = target distances in pips.
# VERIFY XAUUSD against your Headway symbol spec -- see note above.
SYMBOL_CONFIG = {
    "EURUSD": {"pip_size": 0.0001, "tp_pips": 5, "sl_pips": 3},
    "GBPUSD": {"pip_size": 0.0001, "tp_pips": 5, "sl_pips": 3},
    "USDJPY": {"pip_size": 0.01,   "tp_pips": 5, "sl_pips": 3},
    "XAUUSD": {"pip_size": 0.1,    "tp_pips": 15, "sl_pips": 10},  # VERIFY vs Headway spec
}
DEFAULT_CONFIG = {"pip_size": 0.0001, "tp_pips": 5, "sl_pips": 3}


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))

    # avg_loss == 0 with real gains -> RSI is maximally overbought (100),
    # not undefined. avg_loss == 0 AND avg_gain == 0 -> flat market -> 50.
    result[(avg_loss == 0) & (avg_gain > 0)] = 100
    result[(avg_loss == 0) & (avg_gain == 0)] = 50
    return result


def load_open_signals():
    if os.path.exists(OPEN_SIGNALS_FILE):
        with open(OPEN_SIGNALS_FILE) as f:
            return json.load(f)
    return {}


def save_open_signals(data):
    with open(OPEN_SIGNALS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def log_row(filename, fieldnames, row):
    file_exists = os.path.exists(filename)
    with open(filename, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


async def get_connection():
    api = MetaApi(TOKEN)
    account = await api.metatrader_account_api.get_account(ACCOUNT_ID)
    if account.state != "DEPLOYED":
        await account.deploy()
    await account.wait_connected()
    connection = account.get_rpc_connection()
    await connection.connect()
    await connection.wait_synchronized()
    return connection


def check_closed_out(symbol, signal, current_price):
    """Returns ('WIN'|'LOSS'|None, exit_price)."""
    direction = signal["direction"]
    tp, sl = signal["take_profit"], signal["stop_loss"]

    if direction == "BUY":
        if current_price >= tp:
            return "WIN", tp
        if current_price <= sl:
            return "LOSS", sl
    else:  # SELL
        if current_price <= tp:
            return "WIN", tp
        if current_price >= sl:
            return "LOSS", sl

    return None, None


async def process_symbol(connection, symbol, open_signals, timestamp):
    cfg = SYMBOL_CONFIG.get(symbol, DEFAULT_CONFIG)
    pip_size = cfg["pip_size"]

    price_info = await connection.get_symbol_price(symbol)
    bid, ask = float(price_info["bid"]), float(price_info["ask"])
    mid_price = (bid + ask) / 2

    # --- Case 1: there's an open signal for this symbol -- check if it closed ---
    if symbol in open_signals:
        signal = open_signals[symbol]
        check_price = bid if signal["direction"] == "BUY" else ask
        outcome, exit_price = check_closed_out(symbol, signal, check_price)

        if outcome:
            entry = signal["entry_price"]
            pips = (exit_price - entry) / pip_size if signal["direction"] == "BUY" \
                else (entry - exit_price) / pip_size
            pct_move = (exit_price - entry) / entry * 100 if signal["direction"] == "BUY" \
                else (entry - exit_price) / entry * 100

            log_row(CLOSED_TRADES_LOG,
                    ["timestamp_utc", "symbol", "direction", "entry_price", "exit_price",
                     "outcome", "pips", "pct_move", "opened_at"],
                    {
                        "timestamp_utc": timestamp, "symbol": symbol,
                        "direction": signal["direction"], "entry_price": entry,
                        "exit_price": exit_price, "outcome": outcome,
                        "pips": round(pips, 1), "pct_move": round(pct_move, 4),
                        "opened_at": signal["opened_at"],
                    })
            print(f"  {symbol}: {outcome} closed. {signal['direction']} entry={entry} exit={exit_price} pips={pips:.1f}")
            del open_signals[symbol]
        else:
            print(f"  {symbol}: signal still open ({signal['direction']} from {signal['opened_at']}), price={mid_price:.5f}")
        return  # don't evaluate a new entry the same run a position is open/just closed

    # --- Case 2: no open signal -- evaluate for a new entry ---
    candles = await connection.get_candles(symbol, TIMEFRAME, limit=CANDLE_COUNT)
    if not candles or len(candles) < 30:
        print(f"  {symbol}: not enough candle data, skipping.")
        return

    df = pd.DataFrame(candles)
    df["close"] = df["close"].astype(float)
    df["ema_fast"] = ema(df["close"], 9)
    df["ema_slow"] = ema(df["close"], 21)
    df["rsi"] = rsi(df["close"], 14)

    prev, last = df.iloc[-2], df.iloc[-1]
    last_rsi = last["rsi"]

    if pd.isna(last_rsi) or pd.isna(prev["ema_fast"]) or pd.isna(prev["ema_slow"]):
        print(f"  {symbol}: indicators not warmed up yet, skipping.")
        return

    crossed_up = prev["ema_fast"] <= prev["ema_slow"] and last["ema_fast"] > last["ema_slow"]
    crossed_down = prev["ema_fast"] >= prev["ema_slow"] and last["ema_fast"] < last["ema_slow"]

    signal_dir = None
    if crossed_up and last_rsi < 70:
        signal_dir = "BUY"
    elif crossed_down and last_rsi > 30:
        signal_dir = "SELL"

    if signal_dir is None:
        print(f"  {symbol}: no signal. price={mid_price:.5f} RSI={last_rsi:.1f}")
        return

    entry_price = ask if signal_dir == "BUY" else bid
    if signal_dir == "BUY":
        sl = entry_price - cfg["sl_pips"] * pip_size
        tp = entry_price + cfg["tp_pips"] * pip_size
    else:
        sl = entry_price + cfg["sl_pips"] * pip_size
        tp = entry_price - cfg["tp_pips"] * pip_size

    open_signals[symbol] = {
        "direction": signal_dir,
        "entry_price": entry_price,
        "stop_loss": sl,
        "take_profit": tp,
        "opened_at": timestamp,
    }

    log_row(SIGNALS_LOG,
            ["timestamp_utc", "symbol", "direction", "entry_price", "stop_loss",
             "take_profit", "rsi"],
            {
                "timestamp_utc": timestamp, "symbol": symbol, "direction": signal_dir,
                "entry_price": round(entry_price, 5), "stop_loss": round(sl, 5),
                "take_profit": round(tp, 5), "rsi": round(float(last_rsi), 1),
            })
    print(f"  {symbol}: NEW SIGNAL {signal_dir} entry={entry_price:.5f} SL={sl:.5f} TP={tp:.5f} RSI={last_rsi:.1f}")


async def main():
    if not TOKEN or not ACCOUNT_ID:
        print("ERROR: METAAPI_TOKEN and/or METAAPI_ACCOUNT_ID are not set.")
        sys.exit(1)

    timestamp = datetime.now(timezone.utc).isoformat()
    open_signals = load_open_signals()

    connection = await get_connection()

    for symbol in SYMBOLS:
        try:
            await process_symbol(connection, symbol, open_signals, timestamp)
        except Exception as e:
            print(f"  {symbol}: ERROR -- {e}")

    save_open_signals(open_signals)


if __name__ == "__main__":
    asyncio.run(main())
