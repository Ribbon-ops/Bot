import json, os, csv
from datetime import datetime, timezone, timedelta
import yfinance as yf
import pandas as pd

# === $100 STANDARD SETTINGS ===
ACCOUNT_BALANCE = 100
LOT_SIZE = 0.01 # $0.10 per pip for EURUSD/GBPUSD
SYMBOLS = ["EURUSD","GBPUSD"]
YMAP = {"EURUSD":"EURUSD=X","GBPUSD":"GBPUSD=X"}
CONF = {
 "EURUSD":{"pip":0.0001,"tp_pips":8.0,"sl_pips":4.0, "usd_per_pip":0.10},
 "GBPUSD":{"pip":0.0001,"tp_pips":8.0,"sl_pips":4.0, "usd_per_pip":0.10},
}
LOT = LOT_SIZE

def get_asian_range(sym):
    df = yf.download(YMAP[sym], period="2d", interval="15m", progress=False, auto_adjust=True)
    if df.empty: return None,None,None,None
    if isinstance(df.columns,pd.MultiIndex): df.columns=df.columns.get_level_values(0)
    df.columns=[str(c).lower() for c in df.columns]
    df.index = pd.to_datetime(df.index, utc=True)
    now = datetime.now(timezone.utc)
    asian_start = (now.replace(hour=22, minute=0, second=0, microsecond=0) - timedelta(days=1))
    asian_end = now.replace(hour=7, minute=0, second=0, microsecond=0)
    asian = df[(df.index >= asian_start) & (df.index < asian_end)]
    if asian.empty: return None,None,None,None
    high = float(asian["high"].max())
    low = float(asian["low"].min())
    cur = float(df["close"].iloc[-1])
    # volatility filter - skip low vol days
    rng = (high-low)/CONF[sym]["pip"]
    return high, low, cur, rng

def main():
    ts=datetime.now(timezone.utc).isoformat()
    now_gmt = datetime.now(timezone.utc)
    is_london = 7 <= now_gmt.hour < 16

    opens={}
    if os.path.exists("open_signals.json"):
        try:
            with open("open_signals.json") as f: opens=json.load(f)
        except: opens={}
    for s in SYMBOLS:
        if s not in opens: opens[s]=[]
        if isinstance(opens[s],dict): opens[s]=[opens[s]]

    # Daily lock - protect $100
    daily_pnl=0; trades_today=0
    if os.path.exists("closed_trades.csv"):
        try:
            with open("closed_trades.csv") as f:
                for r in csv.DictReader(f):
                    if ts[:10] in r["timestamp_utc"]:
                        trades_today+=1
                        daily_pnl+=float(r.get("usd","0"))
        except: pass
    if daily_pnl <= -1.2: # -$1.20 max loss stop
        print(f"STOP loss hit {daily_pnl}")
        return

    for sym in SYMBOLS:
        cfg=CONF[sym]
        try:
            asian_high, asian_low, cur, rng = get_asian_range(sym)
            if asian_high is None: continue
            if rng < 15: # Asian range too small = no breakout today
                print(f"{sym} low vol {rng:.1f} skip")
                continue

            # === CLOSE CHECK ===
            remain=[]
            for tr in opens[sym]:
                e=float(tr["entry_price"]); is_buy=tr["direction"]=="BUY"
                pips=(cur-e)/cfg["pip"] if is_buy else (e-cur)/cfg["pip"]
                usd=pips*cfg["usd_per_pip"]
                if pips>=cfg["tp_pips"] or pips<=-cfg["sl_pips"]:
                    outcome="WIN" if pips>0 else "LOSS"
                    ex=os.path.exists("closed_trades.csv")
                    with open("closed_trades.csv","a",newline="") as f:
                        w=csv.DictWriter(f,fieldnames=["timestamp_utc","symbol","direction","lot","entry_price","exit_price","outcome","pips","usd","tp_usd","sl_usd","opened_at"])
                        if not ex: w.writeheader()
                        w.writerow({
                            "timestamp_utc":ts,"symbol":sym,"direction":tr["direction"],"lot":LOT,
                            "entry_price":e,"exit_price":cur,"outcome":outcome,
                            "pips":round(pips,1),"usd":round(usd,2),
                            "tp_usd":round(cfg["tp_pips"]*cfg["usd_per_pip"],2),
                            "sl_usd":round(cfg["sl_pips"]*cfg["usd_per_pip"],2),
                            "opened_at":tr["opened_at"]
                        })
                else:
                    tr["current_price"]=cur
                    tr["current_pips"]=round(pips,1)
                    tr["current_usd"]=round(usd,2)
                    remain.append(tr)
            opens[sym]=remain

            # === OPEN - LONDON BREAKOUT ===
            if is_london and len(opens[sym])==0 and trades_today<4:
                buf=0.00015
                if cur > asian_high + buf:
                    direction="BUY"
                elif cur < asian_low - buf:
                    direction="SELL"
                else:
                    continue
                entry=cur
                sl=entry-cfg["sl_pips"]*cfg["pip"] if direction=="BUY" else entry+cfg["sl_pips"]*cfg["pip"]
                tp=entry+cfg["tp_pips"]*cfg["pip"] if direction=="BUY" else entry-cfg["tp_pips"]*cfg["pip"]
                opens[sym].append({
                    "direction":direction,
                    "lot":LOT,
                    "entry_price":entry,
                    "stop_loss":sl,
                    "take_profit":tp,
                    "tp_pips":cfg["tp_pips"],
                    "sl_pips":cfg["sl_pips"],
                    "tp_usd":round(cfg["tp_pips"]*cfg["usd_per_pip"],2),
                    "sl_usd":round(cfg["sl_pips"]*cfg["usd_per_pip"],2),
                    "opened_at":ts,
                    "current_price":cur,
                    "current_pips":0,
                    "current_usd":0,
                    "asian_high":asian_high,
                    "asian_low":asian_low,
                    "strategy":"LONDON_BREAKOUT"
                })
                print(f"OPEN {sym} {direction} LOT {LOT} TP ${cfg['tp_pips']*cfg['usd_per_pip']}")

        except Exception as e:
            print(f"{sym} ERR {e}")

    with open("open_signals.json","w") as f: json.dump(opens,f,indent=2)
    # copy to Bot folder for dashboard
    os.makedirs("Bot",exist_ok=True)
    import shutil
    for fn in ["open_signals.json","closed_trades.csv"]:
        if os.path.exists(fn):
            try: shutil.copy(fn,f"Bot/{fn}")
            except: pass

if __name__=="__main__": main()
