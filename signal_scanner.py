import json, os, requests
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf

SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "EURUSD,GBPUSD,USDJPY,XAUUSD").split(",")]
TIMEFRAME = os.getenv("TIMEFRAME", "1m")

OPEN_FILE = "open_signals.json"
LOG = "signals_log.csv"
CLOSED = "closed_trades.csv"

# REAL SPOT MAP - matches TradingView
YAHOO_MAP = {"EURUSD":"EURUSD=X","GBPUSD":"GBPUSD=X","USDJPY":"USDJPY=X","XAUUSD":"XAUUSD=X"}

CONFIG = {
    "EURUSD": {"pip":0.0001,"tp":1.5,"sl":4,"sweep_tp":0.8,"max":5},
    "GBPUSD": {"pip":0.0001,"tp":1.5,"sl":4,"sweep_tp":0.8,"max":5},
    "USDJPY": {"pip":0.01,"tp":1.5,"sl":4,"sweep_tp":0.8,"max":5},
    "XAUUSD": {"pip":0.1,"tp":3.0,"sl":6,"sweep_tp":1.2,"max":3},
}
DEF = {"pip":0.0001,"tp":1.5,"sl":4,"sweep_tp":0.8,"max":5}

def get_real_price(symbol):
    # Try 3 real sources, no guessing
    ticker=YAHOO_MAP.get(symbol,symbol)
    try:
        # 1. Yahoo fast_info = REAL TIME
        t=yf.Ticker(ticker)
        price=t.fast_info.last_price
        if price and price>0:
            return float(price)
    except: pass
    try:
        # 2. Yahoo history last close
        df=yf.download(ticker, period="1d", interval="1m", progress=False)
        if not df.empty:
            return float(df["Close"].iloc[-1])
    except: pass
    try:
        # 3. exchangerate.host live
        if "USD" in symbol:
            base=symbol[:3]
            r=requests.get(f"https://api.exchangerate.host/convert?from={base}&to=USD", timeout=5).json()
            if "result" in r:
                return float(r["result"])
    except: pass
    return None

def load_opens():
    if os.path.exists(OPEN_FILE):
        try:
            with open(OPEN_FILE) as f:
                data=json.load(f)
                for k,v in data.items():
                    if isinstance(v,dict): data[k]=[v]
                return data
        except: pass
    return {s: [] for s in SYMBOLS}

def save_opens(d):
    with open(OPEN_FILE,"w") as f:
        json.dump(d,f,indent=2)

def log_row(fn, fields, row):
    ex=os.path.exists(fn)
    import csv
    with open(fn,"a",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        if not ex: w.writeheader()
        w.writerow(row)

def get_candles(sym, tf):
    ticker=YAHOO_MAP.get(sym,sym)
    df=yf.download(tickers=ticker,period="1d",interval=tf,progress=False,auto_adjust=False)
    if df.empty: return None
    if isinstance(df.columns,pd.MultiIndex): df.columns=df.columns.get_level_values(0)
    df.columns=[c.lower() for c in df.columns]
    return df

def main():
    ts=datetime.now(timezone.utc).isoformat()
    opens=load_opens()
    for s in SYMBOLS:
        if s not in opens: opens[s]=[]
        if not isinstance(opens[s], list): opens[s]=[opens[s]]

    print(f"REAL MARKET LIVE {ts}")
    for symbol in SYMBOLS:
        try:
            cfg=CONFIG.get(symbol,DEF)
            df=get_candles(symbol,TIMEFRAME)
            if df is None or len(df)<10:
                print(f" {symbol}: no history")
                continue

            cur=get_real_price(symbol)
            if cur is None:
                cur=float(df["close"].iloc[-1])
                print(f" {symbol}: using delayed price {cur}")
            else:
                print(f" {symbol}: REAL PRICE {cur}")

            high_5=float(df["high"].iloc[-6:-1].max())
            low_5=float(df["low"].iloc[-6:-1].min())
            last=df.iloc[-1]

            # close logic
            remaining=[]
            for trade in opens[symbol]:
                entry=trade["entry_price"]
                is_buy=trade["direction"]=="BUY"
                profit_pips=(cur-entry)/cfg["pip"] if is_buy else (entry-cur)/cfg["pip"]
                candle_reversed = (is_buy and float(last["close"])<float(last["open"])) or (not is_buy and float(last["close"])>float(last["open"]))
                outcome=None; exit_p=None; should_close=False
                if is_buy:
                    if cur>=trade["take_profit"]: outcome="WIN"; exit_p=trade["take_profit"]
                    elif cur<=trade["stop_loss"]: outcome="LOSS"; exit_p=trade["stop_loss"]
                    elif profit_pips>=cfg["sweep_tp"] and candle_reversed: outcome="WIN"; exit_p=cur; should_close=True
                else:
                    if cur<=trade["take_profit"]: outcome="WIN"; exit_p=trade["take_profit"]
                    elif cur>=trade["stop_loss"]: outcome="LOSS"; exit_p=trade["stop_loss"]
                    elif profit_pips>=cfg["sweep_tp"] and candle_reversed: outcome="WIN"; exit_p=cur; should_close=True

                if outcome:
                    pips=(exit_p-entry)/cfg["pip"] if is_buy else (entry-exit_p)/cfg["pip"]
                    log_row(CLOSED,["timestamp_utc","symbol","direction","entry_price","exit_price","outcome","pips","opened_at","note"],
                            {"timestamp_utc":ts,"symbol":symbol,"direction":trade["direction"],"entry_price":entry,"exit_price":exit_p,"outcome":outcome,"pips":round(pips,2),"opened_at":trade["opened_at"],"note":"SWEEP" if should_close else "TP/SL"})
                    print(f" {symbol}: CLOSED {trade['direction']} {outcome} {round(pips,2)}p")
                else:
                    trade["current_price"]=cur
                    remaining.append(trade)
            opens[symbol]=remaining

            if len(opens[symbol])>=cfg["max"]:
                print(f" {symbol}: max open")
                continue

            buy_stop=high_5 + 0.4*cfg["pip"]
            sell_stop=low_5 - 0.4*cfg["pip"]
            triggered=None
            if cur > high_5: triggered="BUY"
            elif cur < low_5: triggered="SELL"

            if triggered:
                entry=cur
                sl=entry-cfg["sl"]*cfg["pip"] if triggered=="BUY" else entry+cfg["sl"]*cfg["pip"]
                tp=entry+cfg["tp"]*cfg["pip"] if triggered=="BUY" else entry-cfg["tp"]*cfg["pip"]
                opens[symbol].append({"direction":triggered,"entry_price":entry,"stop_loss":sl,"take_profit":tp,"opened_at":ts,"current_price":cur,"buy_stop":buy_stop,"sell_stop":sell_stop})
                log_row(LOG,["timestamp_utc","symbol","direction","entry_price","stop_loss","take_profit","buy_stop","sell_stop"],
                        {"timestamp_utc":ts,"symbol":symbol,"direction":triggered,"entry_price":round(entry,5),"stop_loss":round(sl,5),"take_profit":round(tp,5),"buy_stop":round(buy_stop,5),"sell_stop":round(sell_stop,5)})
                print(f" {symbol}: NEW REAL {triggered} at {cur}")
            else:
                print(f" {symbol}: waiting H5={high_5:.5f} L5={low_5:.5f} REAL={cur:.5f}")

        except Exception as e:
            print(f" {symbol}: ERR {e}")

    save_opens(opens)

if __name__=="__main__":
    main()
