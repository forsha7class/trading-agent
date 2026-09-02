from dataclasses import dataclass
try:
    from config.settings import (
        RISK_PER_TRADE, RISK_PER_TRADE_MIN, RISK_PER_TRADE_MAX,
        DAILY_LOSS_LIMIT, MAX_POSITIONS, MAX_LEVERAGE, MIN_RR,
        STALE_THRESHOLD_S, MAX_SPREAD_PCT,
    )
except ImportError:
    from trading_agent.config.settings import (  # fallback
        RISK_PER_TRADE, RISK_PER_TRADE_MIN, RISK_PER_TRADE_MAX,
        DAILY_LOSS_LIMIT, MAX_POSITIONS, MAX_LEVERAGE, MIN_RR,
        STALE_THRESHOLD_S, MAX_SPREAD_PCT,
    )

# Hard veto codes - exactly 9
VETO_NO_MARTINGALE = "NO_MARTINGALE"
VETO_NO_AVERAGING = "NO_AVERAGING"
VETO_NO_REVENGE = "NO_REVENGE"
VETO_NO_STALE_DATA = "NO_STALE_DATA"
VETO_NO_ILLIQUID = "NO_ILLIQUID"
VETO_NO_EXCESS_LEVERAGE = "NO_EXCESS_LEVERAGE"
VETO_NO_RISK_OVERRIDE = "NO_RISK_OVERRIDE"
VETO_NO_INVALID_RR = "NO_INVALID_RR"
VETO_NO_CRITICAL_FAILURE = "NO_CRITICAL_FAILURE"

HARD_RULES = [
    VETO_NO_MARTINGALE, VETO_NO_AVERAGING, VETO_NO_REVENGE,
    VETO_NO_STALE_DATA, VETO_NO_ILLIQUID, VETO_NO_EXCESS_LEVERAGE,
    VETO_NO_RISK_OVERRIDE, VETO_NO_INVALID_RR, VETO_NO_CRITICAL_FAILURE,
]

@dataclass
class RiskLimits:
    risk_per_trade: float = RISK_PER_TRADE
    risk_per_trade_min: float = RISK_PER_TRADE_MIN
    risk_per_trade_max: float = RISK_PER_TRADE_MAX
    daily_loss_limit: float = DAILY_LOSS_LIMIT
    max_positions: int = MAX_POSITIONS
    max_positions_min: int = 1
    max_positions_max: int = 3
    max_leverage: float = MAX_LEVERAGE
    min_rr: float = MIN_RR
    stale_threshold_s: float = STALE_THRESHOLD_S
    max_spread_pct: float = MAX_SPREAD_PCT
