"""Probability threshold analysis."""
from __future__ import annotations
import math
from evaluation.labels import make_labels
from evaluation.prob_model import build_feature_matrix, train_prob_model

def threshold_report(candles, thresholds=(0.5,0.55,0.6,0.65,0.7,0.75), horizon=4, threshold=0.005, fee=0.0004, slippage=0.0005):
    n=len(candles)
    split=int(n*0.7)
    train=candles[:split]; test=candles[split:]
    m=train_prob_model(train, horizon=horizon)
    from evaluation.prob_model import build_feature_matrix
    X,_=build_feature_matrix(test)
    labs=__import__("evaluation.labels", fromlist=["make_labels"]).make_labels(test, horizon=horizon, threshold=threshold)
    labs_aligned=[l["label"] for l in labs[-len(X):]] if len(X) else []
    preds=m.predict(X) if len(X) else []
    out=[]
    for th in thresholds:
        # trade when p_up >= th -> LONG, p_down>=th -> SHORT
        pnls=[]; wins=0; trades=0
        for p,lab in zip(preds, labs_aligned):
            side=None
            if p["p_up"]>=th: side="up"
            elif p["p_down"]>=th: side="down"
            else: continue
            trades+=1
            if lab==side: wins+=1; pnls.append(1)
            elif lab=="flat": pnls.append(0)
            else: pnls.append(-1)
        wr=wins/trades if trades else 0
        prec=wr
        exp=sum(pnls)/len(pnls) if pnls else 0
        out.append({"threshold":th,"trades":trades,"precision":round(prec,3),"expectancy":round(exp,3),"wr":round(wr,3)})
    return out
