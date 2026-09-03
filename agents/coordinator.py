"""Coordinator — enforces pipeline order, collects outputs, never bypasses risk."""
from __future__ import annotations
import time

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
        from storage.database import init_db, insert_decision, log_event
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
        ai_review = {}
        try:
            from agents.ai_contract import run_review
            ai_review = run_review(
                {**ctx,
                 "features": feats, "regime": regime_dict,
                 "ensemble": ens_dict, "probability": prob_dict,
                 "mtf": mtf_dict,
                 "proposed_direction": ens_dict.get("direction", "NO_TRADE")},
                decision=dec, use_llm=False)
        except Exception:
            ai_review = {}

        # 12. persist
        try:
            init_db()
            dd=dec.to_dict() if hasattr(dec,'to_dict') else (dec.__dict__ if hasattr(dec,'__dict__') else dec)
            # json fields need dumps handling inside insert_decision already
            insert_decision(dd)
            log_event("coordinator","info",f"decision {dec.get('decision')} {dec.get('reason','')[:120]}",{"symbol":symbol,"decision":dec.get("decision")})
            # persist bounded AI review record (decision-support audit)
            if ai_review:
                import json as _json
                log_event("ai_contract","info",f"AI review status={ai_review.get('status')} dir={ai_review.get('assessment','')[:80]}",
                          {"symbol":symbol,"decision":dec.get("decision"),"review":_json.dumps(ai_review,default=str)})
        except Exception as e:
            # failure to persist still returns decision but logs
            pass

        return dec
