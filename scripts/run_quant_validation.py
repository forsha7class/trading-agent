"""Orchestrate Phase 2 quant validation — reproducible, fee-aware, regime-aware."""
import json, time, math, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ingestion.market_data import fetch_klines
from ingestion.dataset import store_dataset, load_dataset
from storage.database import init_db
from storage.experiments import create_experiment
from evaluation.strategy_eval import evaluate_all
from evaluation.baseline_compare import compare
from evaluation.labels import make_labels
from evaluation.prob_model import train_prob_model, build_feature_matrix
from evaluation.calibration_ext import bucket_report
from evaluation.notrade_analysis import analyze as notrade_analyze
from evaluation.regime_analysis import regime_report
from evaluation.backtest import run_backtest, walk_forward

SYMBOLS=["BTCUSDT","ETHUSDT"]
LIMIT=600

def fetch_and_store(symbol, tf, limit):
    init_db()
    try:
        candles=fetch_klines(symbol, tf, limit=limit)
        did=store_dataset(candles, symbol, tf, source="binance")
        return candles, did
    except Exception as e:
        print(f"fetch {symbol} {tf} failed: {e}")
        return [], 0

def run():
    init_db()
    results={}
    for sym in SYMBOLS:
        candles, did = fetch_and_store(sym, "1h", LIMIT)
        if not candles:
            continue
        print(f"{sym}: {len(candles)} candles {candles[0]['close']:.0f}->{candles[-1]['close']:.0f} dataset {did}")
        strat=evaluate_all(candles)
        base=compare(candles)
        split=int(len(candles)*0.7)
        train=candles[:split]
        test=candles[split:]
        m=train_prob_model(train, horizon=4)
        X_test, _ = build_feature_matrix(test)
        labs_test=make_labels(test, horizon=4, threshold=0.005)
        labs_test_aligned=[l["label"] for l in labs_test[-len(X_test):]] if len(X_test) else []
        preds=m.predict(X_test) if len(X_test) else []
        if preds and labs_test_aligned:
            pups=[p["p_up"] for p in preds]
            buckets=bucket_report(pups, labs_test_aligned, target="up")
            brier=sum((p["p_up"]-(1 if lab=="up" else 0))**2 for p,lab in zip(preds,labs_test_aligned))/len(preds) if preds else 0
        else:
            buckets=[]; brier=0
        wf=walk_forward(candles, splits=3)
        nt=notrade_analyze(candles)
        rr=regime_report(candles)
        rb=run_backtest(candles)["metrics"]
        results[sym]={
            "candles":len(candles),"dataset_id":did,
            "strategies":{k:{"metrics":{kk:vv for kk,vv in v["metrics"].items() if kk!="equity_curve"}, "trade_count":v["metrics"]["trade_count"]} for k,v in strat.items()},
            "baselines":base,
            "prob":{"brier_up":round(brier,4),"buckets":buckets,"pred_sample":preds[:2]},
            "walk_forward":wf,
            "notrade":nt,
            "regime":rr,
            "realistic_backtest":rb,
        }
        create_experiment(f"quant_{sym}_{int(time.time())}", config={"fee":0.0004,"slippage":0.0005,"limit":LIMIT,"timeframe":"1h"},
                          dataset={"symbol":sym,"row_count":len(candles),"dataset_id":did},
                          metrics={"pnl":rb.get("pnl"),"win_rate":rb.get("win_rate")}, conclusion="auto quant run", status="EXPERIMENTAL",
                          versions={"model":"0.2.0","strategy":"0.1.0","feature":"0.1.0"})
    out_path=Path(__file__).parent.parent / "docs" / "quant_results.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"wrote {out_path}")
    return results

if __name__=="__main__":
    r=run()
    for sym, v in r.items():
        print(f"\n=== {sym} ===")
        for k,sv in v["strategies"].items():
            print(f" {k}: trades {sv['trade_count']} wr {sv['metrics']['win_rate']} pf {sv['metrics']['profit_factor']} exp {sv['metrics']['expectancy']}")
        print(f" realistic pnl {v['realistic_backtest']['pnl']} buy_hold {v['baselines']['buy_hold']}")
        print(f" notrade rejection {v['notrade']['rejection_rate']} ev_traded {v['notrade']['ev_traded']} filter_adds {v['notrade']['filter_adds_value']}")
        print(f" brier {v['prob']['brier_up']} buckets {v['prob']['buckets'][:2]}")
