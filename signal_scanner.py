import json, os
from datetime import datetime, timezone
import yfinance as yf

SYMBOLS = ["XAUUSD","EURUSD","GBPUSD","USDJPY"]
OPEN_FILE = "open_signals.json"
LOG = "signals_log.csv"
CLOSED = "closed_trades.csv"
YAHOO_MAP = {"EURUSD":"EURUSD=X","GBPUSD":"GBPUSD=X","USDJPY":"USDJPY=X","XAUUSD":"XAUUSD=X"}
CONFIG = {
    "EURUSD": {"pip":0.0001,"tp":1.5,"sl":4,"sweep":0.8,"max":3},
    "GBPUSD": {"pip":0.0001,"tp":1.5,"sl":4,"sweep":0.8,"max":3},
    "USDJPY": {"pip":0.01,"tp":1.5,"sl":4,"sweep":0.8,"max":3},
    "XAUUSD": {"pip":0.1,"tp":2.5,"sl":6,"sweep":1.2,"max":2},
}

def get_price(ticker):
    try:
        t=yf.Ticker(ticker)
        p=t.fast_info.last_price
        if p: return float(p)
    except: pass
    df=yf.download(ticker,period="1d",interval="1m",progress=False)
    return float(df["Close"].iloc[-1])

def main():
    ts=datetime.now(timezone.utc).isoformat()
    opens={}
    if os.path.exists(OPEN_FILE):
        try:
            with open(OPEN_FILE) as f: opens=json.load(f)
        except: opens={}
    for s in SYMBOLS:
        if s not in opens: opens[s]=[]
        if isinstance(opens[s], dict): opens[s]=[opens[s]]

    print(f"FORCE LIVE {ts}")
    for sym in SYMBOLS:
        cfg=CONFIG[sym]
        try:
            price=get_price(YAHOO_MAP[sym])
            print(f"{sym} REAL={price}")

            # close old
            new=[]
            for tr in opens[sym]:
                entry=tr["entry_price"]
                is_buy=tr["direction"]=="BUY"
                profit=(price-entry)/cfg["pip"] if is_buy else (entry-price)/cfg["pip"]
                closed=False
                exit_p=price
                outcome=None
                if is_buy:
                    if price>=tr["take_profit"]: outcome="WIN"; exit_p=tr["take_profit"]; closed=True
                    elif price<=tr["stop_loss"]: outcome="LOSS"; exit_p=tr["stop_loss"]; closed=True
                    elif profit>=cfg["sweep"]: outcome="WIN"; exit_p=price; closed=True
                else:
                    if price<=tr["take_profit"]: outcome="WIN"; exit_p=tr["take_profit"]; closed=True
                    elif price>=tr["stop_loss"]: outcome="LOSS"; exit_p=tr["stop_loss"]; closed=True
                    elif profit>=cfg["sweep"]: outcome="WIN"; exit_p=price; closed=True

                if closed:
                    pips=(exit_p-entry)/cfg["pip"] if is_buy else (entry-exit_p)/cfg["pip"]
                    import csv
                    ex=os.path.exists(CLOSED)
                    with open(CLOSED,"a",newline="") as f:
                        w=csv.DictWriter(f,fieldnames=["timestamp_utc","symbol","direction","entry_price","exit_price","outcome","pips","opened_at","note"])
                        if not ex: w.writeheader()
                        w.writerow({"timestamp_utc":ts,"symbol":sym,"direction":tr["direction"],"entry_price":entry,"exit_price":exit_p,"outcome":outcome,"pips":round(pips,2),"opened_at":tr["opened_at"],"note":"FORCE"})
                    print(f"{sym} CLOSED {outcome} {pips}p")
                else:
                    tr["current_price"]=price
                    new.append(tr)
            opens[sym]=new

            # FORCE NEW TRADE if no open trade
            if len(opens[sym])==0:
                # decide direction from last 2 candles
                df=yf.download(YAHOO_MAP[sym],period="1d",interval="1m",progress=False)
                direction="BUY" if float(df["Close"].iloc[-1]) > float(df["Open"].iloc[-1]) else "SELL"
                entry=price
                sl=entry-cfg["sl"]*cfg["pip"] if direction=="BUY" else entry+cfg["sl"]*cfg["pip"]
                tp=entry+cfg["tp"]*cfg["pip"] if direction=="BUY" else entry-cfg["tp"]*cfg["pip"]
                opens[sym].append({"direction":direction,"entry_price":entry,"stop_loss":sl,"take_profit":tp,"opened_at":ts,"current_price":price,"buy_stop":0,"sell_stop":0})
                import csv
                ex=os.path.exists(LOG)
                with open(LOG,"a",newline="") as f:
                    w=csv.DictWriter(f,fieldnames=["timestamp_utc","symbol","direction","entry_price","stop_loss","take_profit","buy_stop","sell_stop"])
                    if not ex: w.writeheader()
                    w.writerow({"timestamp_utc":ts,"symbol":sym,"direction":direction,"entry_price":round(entry,5),"stop_loss":round(sl,5),"take_profit":round(tp,5),"buy_stop":0,"sell_stop":0})
                print(f"{sym} NEW FORCED {direction} at {price}")

        except Exception as e:
            print(f"{sym} ERR {e}")

    with open(OPEN_FILE,"w") as f: json.dump(opens,f,indent=2)

if __name__=="__main__":
    main()
