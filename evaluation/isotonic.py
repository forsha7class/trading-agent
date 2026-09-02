"""Isotonic regression (PAVA) for probability calibration — numpy only."""
from __future__ import annotations
import math, numpy as np

def isotonic_fit(probs: list[float], labels: list[int]):
    """Fit isotonic regression: sorted probs -> calibrated values. Returns (xs, ys) mapping."""
    if not probs:
        return [], []
    # sort by prob
    pairs = sorted(zip(probs, labels), key=lambda x: x[0])
    xs = [p for p,_ in pairs]
    ys = [float(l) for _,l in pairs]
    # PAVA pools
    pools = [[ys[i], 1, xs[i]] for i in range(len(ys))]  # [sum, count, x_rep]
    # Actually need block averages
    # Use standard PAVA
    blocks = [{"sum": float(ys[i]), "cnt": 1, "vals": [ys[i]], "xs": [xs[i]]} for i in range(len(ys))]
    # iterative merge violating monotonicity
    merged = True
    while merged and len(blocks) > 1:
        merged = False
        i = 0
        while i < len(blocks)-1:
            a = blocks[i]["sum"]/blocks[i]["cnt"]
            b = blocks[i+1]["sum"]/blocks[i+1]["cnt"]
            if a > b + 1e-9:
                # merge
                nb = {"sum": blocks[i]["sum"]+blocks[i+1]["sum"], "cnt": blocks[i]["cnt"]+blocks[i+1]["cnt"], "vals": blocks[i]["vals"]+blocks[i+1]["vals"], "xs": blocks[i]["xs"]+blocks[i+1]["xs"]}
                blocks[i] = nb
                del blocks[i+1]
                merged = True
                if i > 0:
                    i -= 1
            else:
                i += 1
    # build stepwise mapping
    out_x=[]; out_y=[]
    for b in blocks:
        avg = b["sum"]/b["cnt"]
        for x in b["xs"]:
            out_x.append(x); out_y.append(avg)
    # sort already
    return out_x, out_y

def isotonic_predict(probs: list[float], fit_x: list[float], fit_y: list[float]) -> list[float]:
    if not fit_x:
        return probs
    import bisect
    # fit_x sorted
    res=[]
    for p in probs:
        # nearest: find interval
        idx = bisect.bisect_left(fit_x, p)
        if idx >= len(fit_y): idx = len(fit_y)-1
        if idx < 0: idx = 0
        # average of neighbors for smoother
        res.append(float(fit_y[idx]))
    return res

def brier(probs: list[float], labels: list[int]) -> float:
    if not probs: return 0
    return sum((p - l)**2 for p,l in zip(probs, labels))/len(probs)

def logloss(probs: list[float], labels: list[int]) -> float:
    s=0
    for p,l in zip(probs, labels):
        pr=max(1e-9, min(1-1e-9, p))
        s+= -math.log(pr) if l==1 else -math.log(1-pr)
    return s/len(probs) if probs else 0
