"""Extended calibration — buckets, reliability."""
from __future__ import annotations
import math

def bucket_report(probs:list[float], labels:list[str], target:str="up", buckets:list[tuple]|None=None)->list[dict]:
    if buckets is None:
        buckets=[(0.5,0.55),(0.55,0.6),(0.6,0.65),(0.65,0.7),(0.7,0.8),(0.8,1.0)]
    out=[]
    for lo,hi in buckets:
        idx=[i for i,p in enumerate(probs) if lo <= p < hi or (hi==1.0 and p>=hi)]
        if not idx: out.append({"bucket":f"{lo:.2f}-{hi:.2f}","count":0,"avg_prob":0,"freq":0,"gap":0}); continue
        ap=sum(probs[i] for i in idx)/len(idx)
        freq=sum(1 for i in idx if labels[i]==target)/len(idx)
        out.append({"bucket":f"{lo:.2f}-{hi:.2f}","count":len(idx),"avg_prob":round(ap,3),"freq":round(freq,3),"gap":round(abs(ap-freq),3)})
    return out

def calibration_metrics(probs:list[dict], labels:list[str])->dict:
    # probs: list of {p_up,p_down,p_flat}
    from evaluation.metrics import max_drawdown  # ensure import side-effect
    import math
    n=len(probs)
    if n==0: return {}
    # Brier per class
    def brier(target):
        key={"up":"p_up","down":"p_down","flat":"p_flat"}[target]
        return sum((p[key] - (1 if lab==target else 0))**2 for p,lab in zip(probs, labels))/n
    def logloss(target):
        key={"up":"p_up","down":"p_down","flat":"p_flat"}[target]
        s=0.0
        for p,lab in zip(probs, labels):
            pr=max(1e-9,min(1-1e-9,p[key]))
            if lab==target: s+= -math.log(pr)
            else: s+= -math.log(1-pr)
        return s/n
    return {"brier_up":round(brier("up"),4),"brier_down":round(brier("down"),4),"brier_flat":round(brier("flat"),4),"logloss_up":round(logloss("up"),4)}
