"""NO_TRADE analysis — traded vs rejected EV. Historical-mode (no stale veto)."""
from __future__ import annotations
from features.technical import build_features
from regime.detector import detect_regime
from strategies.trend import TrendStrategy
from strategies.momentum import MomentumStrategy
from strategies.breakout import BreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy
from trade_signal.ensemble import aggregate
from trade_signal.probability import estimate
from trade_signal.mtf import check_mtf
from decision.engine import DecisionEngine
from evaluation.labels import make_labels
import time

def analyze(candles:list[dict], equity:float=10000)->dict:
    labels=make_labels(candles, horizon=4, threshold=0.005)
    strategies=[TrendStrategy(), MomentumStrategy(), BreakoutStrategy(), MeanReversionStrategy()]
    de=DecisionEngine()
    traded_pnl=[]; rejected_pnl=[]; counts={"traded":0,"rejected":0,"traded_win":0,"rejected_win":0}
    for i in range(50, len(candles)-4):
        window=candles[:i+1]
        f=build_features(window)
        if f.get("error"):
            counts["rejected"]+=1; rejected_pnl.append(0); continue
        if "close_last" in f: f["close"]=f["close_last"]
        reg=detect_regime(f, window)
        market={"features":f,"candles":window,"timeframe":candles[0].get("timeframe","1h"),"regime":reg.regime}
        sigs=[s.generate(market) for s in strategies]
        ens=aggregate(sigs, regime=reg)
        ens_dict={"direction":ens.direction,"score":ens.score,"supporting":ens.supporting,"contradicting":ens.contradicting}
        prob=estimate(ens, f, reg)
        prob_dict={"p_up":prob.p_up,"p_down":prob.p_down,"p_flat":prob.p_flat}
        # MTF stub historical — single TF
        mtf={"aligned":True,"score":70,"veto":None}
        # Decision without stale veto: pass data_ts as window last close_time, and skip stale by using historical now
        # DecisionEngine checks data_ts age vs now; we override data_ts to now to avoid stale rejection for historical windows
        now_ms=int(time.time()*1000)
        ctx={"symbol":candles[0].get("symbol","BTCUSDT"),"timeframe":candles[0].get("timeframe","1h"),
             "candles":window,"features":f,"regime":reg,"ensemble":ens_dict,"probability":prob_dict,"mtf":mtf,
             "equity":equity,"data_ts":now_ms, "spread_pct":0}
        dec=de.decide(ctx)
        ret=labels[i]["ret"] if i < len(labels) and labels[i]["ret"] is not None else 0
        is_traded=dec.decision in ("LONG","SHORT")
        # win: direction matches future return sign (threshold 0.005)
        if ret is None: ret=0
        win=(ret>0.005 and dec.decision=="LONG") or (ret<-0.005 and dec.decision=="SHORT")
        # for NO_TRADE, would_have_won = flat threshold exceeded (any direction move)
        if not is_traded:
            counts["rejected"]+=1
            if abs(ret or 0)>0.005:
                rejected_pnl.append(abs(ret)*100)
                counts["rejected_win"]+=1
            else:
                rejected_pnl.append(0)
        else:
            counts["traded"]+=1
            pnl=(1 if win else -1)*abs(ret or 0)*100 if ret else 0
            traded_pnl.append(pnl)
            if win: counts["traded_win"]+=1
    def ev(arr): return sum(arr)/len(arr) if arr else 0
    total=counts["traded"]+counts["rejected"]
    return {
        "traded":counts["traded"],"rejected":counts["rejected"],
        "rejection_rate": round(counts["rejected"]/total,4) if total else 0,
        "traded_win_rate": round(counts["traded_win"]/counts["traded"],4) if counts["traded"] else 0,
        "rejected_would_win_rate": round(counts["rejected_win"]/counts["rejected"],4) if counts["rejected"] else 0,
        "ev_traded": round(ev(traded_pnl),4), "ev_rejected": round(ev(rejected_pnl),4),
        "filter_adds_value": ev(traded_pnl) > ev(rejected_pnl),
    }
