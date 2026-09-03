import csv, json, os, time
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf

SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "EURUSD,GBPUSD,USDJPY,XAUUSD").split(",")]
TIMEFRAME = os.getenv("TIMEFRAME", "5m")

OPEN_SIGNALS_FILE = "open_signals.json"
SIGNALS_LOG = "signals_log.csv"
CLOSED_TRADES_LOG = "closed_trades.csv"

YAHOO_MAP = {"EURUSD":"EURUSD=X","GBPUSD":"GBPUSD=X","USDJPY":"USDJPY=X","XAUUSD":"GC=F"}
SYMBOL_CONFIG = {
    "EURUSD": {"pip_size":0.0001,"tp_pips":7,"sl_pips":4},
    "GBPUSD": {"pip_size":0.0001,"tp_pips":7,"sl_pips":4},
    "USDJPY": {"pip_size":0.01,"tp_pips":7,"sl_pips":4},
    "XAUUSD": {"pip_size":0.1,"tp_pips":20,"sl_pips":12},
}
DEFAULT_CONFIG = {"pip_size":0.0001,"tp_pips":7,"sl_pips":4}

def ema(s, span): return s.ewm(span=span, adjust=False).mean()
def rsi(s, period=14):
    d=s.diff(); g=d.clip(lower=0); l=-d.clip(upper=0)
    ag=g.rolling(period).mean(); al=l.rolling(period).mean()
    rs=ag/al.replace(0,np.nan); r=100-(100/(1+rs))
    r[(al==0)&(g>0)]=100; r[(al==0)&(g==0)]=50; return r

def adx(df, period=14):
    h=df['high']; l=df['low']; c=df['close']
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    up=h.diff(); down=-l.diff()
    plus_dm=np.where((up>down)&(up>0),up,0.0)
    minus_dm=np.where((down>up)&(down>0),down,0.0)
    atr=tr.rolling(period).mean()
    plus_di=100*(pd.Series(plus_dm).rolling(period).mean()/atr)
    minus_di=100*(pd.Series(minus_dm).rolling(period).mean()/atr)
    dx=100*((plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,np.nan))
    adx_val=dx.rolling(period).mean()
    return adx_val, plus_di, minus_di

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
    df=yf.download(tickers=ticker,period="10d",interval=tf,progress=False,auto_adjust=False)
    if df.empty: return None
    if isinstance(df.columns,pd.MultiIndex): df.columns=df.columns.get_level_values(0)
    df.columns=[c.lower() for c in df.columns]
    return df

def main():
    ts=datetime.now(timezone.utc).isoformat()
    hour=datetime.now(timezone.utc).hour
    # Session filter - avoid Asian low vol
    if hour < 7 or hour > 21:
        print(f"Outside London/NY session ({hour} UTC) - skipping to avoid chop")
        return
    opens=load_open_signals()
    print(f"V2 Scan at {ts}")
    for symbol in SYMBOLS:
        try:
            cfg=SYMBOL_CONFIG.get(symbol,DEFAULT_CONFIG)
            df=get_candles(symbol,TIMEFRAME)
            if df is None or len(df)<60: print(f" {symbol}: no data"); continue
            df["close"]=df["close"].astype(float)
            cur=float(df["close"].iloc[-1])
            # Check open trades
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
                    print(f" {symbol}: {outcome}"); del opens[symbol]
                else: print(f" {symbol}: open {sig['direction']} {cur:.5f}")
                continue
            # Indicators
            df["ema_fast"]=ema(df["close"],9); df["ema_slow"]=ema(df["close"],21)
            df["ema_trend"]=ema(df["close"],50)
            df["rsi"]=rsi(df["close"],14)
            df["bb_mid"]=df["close"].rolling(20).mean()
            df["bb_std"]=df["close"].rolling(20).std()
            df["bb_upper"]=df["bb_mid"]+2*df["bb_std"]
            df["bb_lower"]=df["bb_mid"]-2*df["bb_std"]
            df["bb_width"]=(df["bb_upper"]-df["bb_lower"])/df["bb_mid"]
            adx_v, plus_di, minus_di = adx(df,14)
            df["adx"]=adx_v; df["plus_di"]=plus_di; df["minus_di"]=minus_di

            prev,last=df.iloc[-2],df.iloc[-1]
            if pd.isna(last["rsi"]) or pd.isna(last["adx"]) or pd.isna(last["ema_trend"]): continue

            # Filters
            if last["adx"] < 20: print(f" {symbol}: ADX {last['adx']:.1f} too weak - chop"); continue
            if last["bb_width"] < 0.0015 and symbol!="XAUUSD": print(f" {symbol}: BB width too tight - no vol"); continue

            crossed_up = prev["ema_fast"] <= prev["ema_slow"] and last["ema_fast"] > last["ema_slow"]
            crossed_down = prev["ema_fast"] >= prev["ema_slow"] and last["ema_fast"] < last["ema_slow"]

            buy_ok = crossed_up and last["close"] > last["ema_trend"] and last["rsi"] > 50 and last["rsi"] < 70 and last["plus_di"] > last["minus_di"]
            sell_ok = crossed_down and last["close"] < last["ema_trend"] and last["rsi"] < 50 and last["rsi"] > 30 and last["minus_di"] > last["plus_di"]

            sig_dir="BUY" if buy_ok else "SELL" if sell_ok else None
            if not sig_dir:
                print(f" {symbol}: no signal p={cur:.5f} RSI={last['rsi']:.0f} ADX={last['adx']:.0f} trend={'up' if cur>last['ema_trend'] else 'down'}")
                continue

            entry=cur
            sl=entry-cfg["sl_pips"]*cfg["pip_size"] if sig_dir=="BUY" else entry+cfg["sl_pips"]*cfg["pip_size"]
            tp=entry+cfg["tp_pips"]*cfg["pip_size"] if sig_dir=="BUY" else entry-cfg["tp_pips"]*cfg["pip_size"]
            opens[symbol]={"direction":sig_dir,"entry_price":entry,"stop_loss":sl,"take_profit":tp,"opened_at":ts}
            log_row(SIGNALS_LOG,["timestamp_utc","symbol","direction","entry_price","stop_loss","take_profit","rsi","adx"],
                    {"timestamp_utc":ts,"symbol":symbol,"direction":sig_dir,"entry_price":round(entry,5),"stop_loss":round(sl,5),"take_profit":round(tp,5),"rsi":round(float(last["rsi"]),1),"adx":round(float(last["adx"]),1)})
            print(f" {symbol}: NEW V2 {sig_dir} ADX={last['adx']:.0f} RSI={last['rsi']:.0f}")
            time.sleep(1)
        except Exception as e: print(f" {symbol}: ERROR {e}")
    save_open_signals(opens)

if __name__=="__main__": main()
