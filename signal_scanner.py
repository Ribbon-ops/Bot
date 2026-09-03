import json, os
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf

SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "EURUSD,GBPUSD,USDJPY,XAUUSD").split(",")]
TIMEFRAME = os.getenv("TIMEFRAME", "1m")

OPEN_FILE = "open_signals.json"
LOG = "signals_log.csv"
CLOSED = "closed_trades.csv"

# LIVE SPOT PRICES - matches TradingView
YAHOO_MAP = {"EURUSD":"EURUSD=X","GBPUSD":"GBPUSD=X","USDJPY":"USDJPY=X","XAUUSD":"XAUUSD=X"}

CONFIG = {
    "EURUSD": {"pip":0.0001,"tp":1.5,"sl":4,"sweep_tp":0.8,"max":5},
    "GBPUSD": {"pip":0.0001,"tp":1.5,"sl":4,"sweep_tp":0.8,"max":5},
    "USDJPY": {"pip":0.01,"tp":1.5,"sl":4,"sweep_tp":0.8,"max":5},
    "XAUUSD": {"pip":0.1,"tp":2.5,"sl":6,"sweep_tp":1.2,"max":3},
}
DEF = {"pip":0.0001,"tp":1.5,"sl":4,"sweep_tp":0.8,"max":5}

def load_opens():
    if os.path.exists(OPEN_FILE):
        try:
            with open(OPEN_FILE) as f:
                data=json.load(f)
                for k,v in data.items():
                    if isinstance(v,dict):
                        data[k]=[v]
                return data
        except:
            pass
    return {s: [] for s in SYMBOLS}

def save_opens(d):
    with open(OPEN_FILE,"w") as f:
        json.dump(d,f,indent=2)

def log_row(fn, fields, row):
    ex=os.path.exists(fn)
    import csv
    with open(fn,"a",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        if not ex:
            w.writeheader()
        w.writerow(row)

def get_candles(sym, tf):
    ticker=YAHOO_MAP.get(sym,sym)
    df=yf.download(tickers=ticker,period="2d",interval=tf,progress=False,auto_adjust=False)
    if df.empty:
        return None
    if isinstance(df.columns,pd.MultiIndex):
        df.columns=df.columns.get_level_values(0)
    df.columns=[c.lower() for c in df.columns]
    return df

def main():
    ts=datetime.now(timezone.utc).isoformat()
    opens=load_opens()
    for s in SYMBOLS:
        if s not in opens:
            opens[s]=[]
        if not isinstance(opens[s], list):
            opens[s]=[opens[s]]

    print(f"LIVE $10 Test {ts} TF={TIMEFRAME}")
    for symbol in SYMBOLS:
        try:
            cfg=CONFIG.get(symbol,DEF)
            df=get_candles(symbol,TIMEFRAME)
            if df is None or len(df)<20:
                print(f" {symbol}: no data")
                continue
            cur=float(df["close"].iloc[-1])
            high_5=float(df["high"].iloc[-6:-1].max())
            low_5=float(df["low"].iloc[-6:-1].min())
            last=df.iloc[-1]

            remaining=[]
            for trade in opens[symbol]:
                entry=trade["entry_price"]
                is_buy=trade["direction"]=="BUY"
                profit_pips=(cur-entry)/cfg["pip"] if is_buy else (entry-cur)/cfg["pip"]
                candle_reversed = (is_buy and float(last["close"])<float(last["open"])) or (not is_buy and float(last["close"])>float(last["open"]))
                outcome=None
                exit_p=None
                should_close=False
                if is_buy:
                    if cur>=trade["take_profit"]:
                        outcome="WIN"; exit_p=trade["take_profit"]
                    elif cur<=trade["stop_loss"]:
                        outcome="LOSS"; exit_p=trade["stop_loss"]
                    elif profit_pips>=cfg["sweep_tp"] and candle_reversed:
                        outcome="WIN"; exit_p=cur; should_close=True
                else:
                    if cur<=trade["take_profit"]:
                        outcome="WIN"; exit_p=trade["take_profit"]
                    elif cur>=trade["stop_loss"]:
                        outcome="LOSS"; exit_p=trade["stop_loss"]
                    elif profit_pips>=cfg["sweep_tp"] and candle_reversed:
                        outcome="WIN"; exit_p=cur; should_close=True

                if outcome:
                    pips=(exit_p-entry)/cfg["pip"] if is_buy else (entry-exit_p)/cfg["pip"]
                    note="SWEEP" if should_close else "TP/SL"
                    log_row(CLOSED,["timestamp_utc","symbol","direction","entry_price","exit_price","outcome","pips","opened_at","note"],
                            {"timestamp_utc":ts,"symbol":symbol,"direction":trade["direction"],"entry_price":entry,"exit_price":exit_p,"outcome":outcome,"pips":round(pips,2),"opened_at":trade["opened_at"],"note":note})
                    print(f" {symbol}: CLOSED {trade['direction']} {outcome} {round(pips,2)}p")
                else:
                    trade["current_price"]=cur
                    remaining.append(trade)
            opens[symbol]=remaining

            if len(opens[symbol]) >= cfg["max"]:
                print(f" {symbol}: max open")
                continue

            buy_stop_level = high_5 + 0.4*cfg["pip"]
            sell_stop_level = low_5 - 0.4*cfg["pip"]

            triggered=None
            # LIVE BREAKOUT LOGIC
            if cur > high_5:
                triggered="BUY"
                print(f" {symbol}: LIVE BUY BREAK {cur:.5f} > {high_5:.5f}")
            elif cur < low_5:
                triggered="SELL"
                print(f" {symbol}: LIVE SELL BREAK {cur:.5f} < {low_5:.5f}")

            if triggered:
                entry=cur
                sl=entry-cfg["sl"]*cfg["pip"] if triggered=="BUY" else entry+cfg["sl"]*cfg["pip"]
                tp=entry+cfg["tp"]*cfg["pip"] if triggered=="BUY" else entry-cfg["tp"]*cfg["pip"]
                opens[symbol].append({"direction":triggered,"entry_price":entry,"stop_loss":sl,"take_profit":tp,"opened_at":ts,"current_price":cur,"buy_stop":buy_stop_level,"sell_stop":sell_stop_level})
                log_row(LOG,["timestamp_utc","symbol","direction","entry_price","stop_loss","take_profit","buy_stop","sell_stop"],
                        {"timestamp_utc":ts,"symbol":symbol,"direction":triggered,"entry_price":round(entry,5),"stop_loss":round(sl,5),"take_profit":round(tp,5),"buy_stop":round(buy_stop_level,5),"sell_stop":round(sell_stop_level,5)})
                print(f" {symbol}: NEW LIVE {triggered}")
            else:
                print(f" {symbol}: waiting BS={buy_stop_level:.5f} SS={sell_stop_level:.5f} price={cur:.5f} H5={high_5:.5f} L5={low_5:.5f}")

        except Exception as e:
            print(f" {symbol}: ERR {e}")

    save_opens(opens)

if __name__=="__main__":
    main()
