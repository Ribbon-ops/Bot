"""
backtest.py

Offline backtester. Replays a historical CSV of candles (from
fetch_historical_data.py) through the EMA9/EMA21 + RSI scalping strategy,
simulating entries/exits with a realistic spread cost, and reports honest
performance stats.

This does NOT connect to any live service -- it's pure historical replay,
so you can iterate on strategy parameters quickly and cheaply before ever
touching a demo account.

Usage:
    python backtest.py data/XAUUSD_5min_history.csv

Optional environment variables:
    SPREAD_PIPS   - simulated spread cost per trade, in pips. Default 15
                    (a conservative/realistic assumption for gold -- see
                    README for why this matters so much for scalping).
    PIP_SIZE      - price movement counted as 1 pip. Default 0.1 (gold).
    TP_PIPS       - take-profit distance. Default 15.
    SL_PIPS       - stop-loss distance. Default 10.
    EMA_FAST      - default 9.
    EMA_SLOW      - default 21.
    RSI_PERIOD    - default 14.
"""

import os
import sys

import numpy as np
import pandas as pd

SPREAD_PIPS = float(os.getenv("SPREAD_PIPS", "15"))
PIP_SIZE = float(os.getenv("PIP_SIZE", "0.1"))
TP_PIPS = float(os.getenv("TP_PIPS", "15"))
SL_PIPS = float(os.getenv("SL_PIPS", "10"))
EMA_FAST = int(os.getenv("EMA_FAST", "9"))
EMA_SLOW = int(os.getenv("EMA_SLOW", "21"))
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))


def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    result[(avg_loss == 0) & (avg_gain > 0)] = 100
    result[(avg_loss == 0) & (avg_gain == 0)] = 50
    return result


def load_candles(filepath):
    df = pd.read_csv(filepath)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    return df


def compute_indicators(df):
    df["ema_fast"] = ema(df["close"], EMA_FAST)
    df["ema_slow"] = ema(df["close"], EMA_SLOW)
    df["rsi"] = rsi(df["close"], RSI_PERIOD)
    return df


def run_backtest(df):
    """
    Walks through candles bar-by-bar. When flat, checks for an entry signal.
    When in a trade, checks the CURRENT bar's high/low to see if TP or SL
    would have been touched (uses high/low, not just close, since price
    could have spiked through a level within the bar).

    Spread is applied as an entry cost: on BUY, entry price = close + spread;
    on SELL, entry price = close - spread. This is a simplification (real
    spread also affects the exit) but errs conservative, which is the right
    direction for a strategy self-assessment.
    """
    trades = []
    position = None  # None, or dict with direction/entry/sl/tp/entry_index

    for i in range(max(EMA_SLOW, RSI_PERIOD) + 1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        if pd.isna(row["rsi"]) or pd.isna(prev["ema_fast"]) or pd.isna(prev["ema_slow"]):
            continue

        if position is not None:
            direction = position["direction"]
            if direction == "BUY":
                hit_tp = row["high"] >= position["tp"]
                hit_sl = row["low"] <= position["sl"]
            else:
                hit_tp = row["low"] <= position["tp"]
                hit_sl = row["high"] >= position["sl"]

            # Conservative assumption: if both TP and SL could have been hit
            # in the same bar, assume the worse outcome (SL) actually happened,
            # since we don't have intra-bar order -- this avoids overstating results.
            if hit_sl:
                exit_price = position["sl"]
                outcome = "LOSS"
            elif hit_tp:
                exit_price = position["tp"]
                outcome = "WIN"
            else:
                continue  # still open, move to next bar

            pips = (exit_price - position["entry"]) / PIP_SIZE if direction == "BUY" \
                else (position["entry"] - exit_price) / PIP_SIZE

            trades.append({
                "entry_time": position["entry_time"],
                "exit_time": row["datetime"],
                "direction": direction,
                "entry": position["entry"],
                "exit": exit_price,
                "outcome": outcome,
                "pips": pips,
            })
            position = None
            continue

        # Flat -- check for entry signal
        crossed_up = prev["ema_fast"] <= prev["ema_slow"] and row["ema_fast"] > row["ema_slow"]
        crossed_down = prev["ema_fast"] >= prev["ema_slow"] and row["ema_fast"] < row["ema_slow"]

        signal_dir = None
        if crossed_up and row["rsi"] < 70:
            signal_dir = "BUY"
        elif crossed_down and row["rsi"] > 30:
            signal_dir = "SELL"

        if signal_dir is None:
            continue

        if signal_dir == "BUY":
            entry = row["close"] + SPREAD_PIPS * PIP_SIZE
            sl = entry - SL_PIPS * PIP_SIZE
            tp = entry + TP_PIPS * PIP_SIZE
        else:
            entry = row["close"] - SPREAD_PIPS * PIP_SIZE
            sl = entry + SL_PIPS * PIP_SIZE
            tp = entry - TP_PIPS * PIP_SIZE

        position = {
            "direction": signal_dir, "entry": entry, "sl": sl, "tp": tp,
            "entry_time": row["datetime"],
        }

    return trades


def summarize(trades):
    if not trades:
        print("No trades were generated by this strategy on this data.")
        return

    total = len(trades)
    wins = [t for t in trades if t["outcome"] == "WIN"]
    losses = [t for t in trades if t["outcome"] == "LOSS"]
    win_rate = len(wins) / total * 100

    total_pips = sum(t["pips"] for t in trades)
    avg_win_pips = sum(t["pips"] for t in wins) / len(wins) if wins else 0
    avg_loss_pips = sum(t["pips"] for t in losses) / len(losses) if losses else 0

    gross_win = sum(t["pips"] for t in wins)
    gross_loss = abs(sum(t["pips"] for t in losses))
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")

    # Max drawdown in pips, walking the cumulative pip curve
    cum = 0
    peak = 0
    max_dd = 0
    for t in trades:
        cum += t["pips"]
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    print(f"\n{'='*50}")
    print(f"BACKTEST RESULTS")
    print(f"{'='*50}")
    print(f"Total trades:       {total}")
    print(f"Win rate:           {win_rate:.1f}% ({len(wins)}W / {len(losses)}L)")
    print(f"Total pips:         {total_pips:+.1f}")
    print(f"Avg win:            {avg_win_pips:+.1f} pips")
    print(f"Avg loss:           {avg_loss_pips:+.1f} pips")
    print(f"Profit factor:      {profit_factor:.2f}  (>1.0 = gross wins exceed gross losses)")
    print(f"Max drawdown:       {max_dd:.1f} pips (worst peak-to-trough)")
    print(f"Spread cost used:   {SPREAD_PIPS} pips/trade")
    print(f"TP / SL:            {TP_PIPS} / {SL_PIPS} pips")
    print(f"{'='*50}")

    if profit_factor < 1.0:
        print("\n⚠️  Profit factor below 1.0 -- this strategy configuration LOSES")
        print("   money on this historical data, even before considering that")
        print("   live spreads/slippage are often worse than backtest assumptions.")
    elif total < 30:
        print(f"\n⚠️  Only {total} trades -- too small a sample to draw real conclusions.")
        print("   Consider a longer history period or a less restrictive strategy.")


def main():
    if len(sys.argv) < 2:
        print("Usage: python backtest.py <path_to_historical_csv>")
        sys.exit(1)

    filepath = sys.argv[1]
    df = load_candles(filepath)
    df = compute_indicators(df)
    trades = run_backtest(df)
    summarize(trades)

    # Save trade log for inspection
    if trades:
        out_path = filepath.replace(".csv", "_backtest_trades.csv")
        pd.DataFrame(trades).to_csv(out_path, index=False)
        print(f"\nFull trade log saved to {out_path}")


if __name__ == "__main__":
    main()
