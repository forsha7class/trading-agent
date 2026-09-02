"""Calibration helpers."""
from __future__ import annotations
import math
def reliability_bins(probs:list[float], outcomes:list[int], n_bins:int=5)->list[dict]:
    if not probs: return []
    out=[]
    for b in range(n_bins):
        lo=b/n_bins; hi=(b+1)/n_bins
        idx=[i for i,p in enumerate(probs) if lo<=p<hi or (b==n_bins-1 and p==1.0)]
        if not idx: out.append({"bin":b,"count":0,"avg_prob":0,"freq":0}); continue
        ap=sum(probs[i] for i in idx)/len(idx)
        fr=sum(outcomes[i] for i in idx)/len(idx)
        out.append({"bin":b,"count":len(idx),"avg_prob":round(ap,3),"freq":round(fr,3)})
    return out
