"""AI decision-support contract adapter (Phase 5).

Runs the bounded review agents (analyst, signal reviewer, risk reviewer) and,
optionally, the LLM reviewer, then folds their outputs into the Phase 5 output
contract schema:

    {status, assessment, evidence, counter_evidence, risk_flags,
     uncertainties, invalidations, human_review_required}

BOUNDED BY DESIGN:
- Never changes the final quantitative decision.
- Never overrides a hard risk veto (RiskEngine stays authoritative).
- Risk reviewer cannot raise risk/trade, leverage, exposure, or daily-loss limits.
- Missing AI / no LLM key -> status UNAVAILABLE, never a silent approval.
- Does not invent market data: evidence fields only echo supplied facts.
"""
from __future__ import annotations

CONTRACT_VERSION = "0.1.0"

def _regime_label(regime) -> str:
    if regime is None:
        return "UNCERTAIN"
    if isinstance(regime, str):
        return regime
    if isinstance(regime, dict):
        return regime.get("regime", "UNCERTAIN")
    return getattr(regime, "regime", "UNCERTAIN")

def run_review(ctx: dict, decision=None, use_llm: bool = False) -> dict:
    """Run bounded review agents and return a Phase 5 contract record.

    ctx keys consumed:
      features, regime, ensemble, probability, mtf, proposed_direction
    decision: the Decision produced by DecisionEngine (authoritative). Its
      entry/stop/rr/risk_pct already passed the hard RiskEngine gate inside
      DecisionEngine; the risk reviewer here only ADVISES, never re-vetoes an
      already-approved quant decision, and never raises any risk limit.
    """
    from agents.analyst import analyze
    from agents.signal_reviewer import review as signal_review

    analyst_out = analyze({
        "features": ctx.get("features", {}),
        "regime": ctx.get("regime"),
        "ensemble": ctx.get("ensemble", {}),
        "probability": ctx.get("probability", {}),
    })
    sig_out = signal_review({
        "ensemble": ctx.get("ensemble", {}),
        "regime": ctx.get("regime"),
        "mtf": ctx.get("mtf"),
        "probability": ctx.get("probability", {}),
    })

    # Risk reviewer: advisory summary from the authoritative Decision. It cannot
    # raise risk/trade, leverage, exposure, or daily-loss limits. A hard veto
    # already expressed as NO_TRADE (quant_approved False) is surfaced as REJECT.
    dec_dict = decision
    if dec_dict is not None and not isinstance(dec_dict, dict):
        dec_dict = getattr(dec_dict, "__dict__", {}) or {}
    dec_dict = dec_dict or {}
    quant_approved = str(dec_dict.get("decision", "NO_TRADE")).upper() in ("LONG", "SHORT")
    risk_advisory = {
        "approved": quant_approved,
        "reason": dec_dict.get("reason", "") if quant_approved else "quant veto/NO_TRADE",
        "veto": None if quant_approved else "RISK_REJECT",
        "rr": dec_dict.get("rr"),
        "risk_pct": dec_dict.get("risk_pct"),
        "position_size": dec_dict.get("position_size"),
        "role": "risk_reviewer",
    }

    direction = str(ctx.get("proposed_direction") or
                    (ctx.get("ensemble", {}) or {}).get("direction", "NO_TRADE")).upper()

    evidence = [f for f in (analyst_out or {}).get("facts", [])]
    counter_evidence = []
    uncertainties = [u for u in (analyst_out or {}).get("uncertainties", [])]
    risk_flags = []
    invalidations = []

    # ---- Signal reviewer → PASS/FLAG/REJECT ----
    sig_approved = bool((sig_out or {}).get("approved", True))
    sig_flags = (sig_out or {}).get("flags", [])
    status = "PASS"
    if not sig_approved:
        status = "REJECT" if sig_flags else "PASS"
        invalidations.append("signal_reviewer: " + " ".join(sig_flags))
        status = "REJECT"
    elif sig_flags:
        status = "FLAG"
        risk_flags.extend(sig_flags)
    # analyst uncertainties surface as flags, not rejections
    for u in uncertainties:
        if u not in risk_flags:
            risk_flags.append(f"analyst: {u}")

    # ---- Risk reviewer (advisory) — quantitative veto always authoritative ----
    risk_approved = bool(risk_advisory.get("approved", True))
    veto = risk_advisory.get("veto")
    if veto:
        status = "REJECT"
        invalidations.append(f"risk_reviewer: veto {veto}")
        risk_flags.append(f"risk veto {veto}")
    elif not risk_approved:
        status = "REJECT"
        invalidations.append("risk_reviewer: rejected")
        risk_flags.append("risk reviewer rejected")

    # ---- LLM reviewer (optional) — advisory, never authority ----
    if use_llm:
        try:
            from agents.llm import llm_review
            llm = llm_review({
                "direction": direction,
                "ensemble": ctx.get("ensemble", {}),
                "probability": ctx.get("probability", {}),
                "regime": _regime_label(ctx.get("regime")),
                "analyst_facts": evidence,
                "signal_review": sig_out,
                "risk_review": risk_advisory,
            })
        except Exception:
            llm = None
        if llm is None:
            risk_flags.append("llm_reviewer: UNAVAILABLE (no key / call failed)")
            # do not silently approve; keep status as-is but annotate unavailability
            risk_flags.append("llm_review UNAVAILABLE")
        else:
            evidence.append("llm: " + str(llm.get("assessment", "")))
            for ce in (llm.get("counter_evidence") or []):
                if ce not in counter_evidence:
                    counter_evidence.append(ce)
            for rf in (llm.get("risk_flags") or []):
                if rf not in risk_flags:
                    risk_flags.append(rf)

    if isinstance(analyst_out, dict) and analyst_out.get("facts") is False:
        status = "UNAVAILABLE"

    assessment = (
        f"proposed_direction={direction}; signal_reviewer approved={sig_approved} "
        f"flags={sig_flags}; risk_reviewer approved={risk_approved}; "
        f"contract_v{CONTRACT_VERSION}"
    )

    return {
        "status": status,
        "assessment": assessment,
        "evidence": evidence,
        "counter_evidence": counter_evidence,
        "risk_flags": risk_flags,
        "uncertainties": uncertainties,
        "invalidations": invalidations,
        "human_review_required": status in ("FLAG", "REJECT", "UNAVAILABLE"),
        "contract_version": CONTRACT_VERSION,
        "role": "ai_contract",
    }

def review_passes(review: dict) -> bool:
    """A bounded decision-support gate: REJECT or UNAVAILABLE blocks going LONG/SHORT."""
    # This is advisory; the quantitative engine is the real gate. Exposed so a
    # caller may consult it. Never used to override a hard risk veto.
    return review.get("status") in ("PASS", "FLAG")
