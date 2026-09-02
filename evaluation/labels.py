"""Signal labeling — horizon-specific, no lookahead ambiguity."""
from __future__ import annotations
import math

def make_labels(candles:list[dict], horizon:int=4, threshold:float=0.005, flat_threshold:float|None=None)->list[dict]:
    """Horizon-specific labels. At time T (index i), use future return over N candles.
    flat if abs(ret) < threshold, up if ret > threshold, down if ret < -threshold.
    Returns list aligned to candles (last `horizon` entries have label None — no future).
    Also computes stop/target outcome if needed externally."""
    flat_threshold = flat_threshold if flat_threshold is not None else threshold
    out=[]
    n=len(candles)
    closes=[float(c["close"]) for c in candles]
    for i in range(n):
        if i + horizon >= n:
            out.append({"index":i,"ts":candles[i].get("close_time", candles[i].get("open_time")), "ret":None, "label":None, "horizon":horizon})
            continue
        entry=closes[i]
        future=closes[i+horizon]
        ret=(future/entry - 1) if entry else 0
        if ret > flat_threshold: label="up"
        elif ret < -flat_threshold: label="down"
        else: label="flat"
        out.append({"index":i,"ts":candles[i].get("close_time"),"ret":ret,"label":label,"horizon":horizon})
    return out

def make_r_labels(candles:list[dict], horizon:int=20, entry_atr_mult:float=1.8, rr:float=1.5, fee:float=0.0004, slippage:float=0.0005)->list[dict]:
    """R-based label: simulate entry at close[i], stop=close[i]±atr*mult, tp=entry±dist*rr, look ahead horizon bars.
    Returns up/down/flat analogue: up=TP hit before SL for LONG setup etc. Here we return hit."""
    from features.technical import build_features
    n=len(candles)
    out=[]
    # precompute ATR per i causally
    for i in range(n):
        if i < 50 or i + 1 >= n:
            out.append({"index":i,"hit":None,"label":None})
            continue
        window=candles[:i+1]
        f=build_features(window)
        atr=float(f.get("atr14", 0) or 0)
        if math.isnan(atr) or atr==0: atr=float(candles[i]["close"])*0.015
        entry=float(candles[i]["close"])
        # we produce both LONG and SHORT outcomes
        long_stop=entry- entry*0.0 - atr*entry_atr_mult if False else entry - atr*1.8  # keep consistent
        long_stop=entry - atr*1.8
        long_tp=entry + abs(entry-long_stop)*rr
        short_stop=entry + atr*1.8
        short_tp=entry - abs(short_stop-entry)*rr
        # find first hit within horizon
        long_hit=None; short_hit=None
        for j in range(i+1, min(n, i+1+horizon)):
            hi=float(candles[j]["high"]); lo=float(candles[j]["low"])
            if long_hit is None:
                if lo <= long_stop: long_hit="SL"
                elif hi >= long_tp: long_hit="TP"
            if short_hit is None:
                if hi >= short_stop: short_hit="SL"
                elif lo <= short_tp: short_hit="TP"
            if long_hit and short_hit: break
        out.append({"index":i,"long_hit":long_hit,"short_hit":short_hit,"label":long_hit or short_hit})
    return out
