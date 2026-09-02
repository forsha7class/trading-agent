"""Phase 2 subsystem tests — dataset, labels, prob, paper engine, experiment registry."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ingestion.dataset import store_dataset, load_dataset, dataset_metadata
from storage.database import init_db
from evaluation.labels import make_labels
from evaluation.prob_model import build_feature_matrix, train_prob_model, ProbModel
from evaluation.calibration_ext import bucket_report
from storage.experiments import create_experiment, list_experiments, set_status
from portfolio.paper_engine import PaperEngine
from evaluation.strategy_eval import evaluate_all
import numpy as np

def test_dataset_roundtrip():
    init_db()
    candles=[{"symbol":"PH2","timeframe":"1h","open":100+i,"high":101+i,"low":99+i,"close":100.5+i,"volume":10,"open_time":i*3600000,"close_time":i*3600000+3599999} for i in range(10)]
    did=store_dataset(candles,"PH2","1h",source="test_ph2")
    assert did>0
    loaded=load_dataset("PH2","1h")
    assert any(c["symbol"]=="PH2" for c in loaded)
    meta=dataset_metadata(did)
    assert meta and meta["row_count"]>=10
    print("dataset roundtrip PASS")

def test_labels():
    candles=[{"close":100+i*0.2,"close_time":i*3600000} for i in range(20)]
    for c in candles: c.setdefault("open",c["close"]); c.setdefault("high",c["close"]+0.5); c.setdefault("low",c["close"]-0.5)
    labs=make_labels(candles, horizon=4, threshold=0.005)
    assert len(labs)==20
    assert labs[-1]["label"] is None  # no future
    assert labs[5]["label"] in ("up","down","flat")
    print("labels PASS", labs[5])

def test_prob_model():
    candles=[{"open":100+i*0.1,"high":100+i*0.1+0.5,"low":100+i*0.1-0.5,"close":100+i*0.1+0.2,"volume":100.0,
              "open_time":i*3600000,"close_time":i*3600000+3599999,"symbol":"BTCUSDT","timeframe":"1h"} for i in range(120)]
    X,names=build_feature_matrix(candles)
    assert X.shape[0]>0 and X.shape[1]==7
    m=train_prob_model(candles, horizon=4)
    assert m.fitted
    preds=m.predict(X[:5])
    for p in preds:
        assert abs(p["p_up"]+p["p_down"]+p["p_flat"]-1)<1e-6
        assert 0.05<=p["p_up"]<=0.85
    print("prob_model PASS", preds[0])

def test_calibration_buckets():
    probs=[0.52,0.62,0.71,0.81,0.55,0.65]
    labels=["up","up","down","up","flat","up"]
    rep=bucket_report(probs, labels, target="up")
    assert len(rep)==6
    # 0.5-0.55 bucket should have 1 item
    assert rep[0]["count"]>=1
    print("calibration buckets PASS", rep[:2])

def test_paper_engine_chain():
    init_db()
    candles=[{"symbol":"BTCUSDT","timeframe":"1h","open":50000+i*10,"high":50000+i*10+20,"low":50000+i*10-10,"close":50000+i*10+5,"volume":100.0,
              "open_time":i*3600000,"close_time":i*3600000+3599999} for i in range(80)]
    pe=PaperEngine(equity=10000)
    res=pe.tick(candles, symbol="BTCUSDT", timeframe="1h")
    assert "decision_id" in res["chain"]
    # update with next candle
    nxt={"high":51000,"low":49000,"close":50500,"close_time":candles[-1]["close_time"]+3600000}
    pe.update_market(nxt)
    st=pe.status()
    assert "equity" in st
    print("paper_engine chain PASS", res["chain"], st)

def test_experiment_registry():
    init_db()
    eid=f"test_{int(time.time())}"
    create_experiment(eid, config={"fee":0.0004}, dataset={"symbol":"BTCUSDT"}, metrics={"pnl":100}, conclusion="test", status="EXPERIMENTAL", versions={"model":"0.2.0"})
    exps=list_experiments()
    assert any(e["id"]==eid for e in exps)
    set_status(eid,"REJECTED")
    exps2=list_experiments()
    assert any(e["id"]==eid and e["status"]=="REJECTED" for e in exps2)
    print("experiment registry PASS")

if __name__=="__main__":
    test_dataset_roundtrip(); test_labels(); test_prob_model(); test_calibration_buckets(); test_paper_engine_chain(); test_experiment_registry()
    print("ALL PHASE2 TESTS PASS")
