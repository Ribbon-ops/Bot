<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LIVE $10 SCALPER</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:'JetBrains Mono',monospace}
body{background:#0a0e13;color:#c8d6e5;min-height:100vh}
.top{background:#111a24;border-bottom:1px solid #1e2f40;padding:14px 18px;display:flex;justify-content:space-between;align-items:center}
.top b{color:#fff;font-size:18px}.live{color:#00ff88;animation:pulse 1s infinite} @keyframes pulse{0%{opacity:1}50%{opacity:.4}}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px} @media(max-width:700px){.grid{grid-template-columns:1fr}}
.card{background:#111a24;border:1px solid #1e2f40;border-radius:12px;padding:14px}
.card h3{color:#fff;font-size:13px;margin-bottom:10px;letter-spacing:1px}
.sym{font-size:20px;color:#fff;font-weight:600}.BUY{color:#00ff88;background:#00ff8820;padding:2px 8px;border-radius:6px;font-size:12px}.SELL{color:#ff4757;background:#ff475720;padding:2px 8px;border-radius:6px;font-size:12px}
.p{font-size:22px;font-weight:600;margin:6px 0}.pos{color:#00ff88}.neg{color:#ff4757}
.small{font-size:11px;color:#6b7d8f}.row{display:flex;justify-content:space-between;margin:4px 0;font-size:12px}
.log{max-height:320px;overflow:auto;font-size:11px;line-height:18px}.log div{border-bottom:1px solid #1a2633;padding:4px 0}
.win{color:#00ff88}.loss{color:#ff4757}
</style></head>
<body>
<div class="top"><b>⚡ $10 LIVE SCALPER <span class="live">● LIVE</span></b><span class="small" id="time"></span></div>

<div class="grid">
  <div class="card"><h3>🔴 OPEN TRADES (LIVE PRICE)</h3><div id="open">loading...</div></div>
  <div class="card"><h3>📊 ACCOUNT</h3><div id="stats"></div></div>
</div>

<div class="grid">
  <div class="card"><h3>📜 SIGNALS LOG (ALL SCANS)</h3><div class="log" id="slog"></div></div>
  <div class="card"><h3>✅ CLOSED TRADES</h3><div class="log" id="clog"></div></div>
</div>

<script>
async function load(){
 const d=Date.now();
 document.getElementById('time').innerText=new Date().toLocaleString();
 try{
  let j=await fetch('open_signals.json?'+d).then(r=>r.json());
  let html=''; let totalP=0, total$=0, count=0;
  for(let s in j){
   for(let t of j[s]){
    count++;
    let cur=t.current_price, e=t.entry_price;
    let pip=s=='XAUUSD'?0.1:s=='USDJPY'?0.01:0.0001;
    let pips=t.direction=='BUY'?(cur-e)/pip:(e-cur)/pip;
    let usd=pips*0.01;
    totalP+=pips; total$+=usd;
    html+=`<div style="border-bottom:1px solid #1e2f40;padding:10px 0">
     <div style="display:flex;justify-content:space-between"><span class="sym">${s}</span><span class="${t.direction}">${t.direction}</span></div>
     <div class="p ${pips>=0?'pos':'neg'}">${pips>=0?'+':''}${pips.toFixed(2)}p <span style="font-size:14px">$${usd>=0?'+':''}${usd.toFixed(4)}</span></div>
     <div class="row"><span class="small">Entry</span><span>${e.toFixed(5)}</span></div>
     <div class="row"><span class="small">Now</span><span>${cur.toFixed(5)}</span></div>
     <div class="row"><span class="small">SL / TP</span><span>${t.stop_loss.toFixed(5)} / ${t.take_profit.toFixed(5)}</span></div>
    </div>`;
   }
  }
  document.getElementById('open').innerHTML=html||'<span class="small">No open trades - waiting for next 2min scan</span>';
  document.getElementById('stats').innerHTML=`
   <div class="p ${total$>=0?'pos':'neg'}" style="font-size:28px">$${total$>=0?'+':''}${total$.toFixed(4)}</div>
   <div class="row"><span class="small">Open Trades</span><span>${count}</span></div>
   <div class="row"><span class="small">Total Pips</span><span class="${totalP>=0?'pos':'neg'}">${totalP.toFixed(2)}p</span></div>
   <div class="row"><span class="small">Strategy</span><span>1.5p TP / 0.8p SWEEP</span></div>
   <div class="row"><span class="small">Market</span><span style="color:#00ff88">REAL YAHOO</span></div>
  `;
 }catch(e){document.getElementById('open').innerHTML='<span class="small">Waiting first scan... '+e+'</span>'}

 try{
  let txt=await fetch('signals_log.csv?'+d).then(r=>r.text());
  let rows=txt.trim().split('\n').reverse().slice(0,30);
  let h='';
  for(let r of rows){ if(r.includes('symbol'))continue; let c=r.split(','); if(!c[1])continue; h+=`<div><span class="small">${c[0].slice(11,19)}</span> <b>${c[1]}</b> <span class="${c[2]}">${c[2]}</span> @${c[3]} TP:${c[5]}</div>`; }
  document.getElementById('slog').innerHTML=h||'no logs yet';
 }catch(e){}

 try{
  let txt=await fetch('closed_trades.csv?'+d).then(r=>r.text());
  let rows=txt.trim().split('\n').reverse().slice(0,30);
  let h='';
  for(let r of rows){ if(r.includes('symbol'))continue; let c=r.split(','); if(!c[1])continue; h+=`<div><span class="small">${c[0].slice(11,19)}</span> <b>${c[1]}</b> ${c[2]} <span class="${c[5].toLowerCase()}">${c[5]} ${c[6]}p</span> ${c[8]}</div>`; }
  document.getElementById('clog').innerHTML=h||'no closed yet';
 }catch(e){}
}
load(); setInterval(load,5000);
</script></body></html>
