import json, os, csv
from datetime import datetime, timezone
import yfinance as yf
import pandas as pd

SYMBOLS = ["XAUUSD","EURUSD","GBPUSD","USDJPY"]
YMAP = {"EURUSD":"EURUSD=X","GBPUSD":"GBPUSD=X","USDJPY":"USDJPY=X","XAUUSD":"GC=F"}
CONF = {
 "EURUSD":{"pip":0.0001,"tp":0.3,"sl":2,"sweep":0.15},
 "GBPUSD":{"pip":0.0001,"tp":0.3,"sl":2,"sweep":0.15},
 "USDJPY":{"pip":0.01,"tp":0.3,"sl":2,"sweep":0.15},
 "XAUUSD":{"pip":0.1,"tp":0.4,"sl":3,"sweep":0.2},
}

def get_price(sym):
 ticker=YMAP[sym]
 df=yf.download(ticker,period="1d",interval="1m",progress=False,auto_adjust=True)
 if df.empty: return None,None
 if isinstance(df.columns,pd.MultiIndex): df.columns=df.columns.get_level_values(0)
 df.columns=[str(c).lower() for c in df.columns]
 price=float(df["close"].iloc[-1])
 return price,df

def main():
 ts=datetime.now(timezone.utc).isoformat()
 opens={}
 if os.path.exists("open_signals.json"):
  try:
   with open("open_signals.json") as f: opens=json.load(f)
  except: opens={}
 for s in SYMBOLS:
  if s not in opens: opens[s]=[]
  if isinstance(opens[s],dict): opens[s]=[opens[s]]
 print(f"RAPID SCALP {ts}")
 for sym in SYMBOLS:
  cfg=CONF[sym]
  try:
   price,df=get_price(sym)
   if price is None: continue
   cur=price
   # CLOSE FAST FOR CENTS
   remain=[]
   for tr in opens[sym]:
    e=float(tr["entry_price"])
    is_buy=tr["direction"]=="BUY"
    pips=(cur-e)/cfg["pip"] if is_buy else (e-cur)/cfg["pip"]
    if pips>=cfg["sweep"]:
     ex=os.path.exists("closed_trades.csv")
     with open("closed_trades.csv","a",newline="") as f:
      w=csv.DictWriter(f,fieldnames=["timestamp_utc","symbol","direction","entry_price","exit_price","outcome","pips","opened_at"])
      if not ex: w.writeheader()
      w.writerow({"timestamp_utc":ts,"symbol":sym,"direction":tr["direction"],"entry_price":e,"exit_price":cur,"outcome":"WIN","pips":round(pips,2),"opened_at":tr["opened_at"]})
     print(f"CLOSE WIN {sym} {pips:.2f}p")
    elif pips<=-cfg["sl"]:
     ex=os.path.exists("closed_trades.csv")
     with open("closed_trades.csv","a",newline="") as f:
      w=csv.DictWriter(f,fieldnames=["timestamp_utc","symbol","direction","entry_price","exit_price","outcome","pips","opened_at"])
      if not ex: w.writeheader()
      w.writerow({"timestamp_utc":ts,"symbol":sym,"direction":tr["direction"],"entry_price":e,"exit_price":cur,"outcome":"LOSS","pips":round(pips,2),"opened_at":tr["opened_at"]})
    else:
     tr["current_price"]=cur
     remain.append(tr)
   opens[sym]=remain
   # OPEN EVERY CANDLE - BUY GREEN SELL RED
   if len(opens[sym])==0:
    is_green=float(df["close"].iloc[-1]) >= float(df["open"].iloc[-1])
    direction="BUY" if is_green else "SELL"
    entry=cur
    sl=entry-cfg["sl"]*cfg["pip"] if direction=="BUY" else entry+cfg["sl"]*cfg["pip"]
    tp=entry+cfg["tp"]*cfg["pip"] if direction=="BUY" else entry-cfg["tp"]*cfg["pip"]
    opens[sym].append({"direction":direction,"entry_price":entry,"stop_loss":sl,"take_profit":tp,"opened_at":ts,"current_price":cur})
    ex=os.path.exists("signals_log.csv")
    with open("signals_log.csv","a",newline="") as f:
     w=csv.DictWriter(f,fieldnames=["timestamp_utc","symbol","direction","entry_price","stop_loss","take_profit"])
     if not ex: w.writeheader()
     w.writerow({"timestamp_utc":ts,"symbol":sym,"direction":direction,"entry_price":round(entry,5),"stop_loss":round(sl,5),"take_profit":round(tp,5)})
    print(f"OPEN {sym} {direction} {entry}")
  except Exception as e:
   print(f"{sym} ERR {e}")
 with open("open_signals.json","w") as f: json.dump(opens,f,indent=2)
if __name__=="__main__": main()
