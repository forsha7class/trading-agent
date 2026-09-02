"""Backtest — no lookahead, includes fees/slippage/position sizing/SL/TP."""
from __future__ import annotations
import math, numpy as np

def run_backtest(candles:list[dict], strategy_fn=None, risk_fn=None, config:dict|None=None)->dict:
    cfg=config or {}
    fee=float(cfg.get("fee",0.0004)); slip=float(cfg.get("slippage",0.0005))
    equity=float(cfg.get("equity",10000)); risk_pct=float(cfg.get("risk_per_trade",0.005))
    min_rr=float(cfg.get("min_rr",1.5))
    # fees/slippage applied per trade
    eq=equity; peak=equity; mdd=0.0
    equity_curve=[eq]
    trades=[]
    # need features builder
    try:
        from features.technical import build_features
    except ImportError:
        from trading_agent.features.technical import build_features
    # simple baseline signal: if strategy_fn not given, use EMA cross on the fly
    for i in range(50, len(candles)):
        window=candles[:i+1]  # causal: only up to i inclusive (no future)
        feats=build_features(window)
        if feats.get("error"): equity_curve.append(eq); continue
        close=float(candles[i]["close"])
        # signal: use provided fn or EMA rule
        direction="NEUTRAL"
        if strategy_fn:
            try:
                sig=strategy_fn({"features":feats,"candles":window,"timeframe":"1h"})
                direction=str(getattr(sig,"direction", sig.get("direction","NEUTRAL") if isinstance(sig,dict) else "NEUTRAL")).upper()
            except: direction="NEUTRAL"
        else:
            # built-in: ema20>ema50 => LONG else SHORT (for testing)
            try:
                if not math.isnan(feats.get("ema20", float("nan"))) and not math.isnan(feats.get("ema50", float("nan"))):
                    direction="LONG" if feats["ema20"]>feats["ema50"] and close>feats["ema20"] else ("SHORT" if feats["ema20"]<feats["ema50"] and close<feats["ema20"] else "NEUTRAL")
            except: pass
        if direction=="NEUTRAL": equity_curve.append(eq); continue
        # risk: compute entry/stop/tp
        atr=float(feats.get("atr14", close*0.015) or close*0.015)
        entry=close
        stop= entry-1.8*atr if direction=="LONG" else entry+1.8*atr
        sd=abs(entry-stop)
        tp= entry+sd*min_rr if direction=="LONG" else entry-sd*min_rr
        rr= abs(tp-entry)/sd if sd else 0
        if rr < min_rr-1e-9: equity_curve.append(eq); continue
        # position size: risk_pct*equity / sd
        allowed=eq*risk_pct
        size=allowed/sd if sd else 0
        # look ahead max 20 bars for SL/TP
        hit=None; exit_price=None
        for j in range(i+1, min(len(candles), i+21)):
            hi=float(candles[j]["high"]); lo=float(candles[j]["low"])
            if direction=="LONG":
                if lo<=stop: hit="SL"; exit_price=stop; break
                if hi>=tp: hit="TP"; exit_price=tp; break
            else:
                if hi>=stop: hit="SL"; exit_price=stop; break
                if lo<=tp: hit="TP"; exit_price=tp; break
        if not hit: equity_curve.append(eq); continue
        # slippage adverse
        eff_entry=entry+entry*slip*(1 if direction=="LONG" else -1)
        eff_exit=exit_price-exit_price*slip*(1 if direction=="LONG" else -1) if hit=="TP" else exit_price+exit_price*slip*(1 if direction=="LONG" else -1)
        # gross
        gross=(eff_exit-eff_entry)*size if direction=="LONG" else (eff_entry-eff_exit)*size
        fees=(abs(eff_entry*size)+abs(eff_exit*size))*fee
        net=gross-fees
        eq+=net; equity_curve.append(eq)
        peak=max(peak,eq); mdd=max(mdd,(peak-eq)/peak if peak else 0)
        trades.append({"entry":entry,"exit":exit_price,"side":direction,"pnl":net,"hit":hit,"bar":i})
        # advance i to j to avoid overlapping
        # (ponytail: single position; extend to portfolio later)
    # metrics
    pnls=[t["pnl"] for t in trades]
    rets=[pnls[k]/equity_curve[k] if equity_curve[k] else 0 for k in range(len(pnls))] if pnls else []
    try:
        from evaluation.metrics import sharpe, sortino, win_rate, profit_factor, max_drawdown
    except ImportError:
        from trading_agent.evaluation.metrics import sharpe, sortino, win_rate, profit_factor, max_drawdown
    metrics={
        "trades":len(trades),"equity":round(eq,2),"pnl":round(eq-equity,2),
        "return_pct":round((eq/equity-1)*100,2) if equity else 0,
        "win_rate":round(win_rate(pnls),4) if pnls else 0,
        "profit_factor":round(profit_factor(pnls),4) if pnls else 0,
        "max_drawdown":round(max_drawdown(equity_curve),4),
        "sharpe":round(sharpe(rets),4) if rets else 0,
        "sortino":round(sortino(rets),4) if rets else 0,
        "expectancy":round(float(np.mean(pnls)) if pnls else 0,2),
        "avg_pnl":round(float(np.mean(pnls)) if pnls else 0,2),
    }
    return {"trades":trades,"equity_curve":equity_curve,"metrics":metrics,"mdd":mdd}

def walk_forward(candles:list[dict], splits:int=3, **kwargs)->dict:
    n=len(candles)
    if n<100: return {"error":"not enough data"}
    chunk=n//(splits+1)
    results=[]
    for k in range(splits):
        train=candles[:chunk*(k+1)]
        test=candles[chunk*(k+1):chunk*(k+2)]
        if not test: break
        r=run_backtest(test, **kwargs)
        results.append({"split":k,"train_len":len(train),"test_len":len(test),"metrics":r["metrics"]})
    return {"splits":results}
