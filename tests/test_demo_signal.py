"""DEMO signal source (frozen RegimeGatedTrend) wiring tests.

Isolated (conftest): temp DB, TRADING_TG_SEND=0, LLM stubbed to None (no network,
no 9Router). Pure in-memory candidates — no orders, no demo DB writes.

Proves:
- DEMO candidates carry explicit frozen source metadata (strategy_id/version).
- RegimeGatedTrend is the ONLY source; legacy ensemble never reaches DEMO.
- LOW_VOL/RANGE/... rejected; TREND_BULL->LONG and TREND_BEAR->SHORT eligible
  when RiskEngine approves.
- PAPER (Coordinator ensemble) path is unchanged/untouched by this module.
- No exchange/Telegram side effects.
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import conftest  # noqa: F401
from execution.demo_signal import build_demo_candidate
from execution.eligibility import (
    FROZEN_DEMO_STRATEGY_ID, FROZEN_DEMO_STRATEGY_VERSION,
    FROZEN_DEMO_ALLOWED_REGIMES, check_demo_eligibility, ELIGIBLE, REASONS,
)

_NOW = int(time.time() * 1000)
_H = 3600000


def candles_gen(start: float, slope: float, up: bool, n: int = 400,
                atr_frac: float = 0.012) -> list[dict]:
    """Deterministic OHLCV ramp producing the target regime on the last bars."""
    base_ts = _NOW - n * _H
    out = []
    for i in range(n):
        mid = start + i * slope
        o = mid
        cl = mid + (slope * 0.7 if up else -slope * 0.7)
        swing = abs(mid) * atr_frac
        hi = max(o, cl) + swing
        lo = min(o, cl) - swing
        ot = base_ts + i * _H
        out.append({"symbol": "BTCUSDT", "timeframe": "1h", "open": o,
                    "high": hi, "low": lo, "close": cl, "volume": 50000,
                    "open_time": ot, "close_time": ot + _H - 1})
    return out


def test_demo_candidate_carries_frozen_source_metadata():
    c = build_demo_candidate(candles_gen(1000, 5, True), equity=10000)
    assert c["strategy_id"] == FROZEN_DEMO_STRATEGY_ID == "trend_gated"
    assert c["strategy_version"] == FROZEN_DEMO_STRATEGY_VERSION == "0.1.0"
    assert c["symbol"] == "BTCUSDT" and c["timeframe"] == "1h"
    assert c["signal_id"] and c["decision_id"]
    print("frozen_metadata PASS", c["strategy_id"], c["strategy_version"])


def test_demo_low_vol_rejected():
    # low-volatility ramp (tiny atr) -> LOW_VOL regime -> NEUTRAL source -> rejected
    c = build_demo_candidate(candles_gen(1000, 0.3, True, atr_frac=0.002), equity=10000)
    assert c["regime"] == "LOW_VOL", c["regime"]
    assert c["signal"] == "NEUTRAL" and c["decision"] == "NO_TRADE"
    assert not c["eligibility"]["eligible"]
    assert c["eligibility"]["reason"] in (REASONS.REGIME_BLOCKED, REASONS.NOT_TRADE)
    print("demo_low_vol_rejected PASS", c["eligibility"]["reason"])


def test_demo_trend_bull_long_eligible():
    c = build_demo_candidate(candles_gen(1000, 5, True), equity=10000)
    assert c["regime"] == "TREND_BULL", c["regime"]
    assert c["signal"] == "LONG" and c["decision"] == "LONG"
    assert c["risk_engine"] == "APPROVED"
    assert c["eligibility"]["eligible"] and c["eligibility"]["reason"] == ELIGIBLE
    assert c["entry"] and c["stop"] and c["tp1"]
    print("demo_trend_bull_long_eligible PASS")


def test_demo_trend_bear_short_eligible():
    c = build_demo_candidate(candles_gen(4000, -6, False), equity=10000)
    assert c["regime"] == "TREND_BEAR", c["regime"]
    assert c["signal"] == "SHORT" and c["decision"] == "SHORT"
    assert c["risk_engine"] == "APPROVED"
    assert c["eligibility"]["eligible"] and c["eligibility"]["reason"] == ELIGIBLE
    print("demo_trend_bear_short_eligible PASS")


def test_wrong_strategy_version_cannot_pass():
    # gate is authoritative: bad version/strategy never eligible
    r = check_demo_eligibility({"strategy_id": "trend_gated", "strategy_version": "9.9.9",
                                "regime": "TREND_BULL", "decision": "LONG",
                                "risk_engine": "APPROVED"})
    assert not r["eligible"] and r["reason"] == REASONS.WRONG_VERSION
    r2 = check_demo_eligibility({"strategy_id": "ensemble", "strategy_version": "0.1.0",
                                 "regime": "TREND_BULL", "decision": "LONG",
                                 "risk_engine": "APPROVED"})
    assert not r2["eligible"] and r2["reason"] == REASONS.WRONG_STRATEGY
    print("wrong_strategy_version_cannot_pass PASS")


def test_risk_veto_not_overridden():
    # frozen-eligible shape but RiskEngine REJECT -> hard no (AI cannot flip)
    r = check_demo_eligibility({"strategy_id": FROZEN_DEMO_STRATEGY_ID,
                                "strategy_version": FROZEN_DEMO_STRATEGY_VERSION,
                                "regime": "TREND_BULL", "decision": "LONG",
                                "risk_engine": "REJECT", "ai_status": "PASS"})
    assert not r["eligible"] and r["reason"] == REASONS.RISK_REJECT
    print("risk_veto_not_overridden PASS")


def test_paper_and_demo_sources_isolated():
    # PAPER path = Coordinator ensemble (unchanged). DEMO path here must never
    # consume an ensemble-labelled signal. Prove the source module only ever tags
    # frozen strategy_id and rejects the ensemble id via the authoritative gate.
    ensemble_sig = {"strategy_id": "ensemble", "strategy_version": "0.1.0",
                    "regime": "TREND_BULL", "decision": "LONG",
                    "risk_engine": "APPROVED"}
    # even a perfectly trending ensemble output is not a frozen DEMO candidate
    assert not check_demo_eligibility(ensemble_sig)["eligible"]
    # and a real frozen candidate never claims ensemble identity
    c = build_demo_candidate(candles_gen(1000, 5, True), equity=10000)
    assert c["strategy_id"] == "trend_gated"
    print("paper_demo_sources_isolated PASS")


def test_no_exchange_or_telegram_side_effects():
    import agents.telegram_notifier as tg
    from execution import demo_signal as ds
    # no exchange-order symbols in the module; telegram not imported by demo path
    import inspect
    src = inspect.getsource(ds)
    assert "place_order" not in src and "sendMessage" not in src
    assert tg._creds()[0] is None  # send disabled by conftest (TRADING_TG_SEND=0)
    # no demo DB writes: build_demo_candidate returns dict, touches no storage
    assert "demo_orders" not in dir(ds)
    print("no_exchange_telegram_side_effects PASS")


def test_regime_aliases_rejected_by_source():
    # source gate must reject every disallowed regime alias (no silent pass)
    from execution.eligibility import check_demo_eligibility
    for reg in ("RANGE", "HIGH_VOL", "HIGH_VOLATILITY",
                "LOW_VOL", "LOW_VOLATILITY", "UNCERTAIN"):
        r = check_demo_eligibility({"strategy_id": FROZEN_DEMO_STRATEGY_ID,
                                    "strategy_version": FROZEN_DEMO_STRATEGY_VERSION,
                                    "regime": reg, "decision": "LONG",
                                    "risk_engine": "APPROVED"})
        assert not r["eligible"] and r["reason"] == REASONS.REGIME_BLOCKED, (reg, r)
    print("regime_aliases_rejected PASS")


if __name__ == "__main__":
    test_demo_candidate_carries_frozen_source_metadata()
    test_demo_low_vol_rejected()
    test_demo_trend_bull_long_eligible()
    test_demo_trend_bear_short_eligible()
    test_wrong_strategy_version_cannot_pass()
    test_risk_veto_not_overridden()
    test_paper_and_demo_sources_isolated()
    test_no_exchange_or_telegram_side_effects()
    test_regime_aliases_rejected_by_source()
    print("ALL DEMO SIGNAL SOURCE TESTS PASS")
