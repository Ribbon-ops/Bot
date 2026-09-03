import json, os, csv
from datetime import datetime, timezone, timedelta
import yfinance as yf
import pandas as pd

ACCOUNT_BALANCE = 100
LOT_SIZE = 0.01
SYMBOLS = ["EURUSD","GBPUSD"]
YMAP = {"EURUSD":"EURUSD=X","GBPUSD":"GBPUSD=X"}
CONF = {
 "EURUSD":{"pip":0.0001,"tp_pips":8.0,"sl_pips":4.0,"usd_per_pip":0.10},
 "GBPUSD":{"pip":0.0001,"tp_pips":8.0,"sl_pips":4.0,"usd_per_pip":0.10},
}

def get_ranges(sym, now):
    df = yf.download(YMAP[sym], period="2d", interval="15m", progress=False, auto_adjust=True)
    if df.empty: return None,None,None,None,None,None
    if isinstance(df.columns,pd.MultiIndex): df.columns=df.columns.get_level_values(0)
    df.columns=[str(c).lower() for c in df.columns]
    df.index = pd.to_datetime(df.index, utc=True)
    cur = float(df["close"].iloc[-1])

    # Asian range 22:00-07:00 GMT
    asian_start = (now.replace(hour=22, minute=0, second=0, microsecond=0) - timedelta(days=1))
    asian_end = now.replace(hour=7, minute=0, second=0, microsecond=0)
    asian = df[(df.index >= asian_start) & (df.index < asian_end)]
    if asian.empty: return None,None,None,None,None,None
    asian_high = float(asian["high"].max())
    asian_low = float(asian["low"].min())

    # London range 07:00-13:00 GMT for NY breakout
    lon_start = now.replace(hour=7, minute=0, second=0, microsecond=0)
    lon_end = now.replace(hour=13, minute=0, second=0, microsecond=0)
    london = df[(df.index >= lon_start) & (df.index < lon_end)]
    if london.empty:
        london_high, london_low = asian_high, asian_low
    else:
        london_high = float(london["high"].max())
        london_low = float(london["low"].min())

    return asian_high, asian_low, london_high, london_low, cur, df

def main():
    ts=datetime.now(timezone.utc).isoformat()
    now = datetime.now(timezone.utc)

    is_london = 7 <= now.hour < 16 # 10am-7pm Uganda
    is_newyork = 13 <= now.hour < 20 # 4pm-11pm Uganda
    is_trading = is_london or is_newyork
    session = "LONDON" if is_london and not is_newyork else "NY" if is_newyork and not is_london else "OVERLAP" if is_london and is_newyork else "CLOSED"

    opens={}
    if os.path.exists("open_signals.json"):
        try:
            with open("open_signals.json") as f: opens=json.load(f)
        except: opens={}
    for s in SYMBOLS:
        if s not in opens: opens[s]=[]
        if isinstance(opens[s],dict): opens[s]=[opens[s]]

    daily_pnl=0; trades_today=0
    if os.path.exists("closed_trades.csv"):
        try:
            with open("closed_trades.csv") as f:
                for r in csv.DictReader(f):
                    if ts[:10] in r["timestamp_utc"]:
                        trades_today+=1
                        daily_pnl+=float(r.get("usd","0"))
        except: pass
    if daily_pnl <= -1.2:
        print(f"STOP loss ${daily_pnl}")
        return

    for sym in SYMBOLS:
        cfg=CONF[sym]
        try:
            asian_high, asian_low, london_high, london_low, cur, df = get_ranges(sym, now)
            if asian_high is None: continue

            # CLOSE
            remain=[]
            for tr in opens[sym]:
                e=float(tr["entry_price"]); is_buy=tr["direction"]=="BUY"
                pips=(cur-e)/cfg["pip"] if is_buy else (e-cur)/cfg["pip"]
                usd=pips*cfg["usd_per_pip"]
                if pips>=cfg["tp_pips"] or pips<=-cfg["sl_pips"]:
                    outcome="WIN" if pips>0 else "LOSS"
                    ex=os.path.exists("closed_trades.csv")
                    with open("closed_trades.csv","a",newline="") as f:
                        w=csv.DictWriter(f,fieldnames=["timestamp_utc","symbol","direction","lot","entry_price","exit_price","outcome","pips","usd","tp_usd","sl_usd","session","opened_at"])
                        if not ex: w.writeheader()
                        w.writerow({"timestamp_utc":ts,"symbol":sym,"direction":tr["direction"],"lot":LOT_SIZE,"entry_price":e,"exit_price":cur,"outcome":outcome,"pips":round(pips,1),"usd":round(usd,2),"tp_usd":round(cfg["tp_pips"]*cfg["usd_per_pip"],2),"sl_usd":round(cfg["sl_pips"]*cfg["usd_per_pip"],2),"session":tr.get("session",""),"opened_at":tr["opened_at"]})
                else:
                    tr["current_price"]=cur; tr["current_pips"]=round(pips,1); tr["current_usd"]=round(usd,2); remain.append(tr)
            opens[sym]=remain

            # OPEN
            if is_trading and len(opens[sym])==0 and trades_today<6:
                buf=0.00015
                if is_london: # London breakout Asian range
                    ref_high, ref_low = asian_high, asian_low
                    ref_name = "ASIAN"
                else: # NY breakout London range
                    ref_high, ref_low = london_high, london_low
                    ref_name = "LONDON"

                if cur > ref_high + buf:
                    direction="BUY"; entry=cur
                elif cur < ref_low - buf:
                    direction="SELL"; entry=cur
                else:
                    continue

                sl=entry-cfg["sl_pips"]*cfg["pip"] if direction=="BUY" else entry+cfg["sl_pips"]*cfg["pip"]
                tp=entry+cfg["tp_pips"]*cfg["pip"] if direction=="BUY" else entry-cfg["tp_pips"]*cfg["pip"]

                opens[sym].append({
                    "direction":direction,"lot":LOT_SIZE,"entry_price":entry,"stop_loss":sl,"take_profit":tp,
                    "tp_pips":cfg["tp_pips"],"sl_pips":cfg["sl_pips"],
                    "tp_usd":round(cfg["tp_pips"]*cfg["usd_per_pip"],2),
                    "sl_usd":round(cfg["sl_pips"]*cfg["usd_per_pip"],2),
                    "opened_at":ts,"current_price":cur,"current_pips":0,"current_usd":0,
                    "asian_high":asian_high,"asian_low":asian_low,
                    "london_high":london_high,"london_low":london_low,
                    "break_ref":ref_name,"ref_high":ref_high,"ref_low":ref_low,
                    "session":session,"strategy":"LONDON_NY_BREAKOUT"
                })
        except Exception as e:
            print(f"{sym} ERR {e}")

    with open("open_signals.json","w") as f: json.dump(opens,f,indent=2)
    os.makedirs("Bot",exist_ok=True)
    import shutil
    for fn in ["open_signals.json","closed_trades.csv"]:
        if os.path.exists(fn):
            try: shutil.copy(fn,f"Bot/{fn}")
            except: pass

if __name__=="__main__": main()
