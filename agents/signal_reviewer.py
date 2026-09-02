"""Signal Reviewer — checks internal coherence, never invents."""
from __future__ import annotations
def review(signal_ctx:dict)->dict:
    ens=signal_ctx.get("ensemble",{})
    regime=signal_ctx.get("regime")
    mtf=signal_ctx.get("mtf")
    prob=signal_ctx.get("probability",{})
    flags=[]
    approved=True
    reason="coherent"
    if isinstance(ens,dict):
        if ens.get("direction")=="NEUTRAL": flags.append("neutral ensemble"); approved=False; reason="neutral"
        if ens.get("score",0)<35: flags.append(f"low score {ens.get('score')}")
    reg=str(getattr(regime,"regime", regime) if not isinstance(regime,dict) else regime.get("regime","") if regime else "")
    if reg=="UNCERTAIN": flags.append("regime uncertain")
    if isinstance(mtf,dict) and mtf.get("veto"): flags.append(f"mtf veto {mtf.get('veto')}"); approved=False; reason="mtf veto"
    if isinstance(prob,dict):
        need= prob.get("p_up",0) if ens.get("direction")=="LONG" else prob.get("p_down",0)
        if isinstance(need,float) and need<0.55: flags.append(f"low prob {need:.2f}")
    # must not invent evidence: only reference provided
    return {"approved":approved,"reason":reason,"flags":flags,"role":"signal_reviewer"}
