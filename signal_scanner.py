import csv
import json
import os
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf

SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "EURUSD,GBPUSD,USDJPY,XAUUSD").split(",")]
TIMEFRAME = os.getenv("TIMEFRAME", "5m")

OPEN_SIGNALS_FILE = "open_signals.json"
SIGNALS_LOG = "signals_log.csv"
CLOSED_TRADES_LOG = "closed_trades.csv"

YAHOO_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "XAUUSD": "GC=F",
}

SYMBOL_CONFIG = {
    "EURUSD": {"pip_size": 0.0001, "tp_pips": 5, "sl_pips": 3},
    "GBPUSD": {"pip_size": 0.0001, "tp_pips": 5, "sl_pips": 3},
    "USDJPY": {"pip_size": 0.01, "tp_pips": 5, "sl_pips": 3},
    "XAUUSD": {"pip_size": 0.1, "tp_pips": 15, "sl_pips": 10},
}
DEFAULT_CONFIG = {"pip_size": 0.0001, "tp_pips": 5, "sl_pips": 3}

def ema(s, span): return s.ewm(span=span, adjust=False).mean()
def rsi(s, period=14):
    d=s.diff(); g=d.clip(lower=0); l=-d.clip(upper=0)
    ag=g.rolling(period).mean(); al=l.rolling(period).mean()
    rs=ag/al.replace(0,np.nan); r=100-(100/(1+rs))
    r[(al==0)&(g>0)]=100; r[(al==0)&(g==0)]=50; return r

def load_open_signals():
    if os.path.exists(OPEN_SIGNALS_FILE):
        with open(OPEN_SIGNALS_FILE) as f: return json.load(f)
    return {}
def save_open_signals(d):
    with open(OPEN_SIGNALS_FILE,"w") as f: json.dump(d,f,indent=2)
def log_row(fn, fields, row):
    ex=os.path.exists(fn)
    with open(fn,"a",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        if not ex: w.writeheader()
        w.writerow(row)

def get_candles(symbol, tf="5m"):
    ticker=YAHOO_MAP.get(symbol,symbol)
    df=yf.download(tickers=ticker,period="7d",interval=tf,progress=False,auto_adjust=False)
    if df.empty: return None
    if isinstance(df.columns,pd.MultiIndex): df.columns=df.columns.get_level_values(0)
    df.columns=[c.lower() for c in df.columns]
    return df

def main():
    ts=datetime.now(timezone.utc).isoformat()
    opens=load_open_signals()
    print(f"Scanning at {ts} - {SYMBOLS}")
    for symbol in SYMBOLS:
        try:
            cfg=SYMBOL_CONFIG.get(symbol,DEFAULT_CONFIG)
            df=get_candles(symbol,TIMEFRAME)
            if df is None or len(df)<30:
                print(f" {symbol}: no data"); continue
            df["close"]=df["close"].astype(float)
            cur=float(df["close"].iloc[-1])
            if symbol in opens:
                sig=opens[symbol]; tp=sig["take_profit"]; sl=sig["stop_loss"]
                outcome=None; exit_p=None
                if sig["direction"]=="BUY":
                    if cur>=tp: outcome="WIN"; exit_p=tp
                    elif cur<=sl: outcome="LOSS"; exit_p=sl
                else:
                    if cur<=tp: outcome="WIN"; exit_p=tp
                    elif cur>=sl: outcome="LOSS"; exit_p=sl
                if outcome:
                    entry=sig["entry_price"]
                    pips=(exit_p-entry)/cfg["pip_size"] if sig["direction"]=="BUY" else (entry-exit_p)/cfg["pip_size"]
                    log_row(CLOSED_TRADES_LOG,["timestamp_utc","symbol","direction","entry_price","exit_price","outcome","pips","opened_at"],
                            {"timestamp_utc":ts,"symbol":symbol,"direction":sig["direction"],"entry_price":entry,"exit_price":exit_p,"outcome":outcome,"pips":round(pips,1),"opened_at":sig["opened_at"]})
                    print(f" {symbol}: {outcome} closed"); del opens[symbol]
                else: print(f" {symbol}: open {sig['direction']} {cur:.5f}")
                continue
            df["ema_fast"]=ema(df["close"],9); df["ema_slow"]=ema(df["close"],21); df["rsi"]=rsi(df["close"],14)
            prev,last=df.iloc[-2],df.iloc[-1]
            if pd.isna(last["rsi"]): continue
            up=prev["ema_fast"]<=prev["ema_slow"] and last["ema_fast"]>last["ema_slow"]
            down=prev["ema_fast"]>=prev["ema_slow"] and last["ema_fast"]<last["ema_slow"]
            sig_dir=None
            if up and last["rsi"]<70: sig_dir="BUY"
            elif down and last["rsi"]>30: sig_dir="SELL"
            if not sig_dir:
                print(f" {symbol}: no signal price={cur:.5f} RSI={last['rsi']:.1f}"); continue
            entry=cur
            sl=entry-cfg["sl_pips"]*cfg["pip_size"] if sig_dir=="BUY" else entry+cfg["sl_pips"]*cfg["pip_size"]
            tp=entry+cfg["tp_pips"]*cfg["pip_size"] if sig_dir=="BUY" else entry-cfg["tp_pips"]*cfg["pip_size"]
            opens[symbol]={"direction":sig_dir,"entry_price":entry,"stop_loss":sl,"take_profit":tp,"opened_at":ts}
            log_row(SIGNALS_LOG,["timestamp_utc","symbol","direction","entry_price","stop_loss","take_profit","rsi"],
                    {"timestamp_utc":ts,"symbol":symbol,"direction":sig_dir,"entry_price":round(entry,5),"stop_loss":round(sl,5),"take_profit":round(tp,5),"rsi":round(float(last["rsi"]),1)})
            print(f" {symbol}: NEW {sig_dir} entry={entry:.5f}")
            time.sleep(1)
        except Exception as e:
            print(f" {symbol}: ERROR {e}")
    save_open_signals(opens)
    print("Done")

if __name__=="__main__": main()
