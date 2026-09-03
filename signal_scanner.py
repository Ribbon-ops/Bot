import json, os
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf

SYMBOLS = ["XAUUSD","EURUSD","GBPUSD","USDJPY"]
OPEN_FILE = "open_signals.json"
LOG = "signals_log.csv"
CLOSED = "closed_trades.csv"

# FIXED TICKERS - GC=F works for Gold real price
YAHOO_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "XAUUSD": "GC=F"
}

CONFIG = {
    "EURUSD": {"pip":0.0001,"tp":1.5,"sl":4,"sweep":0.8,"max":3},
    "GBPUSD": {"pip":0.0001,"tp":1.5,"sl":4,"sweep":0.8,"max":3},
    "USDJPY": {"pip":0.01,"tp":1.5,"sl":4,"sweep":0.8,"max":3},
    "XAUUSD": {"pip":0.1,"tp":2.5,"sl":6,"sweep":1.2,"max":2},
}

def get_price_and_df(ticker):
    try:
        t = yf.Ticker(ticker)
        # try fast price first
        price = None
        try:
            price = t.fast_info.last_price
        except: pass

        df = yf.download(ticker, period="1d", interval="1m", progress=False, auto_adjust=True)
        if df.empty:
            return None, None

        # fix columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # get price from df if fast_info failed
        if price is None:
            # handle both lower and upper case
            col = "Close" if "Close" in df.columns else "close"
            price = float(df[col].iloc[-1])
        else:
            price = float(price)

        return price, df
    except Exception as e:
        print(f" get_price err {ticker}: {e}")
        return None, None

def main():
    ts = datetime.now(timezone.utc).isoformat()
    opens = {}
    if os.path.exists(OPEN_FILE):
        try:
            with open(OPEN_FILE) as f:
                opens = json.load(f)
        except:
            opens = {}
    for s in SYMBOLS:
        if s not in opens: opens[s] = []
        if isinstance(opens[s], dict): opens[s] = [opens[s]]

    print(f"REAL MARKET FIX {ts}")
    for sym in SYMBOLS:
        cfg = CONFIG[sym]
        ticker = YAHOO_MAP[sym]
        try:
            price, df = get_price_and_df(ticker)
            if price is None or df is None:
                print(f" {sym} ({ticker}): NO DATA - trying fallback")
                # fallback for XAUUSD
                if sym == "XAUUSD":
                    price, df = get_price_and_df("GOLD")
                if price is None:
                    print(f" {sym}: still no data, skip")
                    continue

            # fix column names to lower
            df.columns = [str(c).lower() for c in df.columns]
            if "close" not in df.columns:
                print(f" {sym} cols {df.columns}")
                continue

            cur = float(price)
            print(f" {sym} REAL={cur} len={len(df)}")

            # close logic
            remaining = []
            for tr in opens[sym]:
                entry = float(tr["entry_price"])
                is_buy = tr["direction"] == "BUY"
                profit = (cur - entry) / cfg["pip"] if is_buy else (entry - cur) / cfg["pip"]
                closed = False
                exit_p = cur
                outcome = None
                if is_buy:
                    if cur >= float(tr["take_profit"]): outcome="WIN"; exit_p=float(tr["take_profit"]); closed=True
                    elif cur <= float(tr["stop_loss"]): outcome="LOSS"; exit_p=float(tr["stop_loss"]); closed=True
                    elif profit >= cfg["sweep"]: outcome="WIN"; exit_p=cur; closed=True
                else:
                    if cur <= float(tr["take_profit"]): outcome="WIN"; exit_p=float(tr["take_profit"]); closed=True
                    elif cur >= float(tr["stop_loss"]): outcome="LOSS"; exit_p=float(tr["stop_loss"]); closed=True
                    elif profit >= cfg["sweep"]: outcome="WIN"; exit_p=cur; closed=True

                if closed:
                    pips = (exit_p-entry)/cfg["pip"] if is_buy else (entry-exit_p)/cfg["pip"]
                    import csv
                    ex = os.path.exists(CLOSED)
                    with open(CLOSED,"a",newline="") as f:
                        w=csv.DictWriter(f,fieldnames=["timestamp_utc","symbol","direction","entry_price","exit_price","outcome","pips","opened_at","note"])
                        if not ex: w.writeheader()
                        w.writerow({"timestamp_utc":ts,"symbol":sym,"direction":tr["direction"],"entry_price":entry,"exit_price":exit_p,"outcome":outcome,"pips":round(float(pips),2),"opened_at":tr["opened_at"],"note":"LIVE"})
                    print(f" CLOSED {outcome} {round(pips,2)}p")
                else:
                    tr["current_price"]=cur
                    remaining.append(tr)
            opens[sym]=remaining

            # FORCE OPEN if empty - for $10 test
            if len(opens[sym])==0:
                try:
                    last_close = float(df["close"].iloc[-1])
                    last_open = float(df["open"].iloc[-1])
                    direction = "BUY" if last_close >= last_open else "SELL"
                except:
                    direction = "BUY"

                entry = cur
                sl = entry - cfg["sl"]*cfg["pip"] if direction=="BUY" else entry + cfg["sl"]*cfg["pip"]
                tp = entry + cfg["tp"]*cfg["pip"] if direction=="BUY" else entry - cfg["tp"]*cfg["pip"]
                opens[sym].append({"direction":direction,"entry_price":entry,"stop_loss":sl,"take_profit":tp,"opened_at":ts,"current_price":cur,"buy_stop":0,"sell_stop":0})
                import csv
                ex=os.path.exists(LOG)
                with open(LOG,"a",newline="") as f:
                    w=csv.DictWriter(f,fieldnames=["timestamp_utc","symbol","direction","entry_price","stop_loss","take_profit","buy_stop","sell_stop"])
                    if not ex: w.writeheader()
                    w.writerow({"timestamp_utc":ts,"symbol":sym,"direction":direction,"entry_price":round(entry,5),"stop_loss":round(sl,5),"take_profit":round(tp,5),"buy_stop":0,"sell_stop":0})
                print(f" NEW LIVE {direction} at {cur}")

        except Exception as e:
            print(f" {sym} ERR {e}")
            import traceback
            traceback.print_exc()

    with open(OPEN_FILE,"w") as f:
        json.dump(opens,f,indent=2)

if __name__=="__main__":
    main()
