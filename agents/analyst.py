"""Analyst — separates FACT from INTERPRETATION. No market data invention."""
from __future__ import annotations
def analyze(market_state:dict)->dict:
    regime=market_state.get("regime")
    feats=market_state.get("features",{})
    ens=market_state.get("ensemble",{})
    prob=market_state.get("probability",{})
    # FACT
    facts=[]
    if regime: facts.append(f"regime={getattr(regime,'regime', regime) if not isinstance(regime,dict) else regime.get('regime')}")
    if feats:
        for k in ("ema20","ema50","rsi14","atr14","momentum","vol"):
            if k in feats: facts.append(f"{k}={feats[k]}")
    if ens: facts.append(f"ensemble {ens.get('direction')} score={ens.get('score')}")
    if prob: facts.append(f"prob up={prob.get('p_up')} down={prob.get('p_down')} flat={prob.get('p_flat')}")
    # INTERPRETATION (bounded: only from provided evidence)
    interp=[]
    if isinstance(ens,dict) and ens.get("score",0)>=60: interp.append("signal moderately strong")
    elif isinstance(ens,dict) and ens.get("score",0)<40: interp.append("signal weak — prefer NO_TRADE")
    uncertainties=[]
    if isinstance(regime,dict) and regime.get("regime")=="UNCERTAIN": uncertainties.append("regime uncertain")
    elif hasattr(regime,"regime") and getattr(regime,"regime")=="UNCERTAIN": uncertainties.append("regime uncertain")
    if not facts: uncertainties.append("insufficient evidence")
    return {"facts":facts,"interpretation":interp,"uncertainties":uncertainties,"role":"analyst","valid":True}
