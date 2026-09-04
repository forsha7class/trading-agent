"""DEMO source-of-truth eligibility gate tests.

Isolated DB + no telegram (conftest) + pure gate (no external IO, no orders).
Verifies the Phase "gate only" scope: PAPER path untouched, no demo execution,
no demo DB schema, no order placement.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import conftest  # noqa: F401
from execution.eligibility import (
    check_demo_eligibility, ELIGIBLE,
    FROZEN_DEMO_STRATEGY_ID, FROZEN_DEMO_STRATEGY_VERSION,
    FROZEN_DEMO_ALLOWED_REGIMES,
    REASONS,
)

# canonical frozen RegimeGatedTrend approved signal
def _frozen(side="LONG", regime="TREND_BULL", ver=FROZEN_DEMO_STRATEGY_VERSION,
            risk="APPROVED", ai="PASS"):
    return {"strategy_id": FROZEN_DEMO_STRATEGY_ID, "strategy_version": ver,
            "regime": regime, "decision": side, "risk_engine": risk, "ai_status": ai}

# legacy 4-strategy ensemble signal (Coordinator runtime). Ensemble carries no
# single strategy_id; mark explicitly as ensemble source so it can never pass.
def _ensemble(side="LONG", regime="LOW_VOL", risk="APPROVED", ai="PASS"):
    return {"strategy_id": "ensemble", "strategy_version": "0.1.0",
            "regime": regime, "decision": side, "risk_engine": risk, "ai_status": ai}


def test_low_vol_long_from_ensemble_rejected():
    r = check_demo_eligibility(_ensemble("LONG", "LOW_VOL"))
    assert not r["eligible"]
    assert r["reason"] == REASONS.WRONG_STRATEGY  # ensemble never reaches demo
    print("low_vol_ensemble_rejected PASS", r["reason"])


def test_trend_bull_long_frozen_eligible_if_risk_passes():
    r = check_demo_eligibility(_frozen("LONG", "TREND_BULL"))
    assert r["eligible"], r
    assert r["reason"] == ELIGIBLE
    print("trend_bull_frozen_eligible PASS")


def test_trend_bear_short_frozen_eligible_if_risk_passes():
    r = check_demo_eligibility(_frozen("SHORT", "TREND_BEAR"))
    assert r["eligible"], r
    assert r["reason"] == ELIGIBLE
    print("trend_bear_frozen_eligible PASS")


def test_wrong_strategy_version_rejected():
    r = check_demo_eligibility(_frozen(ver="9.9.9"))
    assert not r["eligible"]
    assert r["reason"] == REASONS.WRONG_VERSION
    print("wrong_version_rejected PASS")


def test_legacy_ensemble_signal_rejected_for_demo():
    # even a perfectly-trending ensemble output with risk+ai pass must not pass
    for regime in ("TREND_BULL", "TREND_BEAR", "LOW_VOL", "RANGE"):
        r = check_demo_eligibility(_ensemble("LONG", regime))
        assert not r["eligible"], (regime, r)
        assert r["reason"] == REASONS.WRONG_STRATEGY
    print("legacy_ensemble_rejected PASS")


def test_risk_veto_rejected_regardless_of_source():
    # RiskEngine REJECT is final for both sources; AI PASS cannot override.
    # Frozen source -> RISK_REJECT; ensemble source fails earlier (WRONG_STRATEGY),
    # but both are rejected.
    r = check_demo_eligibility(_frozen("LONG", "TREND_BULL", risk="REJECT", ai="PASS"))
    assert not r["eligible"] and r["reason"] == REASONS.RISK_REJECT
    for make in (_frozen, _ensemble):
        r = check_demo_eligibility(make("LONG", "LOW_VOL", risk="REJECT", ai="PASS"))
        assert not r["eligible"], (make.__name__, r)
        assert r["reason"] in (REASONS.RISK_REJECT, REASONS.WRONG_STRATEGY,
                               REASONS.REGIME_BLOCKED)
    print("risk_veto_rejected PASS")


def test_risk_unavailable_fails_closed():
    # no explicit risk approval -> NOT eligible (fail closed, never a silent pass)
    r = check_demo_eligibility(_frozen("LONG", "TREND_BULL", risk=None))
    assert not r["eligible"]
    assert r["reason"] == REASONS.RISK_UNAVAILABLE
    print("risk_unavailable_fail_closed PASS")


def test_ai_cannot_override_rejection():
    # RiskEngine reject + AI PASS -> still rejected (AI review-only)
    r = check_demo_eligibility(_frozen("LONG", "TREND_BULL", risk="REJECT", ai="PASS"))
    assert not r["eligible"]
    assert r["reason"] == REASONS.RISK_REJECT
    # Wrong strategy + AI FLAG -> still rejected (source is frozen truth)
    r2 = check_demo_eligibility(_ensemble("LONG", "TREND_BULL", ai="FLAG"))
    assert not r2["eligible"]
    print("ai_cannot_override_rejection PASS")


def test_regime_aliases_blocked():
    # spec treats HIGH_VOL==HIGH_VOLATILITY, LOW_VOL==LOW_VOLATILITY -> blocked
    for regime in ("RANGE", "HIGH_VOL", "HIGH_VOLATILITY",
                   "LOW_VOL", "LOW_VOLATILITY", "UNCERTAIN", "TREND_BULLISH"):
        r = check_demo_eligibility(_frozen("LONG", regime))
        assert not r["eligible"], (regime, r)
        assert r["reason"] == REASONS.REGIME_BLOCKED
    print("regime_aliases_blocked PASS")


def test_not_trade_rejected():
    r = check_demo_eligibility(_frozen("NO_TRADE", "TREND_BULL"))
    assert not r["eligible"]
    assert r["reason"] == REASONS.NOT_TRADE
    print("not_trade_rejected PASS")


def test_frozen_constants_match_spec():
    assert FROZEN_DEMO_STRATEGY_ID == "trend_gated"
    assert FROZEN_DEMO_STRATEGY_VERSION == "0.1.0"
    assert FROZEN_DEMO_ALLOWED_REGIMES == {"TREND_BULL", "TREND_BEAR"}
    print("frozen_constants PASS")


if __name__ == "__main__":
    test_low_vol_long_from_ensemble_rejected()
    test_trend_bull_long_frozen_eligible_if_risk_passes()
    test_trend_bear_short_frozen_eligible_if_risk_passes()
    test_wrong_strategy_version_rejected()
    test_legacy_ensemble_signal_rejected_for_demo()
    test_risk_veto_rejected_regardless_of_source()
    test_risk_unavailable_fails_closed()
    test_ai_cannot_override_rejection()
    test_regime_aliases_blocked()
    test_not_trade_rejected()
    test_frozen_constants_match_spec()
    print("ALL DEMO ELIGIBILITY TESTS PASS")
