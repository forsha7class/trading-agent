"""Metrics — pure numpy, no external dep. ponytail: extend when pandas added."""
from __future__ import annotations
import math, numpy as np
def sharpe(returns:list[float], rf:float=0.0)->float:
    if not returns or len(returns)<2: return 0.0
    a=np.array(returns,float)
    mu=float(np.mean(a)-rf); sd=float(np.std(a,ddof=1))
    return mu/sd*math.sqrt(252) if sd else 0.0
def sortino(returns:list[float], rf:float=0.0)->float:
    if not returns or len(returns)<2: return 0.0
    a=np.array(returns,float)-rf
    downside=a[a<0]
    if len(downside)==0: return float("inf") if np.mean(a)>0 else 0.0
    dd=float(np.std(downside,ddof=1)) if len(downside)>1 else abs(float(np.mean(downside)))
    return float(np.mean(a))/dd*math.sqrt(252) if dd else 0.0
def win_rate(pnls:list[float])->float:
    if not pnls: return 0.0
    return sum(1 for x in pnls if x>0)/len(pnls)
def profit_factor(pnls:list[float])->float:
    wins=sum(x for x in pnls if x>0); losses=abs(sum(x for x in pnls if x<=0))
    return wins/losses if losses else (float("inf") if wins>0 else 0.0)
def expectancy(pnls:list[float])->float:
    return float(np.mean(pnls)) if pnls else 0.0
def max_drawdown(equity:list[float])->float:
    if not equity: return 0.0
    peak=equity[0]; mdd=0.0
    for e in equity:
        peak=max(peak,e)
        mdd=max(mdd,(peak-e)/peak if peak else 0)
    return mdd
def brier_score(probs:list[float], outcomes:list[int])->float:
    if not probs: return float("nan")
    return sum((p-o)**2 for p,o in zip(probs,outcomes))/len(probs)
def log_loss(probs:list[float], outcomes:list[int], eps:float=1e-9)->float:
    if not probs: return float("nan")
    s=0.0
    for p,o in zip(probs,outcomes):
        pp=min(max(p,eps),1-eps)
        s+= -(o*math.log(pp)+(1-o)*math.log(1-pp))
    return s/len(probs)
def avg_r(pnls:list[float], risk_per_trade:float=0.005, equity:float=10000)->float:
    # avg pnl / risk
    if not pnls: return 0.0
    risk=equity*risk_per_trade
    return float(np.mean(pnls))/risk if risk else 0.0
