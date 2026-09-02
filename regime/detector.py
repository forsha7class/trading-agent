"""Regime detector — pure function, no IO. ponytail: thresholds fixed; upgrade to adaptive/ML later."""
from dataclasses import dataclass, field
import math

REGIME_VERSION = "0.1.0"
REGIMES = ("TREND_BULL", "TREND_BEAR", "RANGE", "HIGH_VOL", "LOW_VOL", "UNCERTAIN")

@dataclass
class RegimeResult:
    regime: str
    confidence: float
    evidence: list = field(default_factory=list)
    transition: dict = field(default_factory=dict)
    version: str = REGIME_VERSION

def _f(d, k, default=None):
    v = d.get(k, default) if isinstance(d, dict) else default
    return v

def detect_regime(features: dict, candles=None) -> RegimeResult:
    if not isinstance(features, dict) or not features:
        return RegimeResult("UNCERTAIN", 0.0, ["insufficient data: empty features"], {"prob_stay": 0.0}, REGIME_VERSION)
    # required keys
    need = ["ema20", "ema50", "atr14", "rsi14"]
    missing = [k for k in need if features.get(k) is None]
    n_candles = len(candles) if isinstance(candles, (list, tuple)) else 0
    # also need close price
    close = _f(features, "close", _f(features, "price", None))
    if close is None and n_candles:
        try:
            last = candles[-1]
            close = last.get("close", last.get("c")) if isinstance(last, dict) else last[4] if len(last) > 4 else None
        except Exception:
            close = None
    if missing or close is None or n_candles and n_candles < 20:
        # allow if features alone sufficient (>=20 bars implied) — check still
        if close is None or missing:
            return RegimeResult("UNCERTAIN", 0.1, [f"missing: {missing}" if missing else "no close"], {"prob_stay": 0.5}, REGIME_VERSION)

    ema20 = features.get("ema20")
    ema50 = features.get("ema50")
    atr = features.get("atr14", features.get("atr"))
    rsi = features.get("rsi14", features.get("rsi"))
    sma20 = features.get("sma20", ema20)
    momentum = features.get("momentum", 0) or 0
    vol = features.get("vol", None)

    evidence = []
    # atr pct as volatility proxy
    atr_pct = None
    if atr is not None and close:
        try:
            atr_pct = float(atr) / float(close) if float(close) != 0 else None
        except Exception:
            atr_pct = None
    if atr_pct is None and vol is not None:
        atr_pct = float(vol)
    if atr_pct is None:
        atr_pct = 0.015

    # ADX proxy: ema separation normalized by price/atr
    sep = 0.0
    sep_atr = 0.0
    if ema20 is not None and ema50 is not None and close:
        try:
            sep = abs(float(ema20) - float(ema50)) / float(close)
            sep_atr = abs(float(ema20) - float(ema50)) / float(atr) if atr and float(atr) != 0 else sep * 100
        except Exception:
            pass

    adx_proxy = min(100, sep_atr * 15 + abs(float(momentum or 0)) * 500) if sep_atr else 0
    trending = sep > 0.008 and adx_proxy > 20

    # volatility regime (highest priority if extreme)
    if atr_pct > 0.035:
        ev = f"high vol atr_pct={atr_pct:.3%}"
        evidence.append(ev)
        # if also strong trend, still HIGH_VOL per spec
        conf = min(0.95, 0.55 + (atr_pct - 0.035) * 10 + (0.15 if trending else 0))
        return RegimeResult("HIGH_VOL", round(float(conf), 3), evidence, {"prob_stay": 0.6, "likely_next": "RANGE"}, REGIME_VERSION)
    if atr_pct < 0.008:
        evidence.append(f"low vol atr_pct={atr_pct:.3%}")
        conf = min(0.9, 0.55 + (0.008 - atr_pct) * 20)
        return RegimeResult("LOW_VOL", round(float(conf), 3), evidence, {"prob_stay": 0.65, "likely_next": "RANGE"}, REGIME_VERSION)

    # trend vs range
    bull = False
    bear = False
    if ema20 is not None and ema50 is not None and close is not None:
        try:
            bull = float(ema20) > float(ema50) and float(close) > float(ema20)
            bear = float(ema20) < float(ema50) and float(close) < float(ema20)
        except Exception:
            pass

    if trending and bull and (momentum is None or float(momentum) >= 0):
        evidence.append(f"bull trend ema20>ema50 sep={sep:.3%} adx~{adx_proxy:.0f}")
        if rsi is not None:
            evidence.append(f"rsi={float(rsi):.1f}")
        conf = min(0.92, 0.55 + sep * 20 + max(0, float(momentum or 0)) * 5)
        return RegimeResult("TREND_BULL", round(float(conf), 3), evidence, {"prob_stay": 0.7, "likely_next": "RANGE"}, REGIME_VERSION)
    if trending and bear and (momentum is None or float(momentum) <= 0):
        evidence.append(f"bear trend ema20<ema50 sep={sep:.3%} adx~{adx_proxy:.0f}")
        if rsi is not None:
            evidence.append(f"rsi={float(rsi):.1f}")
        conf = min(0.92, 0.55 + sep * 20 + max(0, -float(momentum or 0)) * 5)
        return RegimeResult("TREND_BEAR", round(float(conf), 3), evidence, {"prob_stay": 0.7, "likely_next": "RANGE"}, REGIME_VERSION)

    # default range
    evidence.append(f"range sep={sep:.3%} atr_pct={atr_pct:.3%} adx~{adx_proxy:.0f}")
    if rsi is not None:
        evidence.append(f"rsi={float(rsi):.1f}")
    # confidence higher when clearly not trending and vol mid
    conf = 0.55 + (0.15 if not trending else 0) + (0.1 if 0.01 < atr_pct < 0.03 else 0)
    return RegimeResult("RANGE", round(float(min(0.88, conf)), 3), evidence, {"prob_stay": 0.6, "likely_next": "RANGE"}, REGIME_VERSION)
