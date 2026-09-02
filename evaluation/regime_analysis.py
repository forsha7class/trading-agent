"""Regime-conditional performance."""
from evaluation.strategy_eval import evaluate_strategy
from strategies.trend import TrendStrategy
from strategies.momentum import MomentumStrategy
from strategies.breakout import BreakoutStrategy
from strategies.mean_reversion import MeanReversionStrategy

def regime_report(candles:list[dict])->dict:
    out={}
    for cls in [TrendStrategy, MomentumStrategy, BreakoutStrategy, MeanReversionStrategy]:
        r=evaluate_strategy(candles, cls())
        # r['metrics']['by_regime'] already computed
        out[cls().name]=r["metrics"]["by_regime"]
    # aggregate which regime hurts
    # also compute regime filtering: what if skip UNCERTAIN/HIGH_VOL?
    return out
