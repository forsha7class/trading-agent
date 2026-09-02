"""Probability estimator — heuristic calibrated. Score != probability: score is weighted vote strength 0-100; probability is calibrated uncertainty estimate.
ponytail: logistic map fixed; upgrade to Platt/isotonic when labeled outcomes available."""
from dataclasses import dataclass
import math

PROB_VERSION = "0.1.0"

@dataclass
class ProbDist:
    p_up: float
    p_down: float
    p_flat: float
    version: str = PROB_VERSION
    def as_tuple(self): return (self.p_up, self.p_down, self.p_flat)

def _clip01(x): return max(0.0, min(1.0, float(x)))
def _norm(a,b,c):
    s=a+b+c
    if s==0: return (1/3,1/3,1/3)
    return (a/s,b/s,c/s)

def estimate(combined_signal, features=None, regime=None) -> ProbDist:
    """combined_signal: CombinedSignal or dict with direction/score. features/regime optional for confidence adjust."""
    direction = getattr(combined_signal, "direction", None) or (combined_signal.get("direction") if isinstance(combined_signal, dict) else "NEUTRAL")
    score = getattr(combined_signal, "score", None)
    if score is None and isinstance(combined_signal, dict): score = combined_signal.get("score", 0)
    score = float(score or 0)
    score = max(0, min(100, score))
    s = score/100  # 0-1
    # regime confidence dampens extremes when uncertain
    conf = 0.6
    if regime is not None:
        c = getattr(regime, "confidence", None)
        if c is None and isinstance(regime, dict): c = regime.get("confidence")
        if c is not None:
            try: conf = max(0.1, min(1.0, float(c)))
            except Exception: pass
        # regime type adjusts flat prior
        r = getattr(regime, "regime", None) or (regime.get("regime") if isinstance(regime, dict) else None)
        if r in ("HIGH_VOL", "UNCERTAIN"): conf *= 0.85
    # logistic-ish mapping: p_dir = 0.33 + 0.42 * s * (0.7+0.3*conf)
    boost = 0.7 + 0.3*conf
    if direction == "LONG":
        p_up = 0.33 + 0.42 * s * boost
        p_up = min(0.78, max(0.34, p_up))
        p_flat = 0.32 * (1 - 0.5*s) * (0.9 + 0.1*(1-conf))  # slight increase when low conf
        p_flat = max(0.12, min(0.38, p_flat))
        p_down = 1 - p_up - p_flat
        p_down = max(0.05, p_down)
        p_up, p_down, p_flat = _norm(p_up, p_down, p_flat)
    elif direction == "SHORT":
        p_down = 0.33 + 0.42 * s * boost
        p_down = min(0.78, max(0.34, p_down))
        p_flat = 0.32 * (1 - 0.5*s) * (0.9 + 0.1*(1-conf))
        p_flat = max(0.12, min(0.38, p_flat))
        p_up = 1 - p_down - p_flat
        p_up = max(0.05, p_up)
        p_up, p_down, p_flat = _norm(p_up, p_down, p_flat)
    else:
        p_flat = 0.42 + 0.18 * (1 - s) * boost  # 0.42..0.60
        p_flat = max(0.38, min(0.68, p_flat))
        rem = 1 - p_flat
        # slight bias if score leans (score>30 but direction NEUTRAL means conflict)
        p_up = rem * 0.5
        p_down = rem * 0.5
    # final round to 4dp then renormalize
    p_up, p_down, p_flat = [round(x,4) for x in (p_up, p_down, p_flat)]
    # fix rounding drift
    tot = p_up + p_down + p_flat
    if abs(tot-1.0) > 1e-9:
        # adjust largest
        m = max((p_up,"up"),(p_down,"down"),(p_flat,"flat"))[1]
        if m=="up": p_up += 1.0 - tot
        elif m=="down": p_down += 1.0 - tot
        else: p_flat += 1.0 - tot
    return ProbDist(round(p_up,4), round(p_down,4), round(p_flat,4), PROB_VERSION)

def brier_score(probs: list, outcomes: list) -> float:
    """probs: list of ProbDist|tuple|dict, outcomes: list of 'up'|'down'|'flat' or 0/1/2. Mean Brier (3-class)."""
    if not probs or not outcomes or len(probs)!=len(outcomes): return float("nan")
    n=len(probs); s=0.0
    for p,o in zip(probs, outcomes):
        if isinstance(p, ProbDist): pu,pd,pf = p.p_up,p.p_down,p.p_flat
        elif isinstance(p, dict): pu,pd,pf = p.get("p_up",0),p.get("p_down",0),p.get("p_flat",0)
        elif isinstance(p,(list,tuple)) and len(p)==3: pu,pd,pf = p
        else: continue
        if isinstance(o, str): o=o.lower()
        if o in ("up",0,"0","long"): t=(1,0,0)
        elif o in ("down",1,"1","short"): t=(0,1,0)
        elif o in ("flat",2,"2","neutral"): t=(0,0,1)
        else: continue
        s += (pu-t[0])**2 + (pd-t[1])**2 + (pf-t[2])**2
    return round(s/(3*n) if n else float("nan"), 6)

def log_loss(probs: list, outcomes: list, eps: float = 1e-15) -> float:
    """Multiclass log loss. Clips probs to eps."""
    if not probs or not outcomes or len(probs)!=len(outcomes): return float("nan")
    n=len(probs); s=0.0
    for p,o in zip(probs, outcomes):
        if isinstance(p, ProbDist): pu,pd,pf = p.p_up,p.p_down,p.p_flat
        elif isinstance(p, dict): pu,pd,pf = p.get("p_up",0),p.get("p_down",0),p.get("p_flat",0)
        elif isinstance(p,(list,tuple)) and len(p)==3: pu,pd,pf = p
        else: continue
        pu=max(eps,min(1-eps,pu)); pd=max(eps,min(1-eps,pd)); pf=max(eps,min(1-eps,pf))
        # renormalize after clip
        tot=pu+pd+pf; pu/=tot; pd/=tot; pf/=tot
        if isinstance(o,str): o=o.lower()
        if o in ("up",0,"0","long"): s += -math.log(pu)
        elif o in ("down",1,"1","short"): s += -math.log(pd)
        elif o in ("flat",2,"2","neutral"): s += -math.log(pf)
    return round(s/n if n else float("nan"), 6)
