"""Decision engine — LONG/SHORT/NO_TRADE with specific NO_TRADE reasons. Never bypasses risk."""
from __future__ import annotations
import time
from dataclasses import dataclass, field, asdict

NO_TRADE_REASONS = {
    "DATA_INVALID": "DATA_INVALID",
    "DATA_STALE": "DATA_STALE",
    "INSUFFICIENT_DATA": "INSUFFICIENT_DATA",
    "REGIME_UNCERTAIN": "REGIME_UNCERTAIN",
    "WEAK_SIGNAL": "WEAK_SIGNAL",
    "STRATEGY_DISAGREEMENT": "STRATEGY_DISAGREEMENT",
    "CONTRADICTORY_TF": "CONTRADICTORY_TF",
    "MTF_VETO": "MTF_VETO",
    "RISK_REJECT": "RISK_REJECT",
    "RR_INSUFFICIENT": "RR_INSUFFICIENT",
    "LIQUIDITY_INSUFFICIENT": "LIQUIDITY_INSUFFICIENT",
    "VOLATILITY_EXCESSIVE": "VOLATILITY_EXCESSIVE",
    "RISK_BUDGET_EXHAUSTED": "RISK_BUDGET_EXHAUSTED",
    "POSITION_LIMIT": "POSITION_LIMIT",
    "AI_REJECT": "AI_REJECT",
    "SYSTEM_FAILURE": "SYSTEM_FAILURE",
}

def _rr(entry, stop, tp):
    if entry is None or stop is None: return 0
    sd = abs(float(entry) - float(stop))
    if sd == 0: return 0
    if tp is None: return 0
    return abs(float(tp) - float(entry)) / sd

@dataclass
class Decision:
    symbol: str = "TEST"
    signal: str = "NO_TRADE"  # LONG/SHORT/NO_TRADE
    probability: float | dict | None = None
    regime: str | None = None
    entry: float | None = None
    stop: float | None = None
    tp1: float | None = None
    tp2: float | None = None
    risk_pct: float | None = None
    rr: float | None = None
    evidence: list = field(default_factory=list)
    counter_evidence: list = field(default_factory=list)
    reason: str = ""
    timestamp: int = 0
    versions: dict = field(default_factory=dict)
    # extra for compat
    no_trade_reason: str | None = None
    position_size: float | None = None
    decision: str | None = None
    timeframe: str | None = None
    data_ts: int | None = None
    ts: int | None = None  # alias for storage compatibility

    def __post_init__(self):
        if self.timestamp == 0:
            self.timestamp = int(time.time()*1000)
        if self.ts is None:
            self.ts=self.timestamp
        elif self.timestamp==self.ts:
            pass
        # keep both in sync
        if self.decision is None:
            self.decision = self.signal

    # dict-like compat: engine historically returned dict; keep get/__getitem__
    def __getitem__(self, k): return getattr(self, k) if hasattr(self, k) else self.__dict__[k]
    def __contains__(self, k): return k in self.__dict__
    def get(self, k, d=None): return self.__dict__.get(k, d)
    def keys(self): return self.__dict__.keys()

class DecisionEngine:
    def __init__(self, risk_engine=None, limits=None):
        try:
            from risk.risk_engine import RiskEngine
            from risk.limits import RiskLimits
            self.risk = risk_engine or RiskEngine()
            self.limits = limits or RiskLimits()
        except Exception:
            from trading_agent.risk.risk_engine import RiskEngine
            from trading_agent.risk.limits import RiskLimits
            self.risk = risk_engine or RiskEngine()
            self.limits = limits or RiskLimits()
        try:
            from decision.state_machine import DecisionStateMachine
            self.sm = DecisionStateMachine()
        except Exception:
            from trading_agent.decision.state_machine import DecisionStateMachine
            self.sm = DecisionStateMachine()

    def decide(self, ctx: dict) -> Decision:
        try:
            return self._decide(ctx)
        except Exception as e:
            import logging; logging.getLogger(__name__).exception("decision critical")
            return Decision(symbol=ctx.get("symbol","BTCUSDT"), signal="NO_TRADE", probability=None, regime=ctx.get("regime","UNCERTAIN") if isinstance(ctx.get("regime"), str) else "UNCERTAIN", entry=None, stop=None, tp1=None, tp2=None, risk_pct=None, rr=None, evidence=[], counter_evidence=[], reason=f"SYSTEM_FAILURE:{e}", timestamp=int(time.time()*1000), versions=ctx.get("versions",{}), no_trade_reason="SYSTEM_FAILURE")

    def _decide(self, ctx: dict) -> Decision:
        ts = int(time.time()*1000)
        symbol = ctx.get("symbol","BTCUSDT")
        tf = ctx.get("timeframe","1h")
        versions = ctx.get("versions",{})
        if not versions:
            try:
                from config.settings import get_settings
                s = get_settings()
                versions = {"feature":s.feature_version,"strategy":s.strategy_version,"model":s.model_version,"prompt":s.prompt_version}
            except Exception:
                versions = {"feature":"0.1.0","strategy":"0.1.0","model":"0.1.0","prompt":"0.1.0"}

        # staledata fast veto before any signal
        if ctx.get("is_stale") or ctx.get("stale"):
            try: self.sm.transition("DECISION","DATA_STALE")
            except: pass
            return Decision(symbol=symbol, signal="NO_TRADE", probability=ctx.get("probability") or ctx.get("prob"), regime=self._regime_str(ctx), entry=None, stop=None, tp1=None, tp2=None, risk_pct=None, rr=None, evidence=[], counter_evidence=[], reason="NO_TRADE: DATA_STALE — stale data", timestamp=ts, versions=versions, no_trade_reason="DATA_STALE", timeframe=tf)

        age = ctx.get("data_age_s")
        if age is not None and age > self.limits.stale_threshold_s:
            try: self.sm.transition("DECISION","DATA_STALE")
            except: pass
            return Decision(symbol=symbol, signal="NO_TRADE", probability=ctx.get("probability") or ctx.get("prob"), regime=self._regime_str(ctx), entry=None, stop=None, tp1=None, tp2=None, risk_pct=None, rr=None, evidence=[], counter_evidence=[], reason=f"NO_TRADE: DATA_STALE — age {age:.0f}s", timestamp=ts, versions=versions, no_trade_reason="DATA_STALE", timeframe=tf)

        if ctx.get("critical_failure"):
            return Decision(symbol=symbol, signal="NO_TRADE", probability=None, regime=self._regime_str(ctx), entry=None, stop=None, tp1=None, tp2=None, risk_pct=None, rr=None, evidence=[], counter_evidence=[], reason="NO_TRADE: SYSTEM_FAILURE — critical", timestamp=ts, versions=versions, no_trade_reason="SYSTEM_FAILURE", timeframe=tf)

        # validation
        vr = ctx.get("validation")
        if vr is not None:
            valid = getattr(vr,"valid", vr.get("valid") if isinstance(vr,dict) else True)
            if not valid:
                reason = str(getattr(vr,"reason", vr.get("reason","DATA_INVALID") if isinstance(vr,dict) else "DATA_INVALID"))
                return Decision(symbol=symbol, signal="NO_TRADE", probability=None, regime=self._regime_str(ctx), entry=None, stop=None, tp1=None, tp2=None, risk_pct=None, rr=None, evidence=[], counter_evidence=[], reason=f"NO_TRADE: DATA_INVALID — {reason}", timestamp=ts, versions=versions, no_trade_reason="DATA_INVALID", timeframe=tf)

        feats = ctx.get("features") or {}
        if feats.get("error") == "insufficient_data":
            return Decision(symbol=symbol, signal="NO_TRADE", probability=None, regime=self._regime_str(ctx), entry=None, stop=None, tp1=None, tp2=None, risk_pct=None, rr=None, evidence=[], counter_evidence=[], reason="NO_TRADE: INSUFFICIENT_DATA", timestamp=ts, versions=versions, no_trade_reason="INSUFFICIENT_DATA", timeframe=tf)

        ensemble = ctx.get("ensemble") or {}
        prob = ctx.get("probability") or ctx.get("prob") or {}
        mtf = ctx.get("mtf") or {}
        # derive proposed direction
        direction = str(ctx.get("signal", ctx.get("proposed_signal", ensemble.get("direction","NO_TRADE") if isinstance(ensemble,dict) else "NO_TRADE"))).upper()
        # also consider direct ctx signal
        if direction not in ("LONG","SHORT"):
            # check if ensemble says LONG/SHORT but ctx overrides
            if direction == "NO_TRADE" and ctx.get("reason"):
                return Decision(symbol=symbol, signal="NO_TRADE", probability=prob, regime=self._regime_str(ctx), entry=None, stop=None, tp1=None, tp2=None, risk_pct=None, rr=None, evidence=[], counter_evidence=[], reason=f"NO_TRADE: {ctx['reason']}", timestamp=ts, versions=versions, no_trade_reason=ctx["reason"], timeframe=tf)
            return Decision(symbol=symbol, signal="NO_TRADE", probability=prob, regime=self._regime_str(ctx), entry=None, stop=None, tp1=None, tp2=None, risk_pct=None, rr=None, evidence=[], counter_evidence=[], reason="NO_TRADE: WEAK_SIGNAL — no signal", timestamp=ts, versions=versions, no_trade_reason="WEAK_SIGNAL", timeframe=tf)

        # ensemble weak
        if isinstance(ensemble, dict):
            score = int(ensemble.get("score", 50))
            if score < 40:
                return Decision(symbol=symbol, signal="NO_TRADE", probability=prob, regime=self._regime_str(ctx), entry=None, stop=None, tp1=None, tp2=None, risk_pct=None, rr=None, evidence=[], counter_evidence=[], reason=f"NO_TRADE: WEAK_SIGNAL — score {score}<40", timestamp=ts, versions=versions, no_trade_reason="WEAK_SIGNAL", timeframe=tf)
            if ensemble.get("veto") or (mtf.get("veto") if isinstance(mtf,dict) else False):
                return Decision(symbol=symbol, signal="NO_TRADE", probability=prob, regime=self._regime_str(ctx), entry=None, stop=None, tp1=None, tp2=None, risk_pct=None, rr=None, evidence=[], counter_evidence=[], reason="NO_TRADE: CONTRADICTORY_TF — veto", timestamp=ts, versions=versions, no_trade_reason="CONTRADICTORY_TF", timeframe=tf)

        # probability edge
        if isinstance(prob, dict):
            need = prob.get("p_up",0) if direction=="LONG" else prob.get("p_down",0)
            # if prob is empty, allow (ponytail: enforce when model versioned)
            if prob and need < 0.55:
                return Decision(symbol=symbol, signal="NO_TRADE", probability=prob, regime=self._regime_str(ctx), entry=None, stop=None, tp1=None, tp2=None, risk_pct=None, rr=None, evidence=[], counter_evidence=[], reason=f"NO_TRADE: WEAK_SIGNAL — prob {need:.2f}<0.55", timestamp=ts, versions=versions, no_trade_reason="WEAK_SIGNAL", timeframe=tf)
        elif isinstance(prob, (int,float)):
            if prob < 0.55:
                return Decision(symbol=symbol, signal="NO_TRADE", probability=prob, regime=self._regime_str(ctx), entry=None, stop=None, tp1=None, tp2=None, risk_pct=None, rr=None, evidence=[], counter_evidence=[], reason=f"NO_TRADE: WEAK_SIGNAL — prob {prob:.2f}<0.55", timestamp=ts, versions=versions, no_trade_reason="WEAK_SIGNAL", timeframe=tf)

        # regime gate
        reg_str = self._regime_str(ctx)
        if reg_str == "UNCERTAIN" and isinstance(ensemble, dict) and int(ensemble.get("score",0)) < 60:
            return Decision(symbol=symbol, signal="NO_TRADE", probability=prob, regime=reg_str, entry=None, stop=None, tp1=None, tp2=None, risk_pct=None, rr=None, evidence=[], counter_evidence=[], reason="NO_TRADE: REGIME_UNCERTAIN", timestamp=ts, versions=versions, no_trade_reason="REGIME_UNCERTAIN", timeframe=tf)

        # derive levels
        entry = ctx.get("entry"); stop = ctx.get("stop"); tp1 = ctx.get("tp1"); tp2 = ctx.get("tp2")
        if entry is None:
            entry = feats.get("close") or (ctx.get("candles",[{}])[-1].get("close") if ctx.get("candles") else None)
        if stop is None and entry is not None:
            atr = feats.get("atr14") or feats.get("atr") or float(entry)*0.015
            try:
                a=float(atr); e=float(entry)
                stop = e-1.8*a if direction=="LONG" else e+1.8*a
            except: stop=None
        if tp1 is None and entry is not None and stop is not None:
            try:
                e=float(entry); s=float(stop); dist=abs(e-s)
                tp1 = e+dist*float(self.limits.min_rr) if direction=="LONG" else e-dist*float(self.limits.min_rr)
                tp2 = e+dist*float(self.limits.min_rr)*1.8 if direction=="LONG" else e-dist*float(self.limits.min_rr)*1.8
            except: pass
        rr_val = _rr(entry, stop, tp1)
        if rr_val < float(self.limits.min_rr)-1e-9:
            return Decision(symbol=symbol, signal="NO_TRADE", probability=prob, regime=reg_str, entry=entry, stop=stop, tp1=tp1, tp2=tp2, risk_pct=None, rr=rr_val, evidence=[], counter_evidence=[], reason=f"NO_TRADE: RR_INSUFFICIENT — RR {rr_val:.2f}<{self.limits.min_rr}", timestamp=ts, versions=versions, no_trade_reason="RR_INSUFFICIENT", timeframe=tf, data_ts=ctx.get("data_ts",ts))

        # risk — never bypass
        risk_ctx = dict(ctx)
        risk_ctx.update({"signal":direction,"entry":entry,"stop":stop,"tp1":tp1,"leverage":ctx.get("leverage",1.0),"risk_pct":ctx.get("risk_pct", ctx.get("risk_per_trade", self.limits.risk_per_trade)),"spread_pct":ctx.get("spread_pct", ctx.get("spread",0)),"volume":ctx.get("volume", ctx.get("vol",1)),"positions":ctx.get("positions", ctx.get("open_positions",0))})
        # map stale flag
        if ctx.get("stale"): risk_ctx["is_stale"]=True
        rrisk = self.risk.check(risk_ctx)
        if not rrisk.approved:
            veto = rrisk.veto or "RISK_REJECT"
            m={"NO_ILLIQUID":"LIQUIDITY_INSUFFICIENT","NO_STALE_DATA":"DATA_STALE","NO_REVENGE":"RISK_BUDGET_EXHAUSTED","NO_EXCESS_LEVERAGE":"RISK_REJECT","NO_INVALID_RR":"RR_INSUFFICIENT","NO_CRITICAL_FAILURE":"SYSTEM_FAILURE","NO_MARTINGALE":"RISK_REJECT","NO_AVERAGING":"RISK_REJECT","NO_RISK_OVERRIDE":"RISK_REJECT"}
            r = m.get(veto,"RISK_REJECT")
            return Decision(symbol=symbol, signal="NO_TRADE", probability=prob, regime=reg_str, entry=entry, stop=stop, tp1=tp1, tp2=tp2, risk_pct=rrisk.risk_pct, rr=rrisk.rr or rr_val, evidence=[], counter_evidence=[], reason=f"NO_TRADE: {r} — veto {veto}: {rrisk.reason}", timestamp=ts, versions=versions, no_trade_reason=r, timeframe=tf, data_ts=ctx.get("data_ts",ts))

        # volatility excessive
        try:
            atr = feats.get("atr14") or 0
            if entry and float(entry)!=0 and float(atr)/float(entry) > 0.06:
                return Decision(symbol=symbol, signal="NO_TRADE", probability=prob, regime=reg_str, entry=entry, stop=stop, tp1=tp1, tp2=tp2, risk_pct=rrisk.risk_pct, rr=rr_val, evidence=[], counter_evidence=[], reason="NO_TRADE: VOLATILITY_EXCESSIVE", timestamp=ts, versions=versions, no_trade_reason="VOLATILITY_EXCESSIVE", timeframe=tf)
        except: pass

        # approved
        ev = [f"ensemble {direction} score={ensemble.get('score',50)}" if isinstance(ensemble,dict) else f"signal {direction}"]
        ce = ensemble.get("contradicting",[]) if isinstance(ensemble,dict) else []
        return Decision(symbol=symbol, signal=direction, probability=prob, regime=reg_str, entry=float(entry) if entry is not None else None, stop=float(stop) if stop is not None else None, tp1=float(tp1) if tp1 is not None else None, tp2=float(tp2) if tp2 is not None else None, risk_pct=float(rrisk.risk_pct) if rrisk.risk_pct else ctx.get("risk_pct"), rr=float(rrisk.rr) if rrisk.rr else rr_val, evidence=ev, counter_evidence=ce, reason=f"VALID {direction} — score {ensemble.get('score',50) if isinstance(ensemble,dict) else 50} RR {rr_val:.2f}", timestamp=ts, versions=versions, position_size=rrisk.position_size, decision=direction, timeframe=tf, data_ts=ctx.get("data_ts",ts))

    def _regime_str(self, ctx):
        r=ctx.get("regime")
        if r is None: return "UNCERTAIN"
        if isinstance(r, str): return r
        if isinstance(r, dict): return r.get("regime","UNCERTAIN")
        return getattr(r,"regime","UNCERTAIN")
