import csv, json, os
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf

SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "EURUSD,GBPUSD,USDJPY,XAUUSD").split(",")]
TIMEFRAME = os.getenv("TIMEFRAME", "1m")

OPEN_FILE = "open_signals.json"
LOG = "signals_log.csv"
CLOSED = "closed_trades.csv"

YAHOO_MAP = {"EURUSD":"EURUSD=X","GBPUSD":"GBPUSD=X","USDJPY":"USDJPY=X","XAUUSD":"GC=F"}
CONFIG = {
    "EURUSD": {"pip":0.0001,"tp":3.0,"sl":8,"sweep_tp":1.2,"max":5},
    "GBPUSD": {"pip":0.0001,"tp":3.0,"sl":8,"sweep_tp":1.2,"max":5},
    "USDJPY": {"pip":0.01,"tp":3.0,"sl":8,"sweep_tp":1.2,"max":5},
    "XAUUSD": {"pip":0.1,"tp":5,"sl":15,"sweep_tp":2.0,"max":3},
}
DEF = {"pip":0.0001,"tp":3.0,"sl":8,"sweep_tp":1.2,"max":5}

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
    with open(fn,"a",newline="") as f:
        import csv
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

    print(f"V4 $10 Test - Sweep Scalper {ts} TF={TIMEFRAME}")
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
            prev=df.iloc[-2]

            remaining=[]
            for trade in opens[symbol]:
                entry=trade["entry_price"]
                is_buy=trade["direction"]=="BUY"
                profit_pips=(cur-entry)/cfg["pip"] if is_buy else (entry-cur)/cfg["pip"]
                candle_reversed = (is_buy and float(last["close"])<float(last["open"])) or (not is_buy and float(last["close"])>float(last["open"]))

                should_close_sweep=False
                outcome=None
                exit_p=None

                if is_buy:
                    if cur>=trade["take_profit"]:
                        outcome="WIN"; exit_p=trade["take_profit"]
                    elif cur<=trade["stop_loss"]:
                        outcome="LOSS"; exit_p=trade["stop_loss"]
                    elif profit_pips>=cfg["sweep_tp"] and candle_reversed:
                        should_close_sweep=True
                        outcome="WIN"; exit_p=cur
                else:
                    if cur<=trade["take_profit"]:
                        outcome="WIN"; exit_p=trade["take_profit"]
                    elif cur>=trade["stop_loss"]:
                        outcome="LOSS"; exit_p=trade["stop_loss"]
                    elif profit_pips>=cfg["sweep_tp"] and candle_reversed:
                        should_close_sweep=True
                        outcome="WIN"; exit_p=cur

                if outcome:
                    pips=(exit_p-entry)/cfg["pip"] if is_buy else (entry-exit_p)/cfg["pip"]
                    note="SWEEP-EXIT" if should_close_sweep else "TP/SL"
                    log_row(CLOSED,["timestamp_utc","symbol","direction","entry_price","exit_price","outcome","pips","opened_at","note"],
                            {"timestamp_utc":ts,"symbol":symbol,"direction":trade["direction"],"entry_price":entry,"exit_price":exit_p,"outcome":outcome,"pips":round(pips,2),"opened_at":trade["opened_at"],"note":note})
                    print(f" {symbol}: CLOSED {trade['direction']} {outcome} {round(pips,2)}p {note}")
                else:
                    trade["current_price"]=cur
                    remaining.append(trade)
            opens[symbol]=remaining

            if len(opens[symbol]) >= cfg["max"]:
                print(f" {symbol}: max {cfg['max']} open")
                continue

            buy_stop_level = high_5 + 1.5*cfg["pip"]
            sell_stop_level = low_5 - 1.5*cfg["pip"]

            triggered=None
            if cur >= buy_stop_level and float(prev["close"]) < high_5:
                triggered="BUY"
                print(f" {symbol}: BUY STOP grab {cur:.5f} >= {buy_stop_level:.5f}")
            elif cur <= sell_stop_level and float(prev["close"]) > low_5:
                triggered="SELL"
                print(f" {symbol}: SELL STOP grab {cur:.5f} <= {sell_stop_level:.5f}")

            if triggered:
                if opens[symbol] and opens[symbol][0]["direction"]!=triggered:
                    print(f" {symbol}: respecting reversal, no new {triggered}")
                    continue
                entry=cur
                sl=entry-cfg["sl"]*cfg["pip"] if triggered=="BUY" else entry+cfg["sl"]*cfg["pip"]
                tp=entry+cfg["tp"]*cfg["pip"] if triggered=="BUY" else entry-cfg["tp"]*cfg["pip"]
                opens[symbol].append({"direction":triggered,"entry_price":entry,"stop_loss":sl,"take_profit":tp,"opened_at":ts,"current_price":cur,"buy_stop":buy_stop_level,"sell_stop":sell_stop_level})
                log_row(LOG,["timestamp_utc","symbol","direction","entry_price","stop_loss","take_profit","buy_stop","sell_stop"],
                        {"timestamp_utc":ts,"symbol":symbol,"direction":triggered,"entry_price":round(entry,5),"stop_loss":round(sl,5),"take_profit":round(tp,5),"buy_stop":round(buy_stop_level,5),"sell_stop":round(sell_stop_level,5)})
                print(f" {symbol}: NEW {triggered} stack {len(opens[symbol])}/{cfg['max']}")
            else:
                print(f" {symbol}: waiting BS={buy_stop_level:.5f} SS={sell_stop_level:.5f} price={cur:.5f}")

        except Exception as e:
            print(f" {symbol}: ERR {e}")

    save_opens(opens)

if __name__=="__main__":
    main()
