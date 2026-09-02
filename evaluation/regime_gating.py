"""Regime-gated trend — train/val selection, test untouched."""
from __future__ import annotations
from strategies.base import StrategySignal
from strategies.trend import TrendStrategy
from evaluation.strategy_eval import evaluate_strategy

ALLOWED_TREND_REGIMES = {"TREND_BULL","TREND_BEAR"}

class RegimeGatedTrend(TrendStrategy):
    name = "trend_gated"
    def __init__(self, allowed=None):
        self.allowed = set(allowed) if allowed else ALLOWED_TREND_REGIMES
    def generate(self, market):
        reg = market.get("regime")
        label = reg if isinstance(reg, str) else getattr(reg, "regime", None) or market.get("regime")
        if label not in self.allowed:
            tf = market.get("timeframe","1h")
            return StrategySignal(self.name, "NEUTRAL", 0, tf, None, None, [f"regime {label} blocked"], [], "intraday")
        return super().generate(market)

def evaluate_gated_vs_base(candles, fee=0.0004, slippage=0.0005):
    base = evaluate_strategy(candles, TrendStrategy(), fee=fee, slippage=slippage)
    gated = evaluate_strategy(candles, RegimeGatedTrend(), fee=fee, slippage=slippage)
    return {"base": base["metrics"], "gated": gated["metrics"], "base_trades": base["trades"][:2], "gated_trades": gated["trades"][:2]}

def split_train_val_test(candles, train_ratio=0.6, val_ratio=0.2):
    n=len(candles)
    t=int(n*train_ratio); v=int(n*val_ratio)
    return candles[:t], candles[t:t+v], candles[t+v:]
