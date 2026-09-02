"""Baseline comparison — BuyHold, simple technical, naive random."""
from __future__ import annotations
import math, random
from features.technical import build_features
from evaluation.backtest import run_backtest

def buy_hold(candles:list[dict])->dict:
    if not candles: return {}
    ret=candles[-1]["close"]/candles[0]["close"]-1
    # mdd
    peak=candles[0]["close"]; mdd=0
    for c in candles:
        peak=max(peak,c["close"]); mdd=max(mdd,(peak-c["close"])/peak if peak else 0)
    return {"return_pct":round(ret*100,2),"max_drawdown":round(mdd,4),"trades":1}

def sma_baseline(candles:list[dict], fee=0.0004, slippage=0.0005)->dict:
    def fn(ctx):
        f=ctx["features"]
        close=float(f.get("close_last", f.get("close",0)))
        sma20=float(f.get("sma20",0) or 0)
        if math.isnan(sma20): return type("S",(),{"direction":"NEUTRAL"})()
        d="LONG" if close>sma20 else "SHORT" if close<sma20 else "NEUTRAL"
        return type("S",(),{"direction":d})()
    return run_backtest(candles, strategy_fn=fn, config={"fee":fee,"slippage":slippage})["metrics"]

def naive_random(candles:list[dict], seed=42, fee=0.0004, slippage=0.0005)->dict:
    rng=random.Random(seed)
    def fn(ctx): return type("S",(),{"direction":rng.choice(["LONG","SHORT","NEUTRAL"])})()
    return run_backtest(candles, strategy_fn=fn, config={"fee":fee,"slippage":slippage})["metrics"]

def compare(candles:list[dict])->dict:
    agent=run_backtest(candles)["metrics"]
    return {"buy_hold":buy_hold(candles),"sma20":sma_baseline(candles),"naive_random":naive_random(candles),"agent":agent}
