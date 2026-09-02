"""Decision Maker — combines quant + reviews into LONG/SHORT/NO_TRADE. Never overrides hard risk."""
from __future__ import annotations
def make_decision(ctx:dict, reviews:dict|None=None)->dict:
    # delegate to decision engine (single source); reviews are advisory
    reviews=reviews or {}
    # if any hard risk veto present, force NO_TRADE regardless of reviews
    risk_rev=reviews.get("risk",{})
    if isinstance(risk_rev,dict) and risk_rev.get("approved") is False and risk_rev.get("veto"):
        return {"decision":"NO_TRADE","reason":f"hard risk veto {risk_rev.get('veto')} — decision NO_TRADE","reviews":reviews}
    # signal reviewer reject -> NO_TRADE advisory (not hard veto, but weight)
    # actual decision via DecisionEngine
    try:
        from decision.engine import DecisionEngine
    except ImportError:
        from trading_agent.decision.engine import DecisionEngine
    return DecisionEngine().decide(ctx)
