from dataclasses import dataclass
import time
from .limits import RiskLimits, HARD_RULES, VETO_NO_MARTINGALE, VETO_NO_AVERAGING, VETO_NO_REVENGE, VETO_NO_STALE_DATA, VETO_NO_ILLIQUID, VETO_NO_EXCESS_LEVERAGE, VETO_NO_RISK_OVERRIDE, VETO_NO_INVALID_RR, VETO_NO_CRITICAL_FAILURE
from .position_sizing import position_size

@dataclass
class RiskResult:
    approved: bool
    reason: str
    position_size: float | None
    risk_pct: float | None
    rr: float | None
    veto: str | None

class RiskEngine:
    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()

    def check(self, ctx: dict) -> RiskResult:
        try:
            return self._check(ctx)
        except Exception as e:
            return RiskResult(False, f"CRITICAL_FAILURE: {e}", None, None, None, VETO_NO_CRITICAL_FAILURE)

    def _check(self, ctx: dict) -> RiskResult:
        # --- extract ---
        equity = ctx.get("equity")
        if equity is None or equity <= 0:
            return RiskResult(False, "missing equity", None, None, None, VETO_NO_CRITICAL_FAILURE)
        entry = ctx.get("entry")
        stop = ctx.get("stop")
        tp1 = ctx.get("tp1")
        leverage = ctx.get("leverage", 1.0) or 1.0
        risk_pct = ctx.get("risk_pct", self.limits.risk_per_trade)
        # critical missing fields
        if entry is None or stop is None:
            # if signal is NO_TRADE, not a failure but invalid RR
            if ctx.get("signal") == "NO_TRADE":
                return RiskResult(False, "NO_TRADE has no entry/stop", None, None, None, VETO_NO_INVALID_RR)
            return RiskResult(False, "missing entry/stop", None, None, None, VETO_NO_CRITICAL_FAILURE)

        stop_distance = abs(float(entry) - float(stop))
        tp_distance = abs(float(tp1) - float(entry)) if tp1 is not None else 0
        rr = (tp_distance / stop_distance) if stop_distance > 0 else 0

        # --- 9 hard vetoes ---
        # 1 NO_MARTINGALE
        if ctx.get("is_martingale"):
            return RiskResult(False, "martingale detected", None, risk_pct, rr, VETO_NO_MARTINGALE)
        # 2 NO_AVERAGING
        if ctx.get("is_averaging"):
            return RiskResult(False, "averaging down detected", None, risk_pct, rr, VETO_NO_AVERAGING)
        # 3 NO_REVENGE (daily loss)
        daily_pnl = ctx.get("daily_pnl", 0) or 0
        # daily_pnl negative means loss
        if daily_pnl <= - self.limits.daily_loss_limit * float(equity):
            return RiskResult(False, f"daily loss limit hit {daily_pnl}", None, risk_pct, rr, VETO_NO_REVENGE)
        # also explicit daily_loss_pct
        dlp = ctx.get("daily_loss_pct")
        if dlp is not None and dlp <= -self.limits.daily_loss_limit:
            return RiskResult(False, "daily loss pct exceeded", None, risk_pct, rr, VETO_NO_REVENGE)
        # 4 NO_STALE_DATA
        age = ctx.get("data_age_s")
        if age is None and ctx.get("data_ts") is not None:
            age = time.time() - float(ctx["data_ts"]) / 1000 if ctx["data_ts"] > 1e10 else time.time() - float(ctx["data_ts"])
        if age is not None and age > self.limits.stale_threshold_s:
            return RiskResult(False, f"stale data {age:.0f}s", None, risk_pct, rr, VETO_NO_STALE_DATA)
        if ctx.get("is_stale"):
            return RiskResult(False, "stale flag", None, risk_pct, rr, VETO_NO_STALE_DATA)
        # 5 NO_ILLIQUID
        spread = ctx.get("spread_pct", ctx.get("spread", 0)) or 0
        volume = ctx.get("volume", ctx.get("vol", 1)) or 0
        if spread > self.limits.max_spread_pct:
            return RiskResult(False, f"spread too wide {spread}", None, risk_pct, rr, VETO_NO_ILLIQUID)
        # vol zero with spread check already, but explicit illiquid flag
        if ctx.get("is_illiquid"):
            return RiskResult(False, "illiquid flag", None, risk_pct, rr, VETO_NO_ILLIQUID)
        if volume is not None and volume <= 0 and spread > 0:
            return RiskResult(False, "no volume", None, risk_pct, rr, VETO_NO_ILLIQUID)
        # 6 NO_EXCESS_LEVERAGE
        if leverage > self.limits.max_leverage:
            return RiskResult(False, f"leverage {leverage} > {self.limits.max_leverage}", None, risk_pct, rr, VETO_NO_EXCESS_LEVERAGE)
        # 7 NO_RISK_OVERRIDE
        if risk_pct is not None:
            if risk_pct > self.limits.risk_per_trade_max + 1e-9 or risk_pct < self.limits.risk_per_trade_min - 1e-9:
                # allow NO_TRADE with 0 risk
                if not (ctx.get("signal") == "NO_TRADE" and risk_pct == 0):
                    return RiskResult(False, f"risk_pct {risk_pct} out of bounds [{self.limits.risk_per_trade_min},{self.limits.risk_per_trade_max}]", None, risk_pct, rr, VETO_NO_RISK_OVERRIDE)
            # also check allowed_risk_capital vs equity
            if risk_pct > 0 and risk_pct * float(equity) > float(equity) * self.limits.risk_per_trade_max + 1e-9:
                return RiskResult(False, "risk override capital", None, risk_pct, rr, VETO_NO_RISK_OVERRIDE)
        # 8 NO_INVALID_RR
        if stop_distance <= 0:
            return RiskResult(False, "invalid stop distance", None, risk_pct, rr, VETO_NO_INVALID_RR)
        if rr < self.limits.min_rr:
            return RiskResult(False, f"RR {rr:.2f} < {self.limits.min_rr}", None, risk_pct, rr, VETO_NO_INVALID_RR)
        # also invalid entry/tp direction: for LONG tp>entry, SHORT tp<entry — check if signal known
        sig = ctx.get("signal")
        if sig == "LONG" and tp1 is not None and float(tp1) <= float(entry):
            return RiskResult(False, "LONG tp <= entry", None, risk_pct, rr, VETO_NO_INVALID_RR)
        if sig == "SHORT" and tp1 is not None and float(tp1) >= float(entry):
            return RiskResult(False, "SHORT tp >= entry", None, risk_pct, rr, VETO_NO_INVALID_RR)

        # 9 NO_CRITICAL_FAILURE handled in outer try; also explicit flag
        if ctx.get("critical_failure"):
            return RiskResult(False, "critical failure flag", None, risk_pct, rr, VETO_NO_CRITICAL_FAILURE)

        # concentration / max positions (maps to NO_RISK_OVERRIDE or NO_ILLIQUID; use NO_RISK_OVERRIDE for exposure)
        positions = ctx.get("positions", ctx.get("open_positions", []))
        if isinstance(positions, int):
            npos = positions
        elif isinstance(positions, list):
            npos = len(positions)
        else:
            npos = 0
        if npos >= self.limits.max_positions:
            return RiskResult(False, f"max positions {npos} >= {self.limits.max_positions}", None, risk_pct, rr, VETO_NO_RISK_OVERRIDE)

        # passed all vetoes -> compute sizing
        allowed_risk_capital = float(equity) * float(risk_pct) if risk_pct else float(equity) * self.limits.risk_per_trade
        liq = {"spread_pct": spread, "vol_ratio": 1.0}
        ps = position_size(allowed_risk_capital, stop_distance, leverage, liq)
        if ps is None:
            return RiskResult(False, "position sizing failed", None, risk_pct, rr, VETO_NO_CRITICAL_FAILURE)
        return RiskResult(True, "approved", float(ps["size"]), float(risk_pct), float(rr), None)
