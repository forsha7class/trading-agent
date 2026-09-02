"""Generic strategy evaluation — per symbol/tf/regime, realistic execution."""
from __future__ import annotations
import math, time
from features.technical import build_features
from regime.detector import detect_regime
from trade_signal.ensemble import aggregate as _agg

def evaluate_strategy(candles:list[dict], strategy, fee:float=0.0004, slippage:float=0.0005, risk_pct:float=0.005, min_rr:float=1.5, horizon:int=20)->dict:
    n=len(candles)
    trades=[]
    equity=10000.0; peak=10000.0; mdd=0.0; eq_curve=[equity]
    # track regime
    regime_stats={}
    for i in range(50, n):
        window=candles[:i+1]
        f=build_features(window)
        if f.get("error"): eq_curve.append(equity); continue
        if "close_last" in f: f["close"]=f["close_last"]
        reg=detect_regime(f, window)
        market={"features":f,"candles":window,"timeframe":candles[0].get("timeframe","1h"),"regime":reg.regime}
        sig=strategy.generate(market)
        if sig.direction=="NEUTRAL" or sig.strength < 0.35:
            eq_curve.append(equity); continue
        close=float(candles[i]["close"])
        atr=float(f.get("atr14", close*0.015) or close*0.015)
        entry=close
        stop= sig.invalidation if sig.invalidation else (entry-atr*1.8 if sig.direction=="LONG" else entry+atr*1.8)
        sd=abs(entry-float(stop)) if stop else atr*1.8
        tp= entry+sd*min_rr if sig.direction=="LONG" else entry-sd*min_rr
        # lookahead
        hit=None; exit_price=None
        for j in range(i+1, min(n, i+1+horizon)):
            hi=float(candles[j]["high"]); lo=float(candles[j]["low"])
            if sig.direction=="LONG":
                if lo <= float(stop): hit="SL"; exit_price=float(stop); break
                if hi >= tp: hit="TP"; exit_price=tp; break
            else:
                if hi >= float(stop): hit="SL"; exit_price=float(stop); break
                if lo <= tp: hit="TP"; exit_price=tp; break
        if not hit:
            eq_curve.append(equity); continue
        allowed=equity*risk_pct; size=allowed/max(1e-9, sd)
        eff_entry=entry+entry*slippage*(1 if sig.direction=="LONG" else -1)
        eff_exit=exit_price-exit_price*slippage*(1 if sig.direction=="LONG" else -1) if hit=="TP" else exit_price+exit_price*slippage*(1 if sig.direction=="LONG" else -1)
        gross=(eff_exit-eff_entry)*size if sig.direction=="LONG" else (eff_entry-eff_exit)*size
        fees=(abs(eff_entry*size)+abs(eff_exit*size))*fee
        net=gross-fees
        equity+=net; eq_curve.append(equity); peak=max(peak, equity); mdd=max(mdd, (peak-equity)/peak if peak else 0)
        rec={"entry":entry,"exit":exit_price,"side":sig.direction,"pnl":net,"hit":hit,"bar":i,"regime":reg.regime,"score":sig.strength}
        trades.append(rec)
        # regime bucket
        regime_stats.setdefault(reg.regime, []).append(net)
    pnls=[t["pnl"] for t in trades]
    wins=sum(1 for x in pnls if x>0); wr=wins/len(pnls) if pnls else 0
    pf=sum(x for x in pnls if x>0)/abs(sum(x for x in pnls if x<=0) or 1) if pnls else 0
    # streak
    max_loss_streak=cur=0; ml=0
    for x in pnls:
        if x<=0: cur+=1; ml=max(ml,cur)
        else: cur=0
    # regime table
    by_regime={}
    for k,v in regime_stats.items():
        by_regime[k]={"trades":len(v),"win_rate":sum(1 for x in v if x>0)/len(v) if v else 0,"expectancy":sum(v)/len(v) if v else 0,"pnl":sum(v)}
    return {"trades":trades,"metrics":{"trade_count":len(trades),"win_rate":round(wr,4),"profit_factor":round(pf,4),"expectancy":round(sum(pnls)/len(pnls),2) if pnls else 0,"max_drawdown":round(mdd,4),"equity":round(equity,2),"pnl":round(equity-10000,2),"max_loss_streak":ml,"by_regime":by_regime,"equity_curve":eq_curve}}

def evaluate_all(candles:list[dict], fee:float=0.0004, slippage:float=0.0005)->dict:
    from strategies.trend import TrendStrategy
    from strategies.momentum import MomentumStrategy
    from strategies.breakout import BreakoutStrategy
    from strategies.mean_reversion import MeanReversionStrategy
    out={}
    for cls in [TrendStrategy, MomentumStrategy, BreakoutStrategy, MeanReversionStrategy]:
        out[cls().name]=evaluate_strategy(candles, cls(), fee=fee, slippage=slippage)
    return out
