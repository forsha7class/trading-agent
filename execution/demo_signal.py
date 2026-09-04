"""Isolated DEMO signal source — frozen RegimeGatedTrend path.

PAPER behavior is NOT touched: the existing Coordinator 4-strategy ensemble path
lives entirely elsewhere and remains the PAPER signal source. This module builds
a SEPARATE candidate stream that reaches DEMO execution (added later) by feeding
the frozen Phase 4 candidate through the unchanged deterministic pipeline:

  live candles -> validate -> features -> regime(detect_regime)
      -> RegimeGatedTrend (frozen, ALLOW={TREND_BULL,TREND_BEAR})
      -> existing DecisionEngine (runs unchanged RiskEngine + level derivation)
      -> existing bounded AI review policy (only for approved LONG/SHORT)
      -> explicit source metadata + execution/eligibility.py (authoritative gate)

Guarantees:
- Never consumes legacy/ensemble signals: signal comes only from RegimeGatedTrend.
- Strategy is NOT modified or retuned. RiskEngine untouched. AI provider untouched.
- LOW_VOL / RANGE / HIGH_VOL / UNCERTAIN never produce a trade here because
  RegimeGatedTrend returns NEUTRAL for them (regime gate at the source).
- No orders, no demo DB writes, no Telegram. Purely in-memory candidate output.
"""
from __future__ import annotations
import time

from execution.eligibility import (
    check_demo_eligibility, FROZEN_DEMO_STRATEGY_ID, FROZEN_DEMO_STRATEGY_VERSION,
    FROZEN_DEMO_ALLOWED_REGIMES, ELIGIBLE,
)
from evaluation.regime_gating import RegimeGatedTrend, ALLOWED_TREND_REGIMES

# ---- frozen source config (mirrors docs/PHASE4_FROZEN_SPEC.md / PAPER_FINAL_SPEC.md)
DEMO_SIGNAL_SOURCE_DEFAULT = "trend_gated"
_TIMEFRAME_DEFAULT = "1h"


def _signal_key(symbol: str, timeframe: str, bar_open_time: int) -> str:
    return f"{symbol}:{timeframe}:{bar_open_time}"


def _regime_label(regime) -> str:
    if regime is None:
        return "UNCERTAIN"
    if isinstance(regime, str):
        return regime
    if isinstance(regime, dict):
        return regime.get("regime", "UNCERTAIN")
    return getattr(regime, "regime", "UNCERTAIN")


def build_demo_candidate(
    candles: list[dict],
    symbol: str = "BTCUSDT",
    timeframe: str = "1h",
    equity: float = 10000.0,
    positions: int = 0,
    daily_pnl: float = 0.0,
    use_llm: bool = False,
) -> dict:
    """Build a DB-shaped DEMO candidate from the frozen RegimeGatedTrend source.

    Returns a dict (never raises) shaped like the future demo lifecycle record:
      {strategy_id, strategy_version, regime, decision, decision_id, signal_id,
       symbol, timeframe, side, entry, stop, tp1, tp2, rr, risk_pct,
       position_size, risk_engine, veto, ai_status, ai_review, eligibility,
       reason, ts}

    `eligibility` is the authoritative execution/eligibility.py verdict.
    No order is placed and nothing is persisted.
    """
    now_ms = int(time.time() * 1000)
    candles = candles or []
    ts = candles[-1].get("close_time", now_ms) if candles else now_ms
    base = {
        "symbol": symbol.upper(), "timeframe": timeframe, "ts": ts,
        "strategy_id": FROZEN_DEMO_STRATEGY_ID,
        "strategy_version": FROZEN_DEMO_STRATEGY_VERSION,
        "allowed_regimes": sorted(FROZEN_DEMO_ALLOWED_REGIMES),
        "risk_engine": "UNAVAILABLE", "veto": None,
        "ai_status": "SKIPPED", "ai_review": {},
        "regime": "UNCERTAIN", "decision": "NO_TRADE",
        "signal": "NO_TRADE", "side": "NO_TRADE",
    }

    # 1. validate candles
    try:
        from ingestion.validation import validate_candles
        vr = validate_candles(candles, symbol=symbol, timeframe=timeframe, now_ms=now_ms)
        if not vr.valid:
            base["reason"] = f"DATA_INVALID: {vr.reason}"
            base["decision_id"] = _signal_key(symbol.upper(), timeframe, 0)
            base["signal_id"] = _signal_key(symbol.upper(), timeframe, 0)
            base["eligibility"] = check_demo_eligibility(base)
            return base
    except Exception as e:
        base["reason"] = f"VALIDATION_ERROR: {e}"
        return base

    # 2. features (causal, same as existing pipeline)
    try:
        from features.technical import build_features
        feats = build_features(candles)
        if not isinstance(feats, dict) or feats.get("error") == "insufficient_data" \
                or feats.get("sufficient") is not True:
            base["reason"] = "INSUFFICIENT_DATA: <50 bars"
            return base
        feats["close"] = feats["close_last"]  # expose close (Coordinator convention)
    except Exception as e:
        base["reason"] = f"FEATURE_ERROR: {e}"
        return base

    # 3. regime
    try:
        from regime.detector import detect_regime
        regime = detect_regime(feats, candles)
        label = _regime_label(regime)
        base["regime"] = label
        base["regime_version"] = getattr(regime, "version", None)
        base["regime_confidence"] = getattr(regime, "confidence", None)
    except Exception as e:
        base["reason"] = f"REGIME_ERROR: {e}"
        return base

    # 4. frozen signal source: RegimeGatedTrend (regime gate AT the source)
    try:
        gated = RegimeGatedTrend(allowed=ALLOWED_TREND_REGIMES)
        sig = gated.generate({"features": feats, "candles": candles,
                              "timeframe": timeframe, "regime": label})
        direction = str(getattr(sig, "direction", "NEUTRAL") or "NEUTRAL").upper()
        base["signal"] = direction
        base["signal_evidence"] = list(getattr(sig, "evidence", []) or [])
        base["signal_counter"] = list(getattr(sig, "counter_evidence", []) or [])
        base["signal_strength"] = getattr(sig, "strength", None)
    except Exception as e:
        base["reason"] = f"SIGNAL_ERROR: {e}"
        return base

    base["signal_id"] = _signal_key(symbol.upper(), timeframe,
                                    candles[-1].get("open_time", 0))

    # 5. deterministic levels + unchanged RiskEngine via DecisionEngine.
    #    Only LONG/SHORT (impossible outside TREND_BULL/BEAR here) reach risk.
    if direction not in ("LONG", "SHORT"):
        base["decision"] = "NO_TRADE"
        base["decision_id"] = base["signal_id"]
        base["reason"] = f"NO_TRADE: regime {label} blocked by frozen gate (NEUTRAL)"
        base["eligibility"] = check_demo_eligibility(base)
        return base

    try:
        from decision.engine import DecisionEngine
        ctx = {
            "symbol": symbol.upper(), "timeframe": timeframe,
            "candles": candles, "features": feats, "regime": label,
            "signal": direction,           # authoritative source dir (NOT ensemble)
            "equity": equity, "positions": positions, "daily_pnl": daily_pnl,
            "data_ts": ts, "leverage": 1.0,
        }
        dec = DecisionEngine().decide(ctx)
        dec_dict = dec.to_dict() if hasattr(dec, "to_dict") else \
            (dec.__dict__ if hasattr(dec, "__dict__") else dec)
        approved = str(dec_dict.get("decision", "NO_TRADE")).upper() in ("LONG", "SHORT")
        base["decision"] = str(dec_dict.get("decision", "NO_TRADE")).upper()
        base["side"] = base["decision"]
        base["entry"] = dec_dict.get("entry")
        base["stop"] = dec_dict.get("stop")
        base["tp1"] = dec_dict.get("tp1")
        base["tp2"] = dec_dict.get("tp2")
        base["rr"] = dec_dict.get("rr")
        base["risk_pct"] = dec_dict.get("risk_pct")
        base["position_size"] = dec_dict.get("position_size")
        base["decision_id"] = dec_dict.get("id") or base["signal_id"]
        base["reason"] = str(dec_dict.get("reason") or "")
        base["risk_engine"] = "APPROVED" if approved else "REJECTED"
        base["veto"] = None if approved else "RISK_REJECT"
    except Exception as e:
        base["decision"] = "NO_TRADE"
        base["reason"] = f"DECISION_ERROR: {e}"
        base["risk_engine"] = "REJECTED"
        base["veto"] = "CRITICAL_FAILURE"
        base["decision_id"] = base["signal_id"]

    # 6. bounded AI review (advisory, token-efficient: only approved LONG/SHORT)
    if base["decision"] in ("LONG", "SHORT") and base["risk_engine"] == "APPROVED":
        try:
            from agents.ai_contract import run_review
            base["ai_review"] = run_review(
                {"features": feats, "regime": label,
                 "ensemble": {"direction": direction, "score": 100},
                 "probability": {}, "mtf": {}, "proposed_direction": direction,
                 "symbol": symbol.upper(), "timeframe": timeframe},
                decision=dec_dict, use_llm=use_llm) or {}
            base["ai_status"] = base["ai_review"].get("status", "UNAVAILABLE")
        except Exception:
            base["ai_status"] = "UNAVAILABLE"
            base["ai_review"] = {}

    # 7. authoritative eligibility gate (source of truth)
    base["eligibility"] = check_demo_eligibility({
        "strategy_id": base["strategy_id"],
        "strategy_version": base["strategy_version"],
        "regime": base["regime"],
        "decision": base["decision"],
        "risk_engine": base["risk_engine"],
        "ai_status": base["ai_status"],
    })
    return base


def traceable_chain(candidate: dict) -> dict:
    """Condensed audit trace per task: signal -> risk -> AI -> eligibility."""
    elig = candidate.get("eligibility", {})
    return {
        "signal_id": candidate.get("signal_id"),
        "decision_id": candidate.get("decision_id"),
        "strategy_id": candidate.get("strategy_id"),
        "strategy_version": candidate.get("strategy_version"),
        "regime": candidate.get("regime"),
        "decision": candidate.get("decision"),
        "side": candidate.get("side"),
        "risk_engine": candidate.get("risk_engine"),
        "ai_status": candidate.get("ai_status"),
        "eligible": elig.get("eligible"),
        "eligibility_reason": elig.get("reason"),
        "symbol": candidate.get("symbol"),
        "entry": candidate.get("entry"),
        "ts": candidate.get("ts"),
    }
