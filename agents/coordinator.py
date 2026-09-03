"""Coordinator — enforces pipeline order, collects outputs, never bypasses risk."""
from __future__ import annotations
import time
try:
    from storage.database import _append_only_trigger  # ensure decisions append-only guard
    _append_only_trigger()
except Exception:
    pass

class Coordinator:
    def run(self, symbol:str="BTCUSDT", timeframe:str="1h", candles:list[dict]|None=None, equity:float=10000, **kw)->dict:
        """Full pipeline from candles -> decision. If candles None, fetches live."""
        from ingestion.validation import validate_candles
        from features.technical import build_features
        from regime.detector import detect_regime
        from strategies.trend import TrendStrategy
        from strategies.momentum import MomentumStrategy
        from strategies.breakout import BreakoutStrategy
        from strategies.mean_reversion import MeanReversionStrategy
        from trade_signal.ensemble import aggregate
        from trade_signal.probability import estimate
        from trade_signal.mtf import check_mtf
        from evaluation.metrics import max_drawdown as _mdd
        from decision.engine import DecisionEngine
        from storage.database import init_db, insert_decision, log_event, get_db
        from decision.state_machine import DecisionStateMachine

        sm=DecisionStateMachine()
        now=int(time.time()*1000)

        # 1. fetch if needed
        if candles is None:
            try:
                from ingestion.market_data import fetch_klines
                candles=fetch_klines(symbol, timeframe, limit=100)
            except Exception as e:
                sm.transition("DECISION","fetch failed")
                dec=DecisionEngine().decide({"symbol":symbol,"timeframe":timeframe,"validation":{"valid":False,"reason":"SYSTEM_FAILURE","details":str(e)}})
                try: insert_decision(dec)
                except: pass
                return dec

        # 2. validate
        vr=validate_candles(candles, symbol=symbol, timeframe=timeframe, now_ms=now)
        if not vr.valid:
            sm.transition("DECISION", vr.reason)
            dec=DecisionEngine().decide({"symbol":symbol,"timeframe":timeframe,"candles":candles,"validation":vr,"features":{"error":"insufficient_data"}})
            try: init_db(); insert_decision(dec); log_event("coordinator","warn",f"NO_TRADE {vr.reason}",{"symbol":symbol})
            except: pass
            return dec
        sm.transition("DATA_VALID","validated")
        sm.transition("ANALYZING","building features")

        # 3. features
        feats=build_features(candles)
        # expose close for regime
        if "close_last" in feats: feats["close"]=feats["close_last"]
        sm.transition("SIGNAL_GENERATED","features done")

        # 4. regime
        regime=detect_regime(feats, candles)
        regime_dict={"regime":regime.regime,"confidence":regime.confidence,"evidence":regime.evidence,"version":regime.version} if hasattr(regime,"regime") else regime

        # 5. strategies
        strategies=[TrendStrategy(), MomentumStrategy(), BreakoutStrategy(), MeanReversionStrategy()]
        market_state={"features":feats,"candles":candles,"timeframe":timeframe,"regime":regime.regime if hasattr(regime,"regime") else str(regime)}
        signals=[s.generate(market_state) for s in strategies]

        # 6. ensemble
        ensemble=aggregate(signals, regime=regime)
        # Convert CombinedSignal to dict for downstream
        ens_dict={"direction":ensemble.direction,"score":ensemble.score,"supporting":ensemble.supporting,"contradicting":ensemble.contradicting,"weights":ensemble.weights,"breakdown":ensemble.breakdown} if hasattr(ensemble,"direction") else ensemble

        # 7. probability
        prob=estimate(ensemble, feats, regime)
        prob_dict={"p_up":prob.p_up,"p_down":prob.p_down,"p_flat":prob.p_flat,"version":prob.version} if hasattr(prob,"p_up") else prob

        # 8. MTF (with single TF as stub; real multi-TF would fetch 4h/15m/5m separately)
        # For MVP single-TF, treat as aligned if score strong
        mtf_res=check_mtf({timeframe: {"direction":ens_dict.get("direction","NEUTRAL"),"strength":ens_dict.get("score",0)/100,"ts":candles[-1].get("close_time",now)}}, weights={timeframe:1.0}, now_ms=now)
        mtf_dict={"aligned":mtf_res.aligned,"score":mtf_res.score,"veto":mtf_res.veto,"details":mtf_res.details}

        sm.transition("RISK_CHECK","ensemble+prob done")

        # 9. entry/stop/tp derived in DecisionEngine; pass equity etc
        ctx={
            "symbol":symbol,"timeframe":timeframe,"candles":candles,"features":feats,
            "regime":regime,"ensemble":ens_dict,"probability":prob_dict,"mtf":mtf_dict,
            "validation":vr,"equity":equity,"daily_pnl":kw.get("daily_pnl",0),"positions":kw.get("positions",0),
            "leverage":kw.get("leverage",1.0),"data_ts":candles[-1].get("close_time",now),
            "spread_pct":kw.get("spread_pct",0),
        }

        # AI_REVIEW precedes DECISION in the state machine (advisory layer ran).
        sm.transition("AI_REVIEW", "review done (bounded)")

        # 11. decision (risk enforced inside — authoritative, unchanged)
        dec=DecisionEngine().decide(ctx)
        sm.transition("DECISION", (dec.get("reason") or "")[:120])

        # 11b. Bounded AI decision-support review (Phase 5). Runs AFTER the
        # authoritative quant decision. Advisory only — never changes `dec`,
        # never overrides the hard RiskEngine veto already applied inside
        # DecisionEngine, and cannot raise any risk limit.
        # Token efficiency: DeepSeek is invoked ONLY for an eligible LONG/SHORT
        # candidate. An ordinary NO_TRADE is reviewed deterministically (no LLM),
        # so routine no-trade decisions cause ZERO LLM calls.
        ai_review = {}
        try:
            from agents.ai_contract import run_review
            _eligible = str(dec.get("decision") or dec.get("signal") or "").upper() in ("LONG", "SHORT")
            ai_review = run_review(
                {**ctx,
                 "symbol": symbol, "timeframe": timeframe,
                 "features": feats, "regime": regime_dict,
                 "ensemble": ens_dict, "probability": prob_dict,
                 "mtf": mtf_dict,
                 "proposed_direction": ens_dict.get("direction", "NO_TRADE")},
                decision=dec, use_llm=_eligible)
        except Exception:
            ai_review = {}

        # 12. persist (single authoritative insert; append-only)
        try:
            init_db()
            dd=dec.to_dict() if hasattr(dec,'to_dict') else (dec.__dict__ if hasattr(dec,'__dict__') else dec)
            # json fields need dumps handling inside insert_decision already
            existing = get_db().execute("SELECT id FROM decisions WHERE symbol=? AND ts=? ORDER BY id DESC LIMIT 1",
                                        (dd.get("symbol"), dd.get("ts") or dd.get("timestamp"))).fetchone()
            if existing is None:
                insert_decision(dd)
                existing = get_db().execute("SELECT id FROM decisions WHERE symbol=? AND ts=? ORDER BY id DESC LIMIT 1",
                                            (dd.get("symbol"), dd.get("ts") or dd.get("timestamp"))).fetchone()
            if existing is not None and hasattr(dec, "id"):
                dec.id = int(existing["id"])
            log_event("coordinator","info",f"decision {dec.get('decision')} {dec.get('reason','')[:120]}",{"symbol":symbol,"decision":dec.get("decision")})
            # persist bounded AI review record (decision-support audit)
            if ai_review:
                import json as _json
                log_event("ai_contract","info",f"AI review status={ai_review.get('status')} dir={ai_review.get('assessment','')[:80]}",
                          {"symbol":symbol,"decision":dec.get("decision"),"review":_json.dumps(ai_review,default=str)})
        except Exception as e:
            # failure to persist still returns decision but logs
            pass

        # 13. Telegram notification — OBSERVABILITY ONLY, never part of decision.
        # Runs after the authoritative decision; failures are logged, not raised,
        # so the pipeline is never affected by a notification problem.
        try:
            _notify_decision(symbol, timeframe, dec, ai_review)
        except Exception:
            # notification must never crash the quant pipeline
            pass

        return dec


def _notify_decision(symbol: str, timeframe: str, dec, ai_review: dict) -> None:
    """Translate a coordinator decision into a bounded Telegram notification.

    Pure observability. Reuses decision fields already computed; never calls into
    strategies, risk, or AI agents (kept out of those modules by construction).
    """
    from agents import telegram_notifier as tg
    from storage.database import log_event
    dd = dec.to_dict() if hasattr(dec, "to_dict") else (dec.__dict__ if hasattr(dec, "__dict__") else dec)
    dd = dd or {}
    decision = str(dd.get("decision") or dd.get("signal") or "NO_TRADE").upper()
    reason = str(dd.get("reason") or "")
    base = {
        "symbol": symbol, "timeframe": timeframe,
        "decision": decision, "direction": decision,
        "regime": dd.get("regime") or "?",
        "entry": dd.get("entry"), "stop": dd.get("stop"),
        "tp1": dd.get("tp1"), "tp2": dd.get("tp2"),
        "rr": dd.get("rr"), "risk_pct": dd.get("risk_pct"),
        "p_up": (dd.get("probability") or {}).get("p_up") if isinstance(dd.get("probability"), dict) else None,
        "p_down": (dd.get("probability") or {}).get("p_down") if isinstance(dd.get("probability"), dict) else None,
        "decision_id": dd.get("id") or dd.get("ts"),
        "ts": dd.get("ts") or dd.get("timestamp"),
        "ai_status": (ai_review or {}).get("status", "UNAVAILABLE"),
        "evidence": (ai_review or {}).get("evidence", []),
        "counter_evidence": (ai_review or {}).get("counter_evidence", []),
        "risk_flags": (ai_review or {}).get("risk_flags", []),
        "invalidations": (ai_review or {}).get("invalidations", []),
    }
    ai_status = (ai_review or {}).get("status", "UNAVAILABLE")
    risk_veto_markers = ("RISK_REJECT", "RR_INSUFFICIENT", "RISK_BUDGET_EXHAUSTED",
                         "NO_", "LIQUIDITY", "VOLATILITY", "POSITION_LIMIT", "veto")

    result = None
    if decision in ("LONG", "SHORT"):
        # approved trade signal (paper mode) — include AI status
        base["mode"] = "PAPER"
        result = tg.notify(tg.EVENT_SIGNAL, base)
    elif ai_status == "FLAG":
        base["reasons"] = (ai_review or {}).get("risk_flags", []) or \
                          (ai_review or {}).get("uncertainties", [])
        result = tg.notify(tg.EVENT_AI_FLAG, base)
    elif ai_status == "REJECT" and not any(m in reason.upper() for m in risk_veto_markers):
        base["reason"] = reason or "AI review rejected"
        result = tg.notify(tg.EVENT_AI_REJECT, base)
    elif "NO_TRADE" in decision or any(m in reason.upper() for m in risk_veto_markers):
        # only notify if a risk veto (not routine no-signal)
        if any(m in reason.upper() for m in ("RISK_REJECT", "RR_INS", "VETO", "RISK_BUDGET", "NO_ILLIQUID", "NO_EXCESS", "NO_MARTINGALE", "NO_AVERAGING", "NO_RISK_OVERRIDE", "NO_INVALID_RR", "POSITION_LIMIT", "VOLATILITY", "LIQUIDITY")):
            base["reason"] = reason
            base["risk_engine"] = "REJECT"
            result = tg.notify(tg.EVENT_RISK_REJECT, base)

    if result:
        try:
            log_event("telegram", "debug",
                      f"notify {result.get('sent') and 'sent' or (result.get('deduped') and 'deduped' or 'skipped')} {decision}",
                      {"symbol": symbol, "sent": result.get("sent"),
                       "deduped": result.get("deduped"),
                       "error": tg.redact_secret(str(result.get("error") or ""))})
        except Exception:
            pass
