"""Ensemble — regime-aware bounded weighting. ponytail: fixed cap 0.4 + regime map; upgrade to learned weights."""
from __future__ import annotations
from dataclasses import dataclass, field

REGIME_WEIGHTS={
    "TREND_BULL":{"trend":0.35,"momentum":0.30,"breakout":0.25,"mean_reversion":0.10},
    "TREND_BEAR":{"trend":0.35,"momentum":0.30,"breakout":0.25,"mean_reversion":0.10},
    "RANGE":{"trend":0.15,"momentum":0.15,"breakout":0.20,"mean_reversion":0.50},
    "HIGH_VOL":{"trend":0.20,"momentum":0.15,"breakout":0.15,"mean_reversion":0.20},
    "HIGH_VOLATILITY":{"trend":0.20,"momentum":0.15,"breakout":0.15,"mean_reversion":0.20},
    "LOW_VOL":{"trend":0.30,"momentum":0.25,"breakout":0.30,"mean_reversion":0.15},
    "LOW_VOLATILITY":{"trend":0.30,"momentum":0.25,"breakout":0.30,"mean_reversion":0.15},
    "UNCERTAIN":{"trend":0.25,"momentum":0.25,"breakout":0.25,"mean_reversion":0.25},
}
CAP=0.4
def _w_for(regime:str): return REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS["UNCERTAIN"])
def _get(obj, key, default=None):
    if isinstance(obj, dict): return obj.get(key, default)
    return getattr(obj, key, default)
def _cap_norm(w:dict)->dict:
    tot=sum(w.values()) or 1
    w={k:v/tot for k,v in w.items()}
    for _ in range(6):
        over={k:v for k,v in w.items() if v>CAP}
        if not over: break
        excess=sum(v-CAP for v in over.values())
        for k in over: w[k]=CAP
        under=[k for k in w if k not in over]
        if not under: break
        us=sum(w[k] for k in under) or 1
        for k in under: w[k]+=excess*(w[k]/us)
        tot=sum(w.values()) or 1
        w={k:v/tot for k,v in w.items()}
    # final clamp + renorm
    w={k:min(CAP,v) for k,v in w.items()}
    tot=sum(w.values()) or 1
    w={k:v/tot for k,v in w.items()}
    # if still over due to rounding, force
    for k in w:
        if w[k]>CAP+1e-9: w[k]=CAP
    return w

@dataclass
class CombinedSignal:
    direction: str
    score: float
    supporting: list = field(default_factory=list)
    contradicting: list = field(default_factory=list)
    weights: dict = field(default_factory=dict)
    breakdown: dict = field(default_factory=dict)
    def __getitem__(self, k): return getattr(self, k)
    def get(self, k, d=None): return getattr(self, k, d)
    def __contains__(self, k): return hasattr(self, k)

def aggregate(signals:list, regime=None, weights:dict|None=None)->CombinedSignal:
    if not signals: return CombinedSignal("NEUTRAL",0,[],[],{}, {})
    reg=str(_get(regime,"regime", regime) or "UNCERTAIN")
    if isinstance(regime, dict): reg=str(regime.get("regime","UNCERTAIN"))
    base=dict(_w_for(reg))
    if weights:
        for k,v in weights.items(): base[k]=float(v)
    norm=_cap_norm(base)
    long_s=short_s=0
    breakdown={}
    for s in signals:
        strat=str(_get(s,"strategy","") or "unknown")
        w=norm.get(strat, 0)
        if w==0: w=0.15  # fallback small
        st=float(_get(s,"strength",0) or 0); st=max(0,min(1,st))
        d=str(_get(s,"direction","NEUTRAL") or "NEUTRAL").upper()
        if d=="LONG": long_s+=st*w
        elif d=="SHORT": short_s+=st*w
        breakdown[strat]={"direction":d,"strength":st,"weight":round(float(norm.get(strat,0)),3)}
    total=long_s+short_s
    if total==0: return CombinedSignal("NEUTRAL",0,[],[],norm,breakdown)
    direction="LONG" if long_s>short_s else "SHORT"
    winner=max(long_s,short_s); loser=min(long_s,short_s)
    edge=(winner-loser)/total if total else 0
    score=int(round((winner/total)*70 + edge*30))
    supporting=[str(_get(s,"strategy","?")) for s in signals if str(_get(s,"direction","")).upper()==direction]
    contradicting=[str(_get(s,"strategy","?")) for s in signals if str(_get(s,"direction","")).upper() not in (direction,"NEUTRAL")]
    if score<35 or edge<0.2: return CombinedSignal("NEUTRAL",score,supporting,contradicting,norm,breakdown)
    return CombinedSignal(direction,score,supporting,contradicting,norm,breakdown)
