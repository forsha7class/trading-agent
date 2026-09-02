"""Entry — run decision pipeline, paper trading, health."""
from __future__ import annotations
import argparse, json, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

def cmd_run(args):
    from agents.coordinator import Coordinator
    from storage.database import init_db
    init_db()
    c=Coordinator()
    for sym in (args.symbols or ["BTCUSDT"]):
        dec=c.run(symbol=sym, timeframe=args.timeframe, equity=args.equity)
        # dataclass -> dict
        d = dec.__dict__ if hasattr(dec,'__dict__') else dec
        if hasattr(dec,'to_dict'): d=dec.to_dict()
        print(json.dumps(d, indent=2, default=str))
        prob=d.get("probability") or {}
        if not isinstance(prob, dict): prob=prob.__dict__ if hasattr(prob,'__dict__') else {}
        print(f"\n{sym} SIGNAL: {d.get('decision')}  prob up={prob.get('p_up')} down={prob.get('p_down')} flat={prob.get('p_flat')}  regime={d.get('regime')}  RR={d.get('rr')}  risk={d.get('risk_pct')}  reason={d.get('reason')}\n")

def cmd_backtest(args):
    from ingestion.market_data import fetch_klines
    from evaluation.backtest import run_backtest, walk_forward
    from evaluation.metrics import brier_score, log_loss
    candles=fetch_klines(args.symbol, args.timeframe, limit=args.limit)
    print(f"fetched {len(candles)} candles {args.symbol} {args.timeframe}")
    res=run_backtest(candles, config={"fee":0.0004,"slippage":0.0005,"equity":10000,"risk_per_trade":0.005,"min_rr":1.5})
    print(json.dumps(res["metrics"], indent=2))
    if args.walk:
        wf=walk_forward(candles, splits=3)
        print("walk-forward:", json.dumps(wf, indent=2, default=str))

def cmd_health(args):
    from storage.database import init_db, get_db
    init_db()
    db=get_db()
    mods=[]
    for m in ["decisions","candles","paper_trades","system_events"]:
        try:
            n=db.execute(f"SELECT count(*) FROM {m}").fetchone()[0]
            mods.append(f"{m}: {n} rows ONLINE")
        except Exception as e:
            mods.append(f"{m}: OFFLINE {e}")
    print("\n".join(mods))
    # try pipeline dry-run without network
    try:
        from features.technical import build_features
        from regime.detector import detect_regime
        print("FEATURE ENGINE ONLINE\nREGIME ENGINE ONLINE")
    except Exception as e:
        print(f"ENGINE OFFLINE {e}")

def cmd_dashboard(args):
    import uvicorn
    from dashboard.app import app
    uvicorn.run(app, host="0.0.0.0", port=args.port)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="cmd")
    r=sub.add_parser("run"); r.add_argument("--symbols", nargs="*", default=None); r.add_argument("--timeframe", default="1h"); r.add_argument("--equity", type=float, default=10000)
    b=sub.add_parser("backtest"); b.add_argument("--symbol", default="BTCUSDT"); b.add_argument("--timeframe", default="1h"); b.add_argument("--limit", type=int, default=500); b.add_argument("--walk", action="store_true")
    h=sub.add_parser("health")
    d=sub.add_parser("dashboard"); d.add_argument("--port", type=int, default=8000)
    args=p.parse_args()
    if args.cmd=="run": cmd_run(args)
    elif args.cmd=="backtest": cmd_backtest(args)
    elif args.cmd=="health": cmd_health(args)
    elif args.cmd=="dashboard": cmd_dashboard(args)
    else:
        # default: health + single run
        class A: symbols=["BTCUSDT"]; timeframe="1h"; equity=10000
        print("=== HEALTH ==="); cmd_health(A())
        print("\n=== RUN BTCUSDT ==="); cmd_run(A())
