"""Risk Reviewer — checks sizing/RR, cannot lower hard limits."""
from __future__ import annotations
def review(risk_ctx:dict, risk_result=None)->dict:
    # risk_result is RiskResult
    if risk_result is None:
        try:
            from risk.risk_engine import RiskEngine
            from risk.limits import RiskLimits
        except ImportError:
            from trading_agent.risk.risk_engine import RiskEngine
            from trading_agent.risk.limits import RiskLimits
        risk_result=RiskEngine().check(risk_ctx)
    approved=bool(risk_result.approved)
    return {"approved":approved,"reason":risk_result.reason,"veto":risk_result.veto,"rr":risk_result.rr,"position_size":risk_result.position_size,"risk_pct":risk_result.risk_pct,"role":"risk_reviewer"}
