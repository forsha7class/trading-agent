"""Promotion checklist gate."""
from __future__ import annotations

GATE = [
    "sufficient_history", "no_leakage", "realistic_costs", "oos_expectancy_positive",
    "acceptable_drawdown", "reasonable_trade_count", "param_stability", "cost_sensitivity_ok",
    "regime_understood", "no_severe_wf_degradation", "paper_consistent", "reproducible"
]

def evaluate_gate(metrics: dict) -> dict:
    """metrics: dict with keys matching gate checks. Each value bool or numeric."""
    checks={}
    checks["sufficient_history"] = metrics.get("history_bars",0) >= 2000
    checks["no_leakage"] = bool(metrics.get("leakage_pass", False))
    checks["realistic_costs"] = bool(metrics.get("fees_included", False))
    checks["oos_expectancy_positive"] = metrics.get("oos_expectancy", -1) > 0
    checks["acceptable_drawdown"] = metrics.get("max_drawdown",1) < 0.30
    checks["reasonable_trade_count"] = 20 <= metrics.get("trade_count",0) <= 500
    checks["param_stability"] = metrics.get("param_stable", False)
    checks["cost_sensitivity_ok"] = metrics.get("cost_ok", False)
    checks["regime_understood"] = bool(metrics.get("regime_report", False))
    checks["no_severe_wf_degradation"] = not metrics.get("wf_degraded", True)
    checks["paper_consistent"] = bool(metrics.get("paper_ok", False))
    checks["reproducible"] = bool(metrics.get("reproducible", False))
    passed = sum(1 for v in checks.values() if v)
    status = "VALIDATED" if passed>=10 else ("PROMISING" if passed>=7 else ("INCONCLUSIVE" if passed>=4 else "REJECTED"))
    return {"checks":checks, "passed":passed, "total":len(GATE), "status":status}

def classify_strategy(name: str, metrics: dict) -> str:
    return evaluate_gate(metrics)["status"]
