"""DEMO execution source-of-truth eligibility gate (Phase "no Phase 6" extension).

Single deterministic gate deciding whether a candidate signal is allowed to
reach DEMO exchange execution. PAPER behavior is NOT touched here.

Frozen Phase 4 candidate the gate enforces (docs/PHASE4_FROZEN_SPEC.md,
docs/PAPER_FINAL_SPEC.md):
  strategy_id          = "trend_gated"   (evaluation.regime_gating.RegimeGatedTrend.name)
  strategy_version     = "0.1.0"         (frozen Phase 4 / Phase 5 value)
  allowed regimes      = {TREND_BULL, TREND_BEAR}
  decision             = LONG or SHORT
  RiskEngine           = authoritative: APPROVED required; REJECT is final and
                         cannot be overridden by AI.
  AI                   = review only. A PASS never promotes a rejected signal;
                         a REJECT never demotes a RiskEngine-approved one here
                         (deterministic gate ignores AI for approval).

A legacy 4-strategy ensemble signal (Coordinator runtime path) is labelled with
strategy_id != "trend_gated" and MUST be rejected for DEMO. It remains valid for
the existing PAPER path, which this module never touches.
"""
from __future__ import annotations

# --- Frozen source-of-truth constants (do not change without a new spec) ----
FROZEN_DEMO_STRATEGY_ID = "trend_gated"
FROZEN_DEMO_STRATEGY_VERSION = "0.1.0"
FROZEN_DEMO_ALLOWED_REGIMES = frozenset({"TREND_BULL", "TREND_BEAR"})

# Verdict / failure reasons (deterministic, stable strings for tests & logs)
ELIGIBLE = "ELIGIBLE"
class _R:
    WRONG_STRATEGY = "WRONG_STRATEGY"      # not the frozen RegimeGatedTrend id
    WRONG_VERSION = "WRONG_VERSION"        # strategy_version != frozen
    REGIME_BLOCKED = "REGIME_BLOCKED"      # regime not in {TREND_BULL, TREND_BEAR}
    NOT_TRADE = "NOT_TRADE"                # decision not LONG/SHORT
    RISK_REJECT = "RISK_REJECT"            # RiskEngine not APPROVED (final)
    RISK_UNAVAILABLE = "RISK_UNAVAILABLE"  # no explicit RiskEngine result -> fail closed
REASONS = _R()

_DECISION_OK = frozenset({"LONG", "SHORT"})
_RISK_OK = ("APPROVED", "approved", "PASS", "pass", "APPROVE")
_RISK_REJECTED = ("REJECT", "reject", "REJECTED", "NO_TRADE", "denied")


def _norm(sig: dict) -> dict:
    d = dict(sig or {})
    for k in ("decision", "signal", "direction"):
        if k in d and d[k] is not None:
            d.setdefault("decision", d[k])
    return d


def _risk_verdict(risk_engine) -> str:
    """Map a RiskEngine result to APPROVED / REJECTED / None(unknown)."""
    if risk_engine is None:
        return "unknown"
    if isinstance(risk_engine, str):
        s = risk_engine.strip().upper()
        if s in ("APPROVED", "PASS", "APPROVE", "OK"):
            return "approved"
        if s in ("REJECT", "REJECTED", "DENIED", "VETO", "NO_TRADE"):
            return "rejected"
        return "unknown"
    # object/attribute form (e.g. a RiskResult with .approved)
    a = getattr(risk_engine, "approved", None)
    if a is not None:
        return "approved" if a else "rejected"
    return "unknown"


def check_demo_eligibility(signal: dict) -> dict:
    """Pure deterministic gate. Returns {"eligible": bool, "reason": str, "decision": ...}.

    signal expects (all normalized case-insensitively where stated):
      strategy_id, strategy_version, regime, decision|signal|direction,
      risk_engine (APPROVED/REJECT or object with .approved), ai_status (optional).
    Fail-closed: any unknown/unverifiable field -> not eligible with reason.
    """
    sig = _norm(signal)
    decision = str(sig.get("decision") or "NO_TRADE").upper()
    regime = str(sig.get("regime") or "").upper()
    sid = str(sig.get("strategy_id") or sig.get("strategy") or "").lower()
    ver = str(sig.get("strategy_version") or sig.get("version") or "")

    # 1. strategy must be the frozen RegimeGatedTrend path
    if sid != FROZEN_DEMO_STRATEGY_ID:
        return {"eligible": False, "reason": REASONS.WRONG_STRATEGY,
                "strategy_id": sid, "decision": decision}
    # 2. frozen strategy version
    if ver != FROZEN_DEMO_STRATEGY_VERSION:
        return {"eligible": False, "reason": REASONS.WRONG_VERSION,
                "strategy_version": ver, "decision": decision}
    # 3. regime gate (Phase 4 ALLOW)
    if regime not in FROZEN_DEMO_ALLOWED_REGIMES:
        return {"eligible": False, "reason": REASONS.REGIME_BLOCKED,
                "regime": regime, "decision": decision}
    # 4. trade direction
    if decision not in _DECISION_OK:
        return {"eligible": False, "reason": REASONS.NOT_TRADE,
                "decision": decision, "regime": regime}
    # 5. RiskEngine authoritative. No explicit approval -> fail closed.
    rv = _risk_verdict(sig.get("risk_engine"))
    if rv != "approved":
        reason = REASONS.RISK_REJECT if rv == "rejected" else REASONS.RISK_UNAVAILABLE
        return {"eligible": False, "reason": reason, "risk_engine": rv,
                "decision": decision, "regime": regime}
    # AI is REVIEW ONLY: never consulted for approval here. A deterministic pass
    # stands; a RiskEngine rejection above is already final (AI cannot override).
    return {"eligible": True, "reason": ELIGIBLE, "strategy_id": sid,
            "strategy_version": ver, "regime": regime, "decision": decision,
            "risk_engine": rv, "ai_status": sig.get("ai_status")}
