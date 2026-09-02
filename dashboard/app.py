"""Dashboard — FastAPI + static HTML. ponytail: no React build; upgrade to SPA later."""
from __future__ import annotations
import time, json, sqlite3
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app=FastAPI(title="Smart Crypto Trading Agent")

def _db():
    try:
        from storage.database import get_db
        return get_db()
    except ImportError:
        from trading_agent.storage.database import get_db
        return get_db()

@app.get("/health")
def health():
    mods={}
    for m in ["data_feed","feature_engine","regime_engine","strategy_engine","risk_engine","ai_layer","database"]:
        try:
            if m=="database":
                _db().execute("SELECT 1")
            mods[m]="ONLINE"
        except Exception as e:
            mods[m]=f"OFFLINE: {e}"
    return {"status":"ok","modules":mods,"ts":int(time.time()*1000)}

@app.get("/api/decisions")
def decisions(limit:int=50):
    db=_db()
    rows=db.execute("SELECT * FROM decisions ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/signals")
def signals():
    db=_db()
    rows=db.execute("SELECT symbol, decision as signal, regime, probability, rr, risk_pct, ts, reason FROM decisions ORDER BY ts DESC LIMIT 20").fetchall()
    return [dict(r) for r in rows]

@app.get("/api/performance")
def performance():
    db=_db()
    try:
        rows=db.execute("SELECT pnl, fees FROM paper_trades WHERE status='CLOSED'").fetchall()
        pnls=[r["pnl"] for r in rows if r["pnl"] is not None]
        wins=sum(1 for x in pnls if x>0)
        wr=wins/len(pnls) if pnls else 0
        pf=sum(x for x in pnls if x>0)/abs(sum(x for x in pnls if x<=0) or 1)
        return {"trades":len(pnls),"win_rate":wr,"profit_factor":pf,"pnl":sum(pnls) if pnls else 0}
    except Exception as e:
        return {"error":str(e)}

@app.get("/api/quant")
def quant():
    import pathlib as _p
    q=_p.Path(__file__).parent.parent / "docs" / "quant_results.json"
    return json.loads(q.read_text()) if q.exists() else {}

@app.get("/api/phase3")
def phase3(symbol: str | None = None):
    import pathlib as _p
    q=_p.Path(__file__).parent.parent / "docs" / "phase3_results.json"
    if not q.exists():
        return {}
    j=json.loads(q.read_text())
    if symbol:
        return j.get(symbol, {})
    return j

@app.get("/api/robustness")
def robustness(symbol:str="BTCUSDT"):
    import pathlib as _p
    q=_p.Path(__file__).parent.parent / "docs" / "phase3_results.json"
    if not q.exists():
        return {}
    j=json.loads(q.read_text())
    v=j.get(symbol, {})
    return {"walk_forward": v.get("walk_forward"), "param_stability": v.get("param_stability"), "cost_sensitivity": v.get("cost_sensitivity"), "monte_carlo": v.get("monte_carlo"), "drawdown": v.get("drawdown")}

@app.get("/api/regime-performance")
def regime_perf(symbol:str="BTCUSDT"):
    import pathlib as _p
    # prefer phase3 if present
    q3=_p.Path(__file__).parent.parent / "docs" / "phase3_results.json"
    if q3.exists():
        j=json.loads(q3.read_text())
        if symbol in j and "regime" in j[symbol]:
            return j[symbol]["regime"]
    q=_p.Path(__file__).parent.parent / "docs" / "quant_results.json"
    if not q.exists():
        return {}
    j=json.loads(q.read_text())
    return j.get(symbol, {}).get("regime", {})

@app.get("/api/calibration")
def calibration(symbol:str="BTCUSDT"):
    import pathlib as _p
    q3=_p.Path(__file__).parent.parent / "docs" / "phase3_results.json"
    if q3.exists():
        j=json.loads(q3.read_text())
        if symbol in j and "isotonic" in j[symbol]:
            return j[symbol]["isotonic"]
    q=_p.Path(__file__).parent.parent / "docs" / "quant_results.json"
    if not q.exists():
        return {}
    j=json.loads(q.read_text())
    return j.get(symbol, {}).get("prob", {})

@app.get("/api/notrade")
def notrade(symbol:str="BTCUSDT"):
    import pathlib as _p
    q3=_p.Path(__file__).parent.parent / "docs" / "phase3_results.json"
    if q3.exists():
        j=json.loads(q3.read_text())
        if symbol in j and "notrade" in j[symbol]:
            return j[symbol]["notrade"]
    q=_p.Path(__file__).parent.parent / "docs" / "quant_results.json"
    if not q.exists():
        return {}
    j=json.loads(q.read_text())
    return j.get(symbol, {}).get("notrade", {})

@app.get("/api/paper")
def paper():
    try:
        db=_db()
        rows=db.execute("SELECT * FROM paper_trades ORDER BY opened_at DESC LIMIT 50").fetchall()
        open_rows=[dict(r) for r in rows if r["status"]=="OPEN"]
        closed=[dict(r) for r in rows if r["status"]=="CLOSED"]
        return {"open":open_rows,"closed":closed,"count":len(rows)}
    except Exception as e:
        return {"error":str(e)}

@app.get("/api/paper-detailed")
def paper_detailed(symbol:str="BTCUSDT"):
    import pathlib as _p
    q=_p.Path(__file__).parent.parent / "docs" / "phase3_results.json"
    if not q.exists():
        return {}
    j=json.loads(q.read_text())
    v=j.get(symbol, {})
    return {"mae_mfe_sample": v.get("mae_mfe_sample"), "gates": v.get("gates"), "thresholds": v.get("thresholds")}

@app.get("/api/experiments")
def experiments():
    try:
        from storage.experiments import list_experiments
        return list_experiments()[:20]
    except Exception as e:
        return {"error":str(e)}

@app.get("/api/risk")
def risk_status():
    db=_db()
    dec=db.execute("SELECT decision,reason FROM decisions ORDER BY ts DESC LIMIT 100").fetchall()
    veto=sum(1 for r in dec if r["decision"]=="NO_TRADE")
    return {"last_100":len(dec),"veto_count":veto,"veto_rate":round(veto/max(1,len(dec)),3)}

@app.get("/api/candles/{symbol}")
def candles(symbol:str, interval:str="1h", limit:int=100):
    db=_db()
    rows=db.execute("SELECT * FROM candles WHERE symbol=? AND timeframe=? ORDER BY open_time DESC LIMIT ?", (symbol,interval,limit)).fetchall()
    return [dict(r) for r in rows]

@app.get("/", response_class=HTMLResponse)
def index():
    return """
<!doctype html>
<html><head><meta charset=utf-8><title>Smart Trading Agent</title>
<style>body{font-family:system-ui, sans-serif; margin:20px; background:#0b0e14; color:#cbd5e1}
.card{background:#131722; border:1px solid #1e293b; border-radius:10px; padding:16px; margin:12px 0}
h1{color:#38bdf8} table{width:100%; border-collapse:collapse} th,td{padding:6px 8px; border-bottom:1px solid #1e293b; text-align:left}
.badge{display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px}
.long{background:#065f46; color:#6ee7b7} .short{background:#7f1d1d; color:#fca5a5} .no{background:#334155; color:#94a3b8}
.grid{display:grid; grid-template-columns:1fr 1fr; gap:12px}
.btn{padding:6px 10px; border-radius:6px; border:1px solid #334155; background:#1e293b; color:#cbd5e1; cursor:pointer; margin:2px}
</style>
</head><body>
<h1>Smart Crypto Trading Agent</h1>
<div class=grid>
<div class=card><h3>System Health</h3><pre id=health>loading...</pre></div>
<div class=card><h3>Performance</h3><pre id=perf>loading...</pre></div>
</div>
<div class=card><h3>Signal Board</h3><table><thead><tr><th>PAIR</th><th>SIGNAL</th><th>REGIME</th><th>R:R</th><th>RISK</th><th>REASON</th><th>TIME</th></tr></thead><tbody id=board></tbody></table></div>
<div class=card><h3>Phase 3 — Robustness / Regime / Calibration / Paper</h3>
<div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:8px">
<button class=btn onclick="loadQ('BTCUSDT')">BTCUSDT</button><button class=btn onclick="loadQ('ETHUSDT')">ETHUSDT</button>
<button class=btn onclick="loadRobust('BTCUSDT')">Robustness BTC</button><button class=btn onclick="loadRobust('ETHUSDT')">Robustness ETH</button>
<button class=btn onclick="loadCalib('BTCUSDT')">Calibration BTC</button><button class=btn onclick="loadPaper('BTCUSDT')">Paper BTC</button>
</div>
<pre id=quant style="max-height:360px; overflow:auto">loading...</pre>
<pre id=robust style="max-height:260px; overflow:auto"></pre>
</div>
<div class=card><h3>Signal History</h3><pre id=history>loading...</pre></div>
<script>
async function j(u){const r=await fetch(u); return r.json()}
async function loadQ(sym){
  const q=await j('/api/phase3?symbol='+sym); 
  document.getElementById('quant').textContent='PHASE3 '+sym+'\\n'+JSON.stringify(q,null,2).slice(0,8000);
}
async function loadRobust(sym){
  const r=await j('/api/robustness?symbol='+sym);
  const c=await j('/api/calibration?symbol='+sym);
  const p=await j('/api/paper-detailed?symbol='+sym);
  document.getElementById('robust').textContent='ROBUST '+sym+'\\n'+JSON.stringify(r,null,2).slice(0,4000)+'\\nCALIB '+JSON.stringify(c,null,2).slice(0,2000)+'\\nPAPER '+JSON.stringify(p,null,2).slice(0,2000);
}
async function loadCalib(sym){
  const c=await j('/api/calibration?symbol='+sym);
  document.getElementById('robust').textContent='CALIBRATION '+sym+'\\n'+JSON.stringify(c,null,2);
}
async function loadPaper(sym){
  const p=await j('/api/paper-detailed?symbol='+sym);
  document.getElementById('robust').textContent='PAPER '+sym+'\\n'+JSON.stringify(p,null,2);
}
async function refresh(){
  const h=await j('/health'); document.getElementById('health').textContent=JSON.stringify(h,null,2);
  const p=await j('/api/performance'); document.getElementById('perf').textContent=JSON.stringify(p,null,2);
  const s=await j('/api/signals'); const tb=document.getElementById('board'); tb.innerHTML='';
  for(const row of s){
    const tr=document.createElement('tr');
    const cls=row.signal==='LONG'?'long':row.signal==='SHORT'?'short':'no';
    tr.innerHTML=`<td>${row.symbol}</td><td><span class='badge ${cls}'>${row.signal}</span></td><td>${row.regime||''}</td><td>${row.rr||''}</td><td>${row.risk_pct||''}</td><td style='max-width:280px; overflow:hidden; text-overflow:ellipsis'>${row.reason||''}</td><td>${new Date(row.ts).toLocaleString()}</td>`;
    tb.appendChild(tr);
  }
  const d=await j('/api/decisions?limit=10'); document.getElementById('history').textContent=JSON.stringify(d,null,2);
  if(!window._qLoaded){ loadQ('BTCUSDT'); window._qLoaded=true; }
}
refresh(); setInterval(refresh, 8000);
</script>
</body></html>
"""

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
