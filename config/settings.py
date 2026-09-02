"""Single source of truth — loads settings.yaml + env overrides."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

RISK_PER_TRADE = 0.005
RISK_PER_TRADE_MIN = 0.0025
RISK_PER_TRADE_MAX = 0.0075
DAILY_LOSS_LIMIT = 0.02
MAX_POSITIONS = 3
MAX_POSITIONS_MIN = 1
MAX_POSITIONS_MAX = 3
MAX_LEVERAGE = 3.0
MIN_RR = 1.5
FEES_BPS = 0.0004
SLIPPAGE_BPS = 0.0005
STALE_THRESHOLD_S = 300
MAX_SPREAD_PCT = 0.005
MAX_SPREAD_BPS = 0.005

@dataclass
class Settings:
    symbols: list = field(default_factory=lambda: ["BTCUSDT","ETHUSDT","SOLUSDT"])
    timeframes: dict = field(default_factory=lambda: {"scalping":["4h","1h","15m","5m"],"swing":["1d","4h","1h","15m"]})
    timeframe_weights: dict = field(default_factory=lambda: {"4h":0.3,"1h":0.3,"15m":0.25,"5m":0.15})
    risk_per_trade: float = RISK_PER_TRADE
    daily_loss_limit: float = DAILY_LOSS_LIMIT
    max_positions: int = MAX_POSITIONS
    max_leverage: float = MAX_LEVERAGE
    min_rr: float = MIN_RR
    fee: float = FEES_BPS
    slippage: float = SLIPPAGE_BPS
    db_path: str = "storage/trading.db"
    binance_base: str = "https://api.binance.com"
    stale_multiplier: float = 2.0
    min_bars: int = 50
    # versioning
    feature_version: str = "0.1.0"
    strategy_version: str = "0.1.0"
    model_version: str = "0.1.0"
    prompt_version: str = "0.1.0"

_settings: Settings | None = None

def get_settings(reload: bool=False) -> Settings:
    global _settings
    if _settings is not None and not reload:
        return _settings
    s = Settings()
    # try yaml: check config/settings.yaml then project settings.yaml (parent)
    for p in [Path(__file__).parent/"settings.yaml", Path(__file__).parent.parent/"settings.yaml"]:
        if p.exists():
            try:
                import yaml  # optional
                d = yaml.safe_load(p.read_text())
                if d:
                    for k,v in d.items():
                        if hasattr(s,k):
                            setattr(s,k,v)
            except Exception:
                pass
            break
    # env overrides
    env_map={"RISK_PER_TRADE":"risk_per_trade","DAILY_LOSS_LIMIT":"daily_loss_limit","MAX_POSITIONS":"max_positions","MAX_LEVERAGE":"max_leverage","MIN_RR":"min_rr","FEE":"fee","SLIPPAGE":"slippage","DB_PATH":"db_path","BINANCE_BASE":"binance_base","SYMBOLS":"symbols","TIMEFRAMES":"timeframes"}
    for ek, attr in env_map.items():
        v=os.getenv(ek)
        if v is None or v=="": continue
        try:
            if attr in ("symbols","timeframes"):
                # comma-separated
                setattr(s, attr, [x.strip() for x in v.split(",") if x.strip()])
            elif attr in ("max_positions",):
                setattr(s, attr, int(float(v)))
            elif attr in ("risk_per_trade","daily_loss_limit","min_rr","fee","slippage","max_leverage"):
                setattr(s, attr, float(v))
            else:
                setattr(s, attr, v)
        except: pass
    _settings = s
    return s

def reset_settings():
    global _settings
    _settings=None
