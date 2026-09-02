"""First statistically testable probability layer — logistic regression from numpy (no sklearn).
P(up)/P(down)/P(flat) via one-vs-rest or softmax. Ponytail: replace with sklearn/GBM when available."""
from __future__ import annotations
import math, numpy as np

def _sigmoid(z): return 1/(1+np.exp(-np.clip(z, -30, 30)))

class LogisticRegression:
    def __init__(self, lr:float=0.05, iters:int=600, l2:float=1e-4):
        self.lr=lr; self.iters=iters; self.l2=l2
        self.w=None; self.b=0.0
    def fit(self, X:np.ndarray, y:np.ndarray):
        n,d=X.shape
        self.w=np.zeros(d); self.b=0.0
        for _ in range(self.iters):
            z=X.dot(self.w)+self.b
            p=_sigmoid(z)
            err=p - y
            gw=(X.T.dot(err))/n + self.l2*self.w
            gb=float(np.mean(err))
            self.w -= self.lr*gw
            self.b -= self.lr*gb
        return self
    def predict_proba(self, X:np.ndarray)->np.ndarray:
        z=X.dot(self.w)+self.b
        p=_sigmoid(z)
        return np.vstack([1-p, p]).T  # [not, is]

class ProbModel:
    """3-class via 3 one-vs-rest logistics, renormalized."""
    VERSION="0.2.0"
    def __init__(self):
        self.m_up=LogisticRegression()
        self.m_down=LogisticRegression()
        self.fitted=False
        self.feature_names=[]
    def fit(self, X:np.ndarray, labels:list[str], feature_names:list[str]|None=None):
        self.feature_names=feature_names or []
        y_up=np.array([1 if l=="up" else 0 for l in labels], dtype=float)
        y_down=np.array([1 if l=="down" else 0 for l in labels], dtype=float)
        # handle degenerate (all 0)
        if y_up.sum()==0: y_up=np.zeros_like(y_up)
        if y_down.sum()==0: y_down=np.zeros_like(y_down)
        if y_up.sum()>0 and y_up.sum()<len(y_up): self.m_up.fit(X, y_up)
        if y_down.sum()>0 and y_down.sum()<len(y_down): self.m_down.fit(X, y_down)
        self.fitted=True
        return self
    def predict(self, X:np.ndarray)->list[dict]:
        if not self.fitted: return [{"p_up":0.33,"p_down":0.33,"p_flat":0.34} for _ in range(len(X))]
        pu=self.m_up.predict_proba(X)[:,1] if hasattr(self.m_up,'w') and self.m_up.w is not None else np.full(len(X),0.33)
        pd=self.m_down.predict_proba(X)[:,1] if hasattr(self.m_down,'w') and self.m_down.w is not None else np.full(len(X),0.33)
        out=[]
        for i in range(len(X)):
            a=float(np.clip(pu[i],0.05,0.85)); b=float(np.clip(pd[i],0.05,0.85))
            # flat is remainder, ensure sum 1
            # normalize: if both high, scale
            s=a+b
            if s>0.85: a*=0.85/s; b*=0.85/s
            c=1-a-b
            c=max(0.05,c)
            s2=a+b+c; a/=s2; b/=s2; c/=s2
            out.append({"p_up":round(a,4),"p_down":round(b,4),"p_flat":round(c,4)})
        return out

def build_feature_matrix(candles:list[dict])->tuple[np.ndarray, list[str]]:
    from features.technical import build_features
    feats=[]
    for i in range(50, len(candles)):
        f=build_features(candles[:i+1])
        if f.get("error"): continue
        row=[
            float(f.get("rsi14",50) or 50)/100,
            float(f.get("atr_pct",0.015) or 0.015)*100,
            float(f.get("momentum",0) or 0)*10,
            float(f.get("vol",0.01) or 0.01)*100,
            (1 if f.get("trend")=="UP" else -1 if f.get("trend")=="DOWN" else 0),
            float(f.get("volume_anomaly",1) or 1) - 1,
        ]
        # add EMA spread
        close=float(f.get("close_last", candles[i]["close"]))
        ema20=float(f.get("ema20", close) or close)
        ema50=float(f.get("ema50", close) or close)
        row.append((ema20-ema50)/close*100 if close else 0)
        feats.append(row)
    names=["rsi","atr_pct","momentum","vol","trend","vol_anom","ema_spread"]
    return np.array(feats, dtype=float), names

def train_prob_model(candles:list[dict], horizon:int=4, threshold:float=0.005)->ProbModel:
    from evaluation.labels import make_labels
    X, names=build_feature_matrix(candles)
    labels_all=make_labels(candles, horizon=horizon, threshold=threshold)
    # align: X starts at 50, labels are per-index
    ys=[]
    for i in range(50, len(candles)):
        if i < len(labels_all):
            lbl=labels_all[i].get("label")
            ys.append(lbl if lbl else "flat")
        else:
            ys.append("flat")
    # truncate to X length
    ys=ys[:len(X)]
    X=X[:len(ys)]
    # filter Nones (end)
    filt=[(x,y) for x,y in zip(X,ys) if y is not None]
    if not filt: return ProbModel()
    X=np.array([f[0] for f in filt]); ys=[f[1] for f in filt]
    m=ProbModel(); m.fit(X, ys, names)
    return m
