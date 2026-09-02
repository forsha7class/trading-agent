"""Robustness helpers: param stability, cost sensitivity, drawdown, Monte Carlo."""
from __future__ import annotations
import math, random, numpy as np
from evaluation.strategy_eval import evaluate_strategy
from strategies.trend import TrendStrategy

def param_stability(candles, base_kwargs: dict | None = None, variations: list[dict] | None = None) -> list[dict]:
    base_kwargs = base_kwargs or {}
    if variations is None:
        variations = [
            {"ema_fast":18, "ema_slow":48},
            {"ema_fast":20, "ema_slow":50},
            {"ema_fast":22, "ema_slow":52},
            {"rsi_thresh": 45},
            {"rsi_thresh": 50},
            {"rsi_thresh": 55},
        ]
    out=[]
    for v in variations:
        # TrendStrategy currently has no ctor params; we simulate by patching generate threshold
        # Instead vary strategy-level min strength via fee/slippage proxy is not ideal
        # So we vary evaluate_strategy min_rr/horizon as param sensitivity proxy
        # For true param sensitivity we vary min_rr and horizon
        # Map v to eval kwargs
        cfg={}
        if "ema_fast" in v:
            # ema_fast faster => lower strength threshold
            cfg["min_strength"] = 0.30 if v["ema_fast"]<=18 else (0.35 if v["ema_fast"]==20 else 0.40)
        # use evaluate with adjusted strength by filtering post-hoc; for now just vary horizon/min_rr
        horizon = 20 if v.get("ema_fast",20)==20 else (18 if v.get("ema_fast",20)<20 else 22)
        min_rr = 1.5
        if "rsi_thresh" in v:
            min_rr = 1.3 if v["rsi_thresh"]<50 else (1.5 if v["rsi_thresh"]==50 else 1.7)
        s=TrendStrategy()
        res=evaluate_strategy(candles, s, min_rr=min_rr, horizon=horizon)
        m=res["metrics"]
        out.append({"variation":v, "horizon":horizon, "min_rr":min_rr, "trades":m["trade_count"], "pf":m["profit_factor"], "exp":m["expectancy"], "wr":m["win_rate"], "mdd":m["max_drawdown"]})
    return out

def cost_sensitivity(candles, strategy=None) -> list[dict]:
    from strategies.trend import TrendStrategy
    strat=strategy or TrendStrategy()
    fees=[0.0002,0.0004,0.0006]
    slips=[0.0,0.0005,0.001]
    out=[]
    for f in fees:
        for s in slips:
            res=evaluate_strategy(candles, strat, fee=f, slippage=s)
            m=res["metrics"]
            out.append({"fee":f,"slippage":s,"trades":m["trade_count"],"pf":round(m["profit_factor"],3),"exp":round(m["expectancy"],2),"pnl":round(m["pnl"],2)})
    return out

def drawdown_stats(equity_curve: list[float]) -> dict:
    if not equity_curve: return {}
    peak=equity_curve[0]; mdd=0; mdd_dur=0; cur_dur=0; max_dur=0
    worst=-1e9
    worst5=None; worst10=None
    # drawdown
    for v in equity_curve:
        if v>peak: peak=v; cur_dur=0
        else: cur_dur+=1; max_dur=max(max_dur, cur_dur)
        dd=(peak-v)/peak if peak else 0
        mdd=max(mdd, dd)
    # worst trades not here; caller provides pnls
    return {"max_drawdown":round(mdd,4),"max_drawdown_duration_bars":max_dur}

def monte_carlo(pnls: list[float], n_iter:int=2000, seed:int=42) -> dict:
    if not pnls: return {"error":"no trades"}
    rnd=random.Random(seed)
    # resample order
    finals=[]; maxdds=[]; worst_streaks=[]
    for _ in range(n_iter):
        seq=[pnls[rnd.randrange(len(pnls))] for _ in range(len(pnls))]
        eq=10000; peak=10000; mdd=0; cur_loss=0; max_loss=0
        for x in seq:
            eq+=x
            peak=max(peak,eq)
            mdd=max(mdd,(peak-eq)/peak if peak else 0)
            if x<=0: cur_loss+=1; max_loss=max(max_loss,cur_loss)
            else: cur_loss=0
        finals.append(eq); maxdds.append(mdd); worst_streaks.append(max_loss)
    finals_sorted=sorted(finals); maxdds_sorted=sorted(maxdds)
    def pct(a,p): return a[int(len(a)*p)]
    return {
        "n_iter":n_iter,
        "terminal_p5":round(pct(finals_sorted,0.05),2),"terminal_p50":round(pct(finals_sorted,0.5),2),"terminal_p95":round(pct(finals_sorted,0.95),2),
        "mdd_p50":round(pct(maxdds_sorted,0.5),4),"mdd_p95":round(pct(maxdds_sorted,0.95),4),
        "worst_streak_p95": int(pct(sorted(worst_streaks),0.95)),
    }

def walk_forward_rolling(candles, strategy=None, n_splits:int=4, train_ratio:float=0.5, test_len:int|None=None):
    from evaluation.backtest import walk_forward
    # reuse backtest walk_forward but with more splits
    from strategies.trend import TrendStrategy
    # walk_forward expects splits logic: for now call with splits=n_splits
    return walk_forward(candles, splits=n_splits)
