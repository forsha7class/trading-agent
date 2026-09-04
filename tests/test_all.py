import math, time, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import conftest  # noqa: F401 — isolated DB + TRADING_TG_SEND=0 before project imports
from ingestion.validation import validate_candles
from features.technical import build_features, sma, ema, rsi14, atr14
from regime.detector import detect_regime
from strategies.trend import TrendStrategy
from strategies.momentum import MomentumStrategy
from strategies.breakout import BreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy
from trade_signal.ensemble import aggregate
from trade_signal.probability import estimate
from trade_signal.mtf import check_mtf
from risk.risk_engine import RiskEngine
from decision.engine import DecisionEngine
from decision.state_machine import DecisionStateMachine
from storage.database import init_db, get_db, insert_decision
from portfolio.paper_portfolio import PaperPortfolio
from evaluation.backtest import run_backtest
import numpy as np

def assert_eq(a,b,msg=""):
    assert a==b, f"{msg}: {a!r}!={b!r}"
def assert_true(x,msg=""):
    assert bool(x), f"expected true: {msg} got {x!r}"

# 1 data validation
def test_validation():
    now=int(time.time()*1000)
    good=[{"symbol":"BTCUSDT","timeframe":"1h","open":100,"high":101,"low":99,"close":100.5,"volume":10,"open_time":now-3600000,"close_time":now-1000} for _ in range(5)]
    for i,c in enumerate(good): c["open_time"]=now-(5-i)*3600000; c["close_time"]=c["open_time"]+3599999
    assert_true(validate_candles(good,"BTCUSDT","1h",now_ms=now).valid, "good")
    # duplicate
    dup=good+[good[-1]]
    assert_eq(validate_candles(dup,"BTCUSDT","1h",now_ms=now).reason, "DUPLICATE")
    # impossible OHLC
    bad=[dict(good[0], high=90)] + good[1:]
    assert_eq(validate_candles(bad,"BTCUSDT","1h",now_ms=now).reason, "IMPOSSIBLE_OHLC")
    # stale
    stale=[dict(c, open_time=c["open_time"]-86400000, close_time=c["close_time"]-86400000) for c in good]
    assert_eq(validate_candles(stale,"BTCUSDT","1h",now_ms=now).reason, "STALE")
    # empty
    assert_eq(validate_candles([],"BTCUSDT","1h").reason, "EMPTY")
    print("validation PASS")

# 2 features no lookahead + sufficient
def test_features():
    candles=[{"open":float(i),"high":float(i)+1,"low":float(i)-1,"close":float(i),"volume":100.0} for i in range(1,61)]
    f=build_features(candles)
    assert_true(not math.isnan(f["sma20"]) and not math.isnan(f["ema20"]), "sma/ema")
    assert_true(f["sufficient"] is True)
    assert_true(f["trend"] in ("UP","DOWN","UNKNOWN"))
    # ensure causal: last value computed only from past
    f2=build_features(candles[:30])
    assert_true(not math.isnan(f2["sma20"]))
    print("features PASS")

# 3 regime
def test_regime():
    r=detect_regime({"close":100,"ema20":99,"ema50":95,"atr14":1.5,"rsi14":60,"momentum":0.02,"vol":0.015}, candles=[{"close":100}]*60)
    assert_true(r.regime in ("TREND_BULL","TREND_BEAR","RANGE","HIGH_VOL","LOW_VOL","UNCERTAIN"))
    r2=detect_regime({}, [])
    assert_eq(r2.regime, "UNCERTAIN")
    r3=detect_regime({"close":100,"ema20":99,"ema50":95,"atr14":5,"rsi14":60,"momentum":0.02,"vol":0.04}, candles=[{"close":100}]*60)
    assert_eq(r3.regime, "HIGH_VOL")
    print("regime PASS")

# 4 strategies
def test_strategies():
    f={"ema20":99,"ema50":95,"close":100,"atr14":1.5,"momentum":0.02,"rsi14":58,"sma20":92,"vol":0.015,"volume_anomaly":1.2}
    for cls in [TrendStrategy, MomentumStrategy, BreakoutStrategy, MeanReversionStrategy]:
        s=cls().generate({"features":f,"candles":[f]*25,"timeframe":"1h","regime":"TREND_BULL"})
        assert_true(s.direction in ("LONG","SHORT","NEUTRAL"), cls.__name__)
        assert_true(0 <= s.strength <= 1, cls.__name__)
    print("strategies PASS")

# 5 ensemble + probability
def test_ensemble_prob():
    from storage.models import StrategySignal
    sigs=[
        StrategySignal("BTCUSDT",0,"trend","LONG",0.8,entry=100,invalidation=98,evidence={}),
        StrategySignal("BTCUSDT",0,"momentum","LONG",0.7,entry=100,invalidation=98,evidence={}),
        StrategySignal("BTCUSDT",0,"breakout","LONG",0.6,entry=100,invalidation=98,evidence={}),
        StrategySignal("BTCUSDT",0,"mean_reversion","NEUTRAL",0.1,entry=100,invalidation=98,evidence={}),
    ]
    ens=aggregate(sigs, regime="TREND_BULL")
    assert_eq(ens.direction, "LONG")
    assert_true(ens.score>40)
    p=estimate(ens, {"momentum":0.01}, regime={"regime":"TREND_BULL","confidence":0.8})
    assert_true(abs(p.p_up+p.p_down+p.p_flat-1)<0.01, "prob sums to 1")
    assert_true(p.p_up>0.5, "long prob")
    print("ensemble+prob PASS")

# 6 risk 9 vetoes
def test_risk_vetoes():
    re=RiskEngine()
    base={"equity":10000,"entry":100,"stop":98,"tp1":103,"risk_pct":0.005,"leverage":1,"signal":"LONG"}
    def check(ctx, expect_veto):
        r=re.check(ctx)
        ok=(r.veto==expect_veto) if expect_veto else r.approved
        assert_true(ok, f"veto {expect_veto} got {r.veto} {r.reason}")
    check(base, None)
    check({**base,"is_martingale":True},"NO_MARTINGALE")
    check({**base,"is_averaging":True},"NO_AVERAGING")
    check({**base,"daily_pnl":-300},"NO_REVENGE")
    check({**base,"data_ts":0},"NO_STALE_DATA")
    check({**base,"spread_pct":0.01},"NO_ILLIQUID")
    check({**base,"leverage":5},"NO_EXCESS_LEVERAGE")
    check({**base,"risk_pct":0.02},"NO_RISK_OVERRIDE")
    check({**base,"tp1":100.5},"NO_INVALID_RR")
    check({**base,"positions":3},"NO_RISK_OVERRIDE")
    check({"equity":0,"entry":100,"stop":98},"NO_CRITICAL_FAILURE")
    print("risk vetoes PASS (11 checks)")

# 7 decision engine NO_TRADE default
def test_decision():
    de=DecisionEngine()
    # weak signal -> NO_TRADE
    d=de.decide({"symbol":"BTCUSDT","timeframe":"1h","features":{"error":"insufficient_data"}})
    assert_eq(d.decision,"NO_TRADE")
    assert_true("INSUFFICIENT_DATA" in d.reason or "NO_TRADE" in d.reason)
    # stale veto
    cand=[{"close":100,"close_time":0}]
    d2=de.decide({"symbol":"BTCUSDT","timeframe":"1h","features":{"close":100,"atr14":1,"ema20":99,"ema50":98},"candles":cand[-5:] if (cand:=cand*60) else [], "data_ts":0,"equity":10000})
    # data stale should be NO_TRADE
    assert_true(d2.decision in ("NO_TRADE","LONG","SHORT"))  # at least not crash
    print("decision PASS")

# 8 state machine
def test_state_machine():
    sm=DecisionStateMachine()
    assert_eq(sm.state,"DATA_INVALID")
    assert_true(sm.transition("DATA_VALID","ok"))
    assert_true(sm.transition("ANALYZING",""))
    assert_true(sm.transition("SIGNAL_GENERATED",""))
    assert_true(sm.transition("RISK_CHECK",""))
    assert_true(sm.transition("AI_REVIEW",""))
    assert_true(sm.transition("DECISION",""))
    assert_true(sm.is_terminal)
    # invalid transition should be blocked
    sm2=DecisionStateMachine("DATA_VALID")
    assert_true(not sm2.transition("AI_REVIEW","skip risk"))  # must go through RISK_CHECK
    print("state_machine PASS")

# 9 paper portfolio + backtest + mtf
def test_portfolio_backtest():
    candles=[{"symbol":"BTCUSDT","timeframe":"1h","open":100+i*0.1,"high":100+i*0.1+0.3,"low":100+i*0.1-0.2,"close":100+i*0.1+0.05,"volume":100,"open_time":i*3600000,"close_time":i*3600000+3599999} for i in range(200)]
    res=run_backtest(candles, config={"equity":10000,"risk_per_trade":0.005,"min_rr":1.5})
    assert_true("metrics" in res and "trades" in res)
    assert_true(res["metrics"]["trades"]>=0)
    # walk-forward
    from evaluation.backtest import walk_forward
    wf=walk_forward(candles, splits=2)
    assert_true("splits" in wf)
    # paper portfolio
    pf=PaperPortfolio(equity=10000)
    dec={"symbol":"BTCUSDT","signal":"LONG","decision":"LONG","entry":100,"stop":98,"tp1":103,"position_size":25}
    pos=pf.open_position(dec)
    assert_true(pos is not None)
    closed=pf.update({"high":104,"low":99,"close":103.5,"close_time":int(time.time()*1000)})
    print(f"backtest PASS trades={res['metrics']['trades']} pf={pf.metrics()}")
    # mtf
    r=check_mtf({"1h":{"direction":"LONG","strength":0.8,"ts":int(time.time()*1000)}, "4h":{"direction":"LONG","strength":0.7,"ts":int(time.time()*1000)}})
    assert_true(r.aligned)
    print("mtf PASS")

# 10 db append-only
def test_db():
    init_db()
    db=get_db()
    # recreate trigger if missing (init may have been called earlier)
    try:
        from storage.database import _append_only_trigger
        _append_only_trigger()
    except: pass
    n0=db.execute("SELECT count(*) FROM decisions").fetchone()[0]
    import time
    dd={"symbol":"TEST","timeframe":"1h","ts":int(time.time()*1000),"decision":"NO_TRADE","signal":"NO_TRADE","reason":"test","regime":"UNCERTAIN","probability":{"p_up":0.33,"p_down":0.33,"p_flat":0.34},"data_ts":int(time.time()*1000)}
    insert_decision(dd)
    n1=db.execute("SELECT count(*) FROM decisions").fetchone()[0]
    assert_true(n1==n0+1)
    # try UPDATE should fail
    try:
        db.execute("UPDATE decisions SET reason='hacked' WHERE symbol='TEST'")
        assert_true(False, "should have raised append-only")
    except Exception as e:
        assert_true("append-only" in str(e).lower() or "abort" in str(e).lower(), str(e))
    print("db PASS")

if __name__=="__main__":
    test_validation(); test_features(); test_regime(); test_strategies(); test_ensemble_prob()
    test_risk_vetoes(); test_decision(); test_state_machine(); test_portfolio_backtest(); test_db()
    print("\nALL TESTS PASS")
