from __future__ import annotations
import json, time
from dataclasses import dataclass, asdict, field

def _now_ms() -> int:
    return int(time.time()*1000)

@dataclass
class Candle:
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_time: int
    close_time: int
    def to_dict(self)->dict: return asdict(self)
    @classmethod
    def from_dict(cls,d:dict)->"Candle": return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})

@dataclass
class StrategySignal:
    symbol: str
    ts: int
    strategy: str
    direction: str  # LONG/SHORT/FLAT
    strength: float
    entry: float | None = None
    invalidation: float | None = None
    evidence: dict = field(default_factory=dict)
    version: str = "v1"
    def to_dict(self)->dict: return asdict(self)
    @classmethod
    def from_dict(cls,d:dict)->"StrategySignal": return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})

@dataclass
class RegimeResult:
    symbol: str
    timeframe: str
    ts: int
    regime: str  # TREND_BULL/BEAR/RANGE/HIGH_VOL/LOW_VOL/UNCERTAIN
    confidence: float
    evidence: dict = field(default_factory=dict)
    version: str = "v1"
    def to_dict(self)->dict: return asdict(self)
    @classmethod
    def from_dict(cls,d:dict)->"RegimeResult": return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})

@dataclass
class Decision:
    ts: int
    symbol: str
    timeframe: str
    regime: str | None = None
    signal: str | None = None
    probability: dict = field(default_factory=dict)
    entry: float | None = None
    stop: float | None = None
    tp1: float | None = None
    tp2: float | None = None
    position_size: float | None = None
    risk_pct: float | None = None
    rr: float | None = None
    evidence: dict = field(default_factory=dict)
    counter_evidence: dict = field(default_factory=dict)
    reason: str = ""
    decision: str = "NO_TRADE"  # LONG/SHORT/NO_TRADE
    versions: dict = field(default_factory=dict)
    data_ts: int | None = None
    id: int | None = None
    def to_dict(self)->dict: return asdict(self)
    @classmethod
    def from_dict(cls,d:dict)->"Decision": return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})

@dataclass
class PaperTrade:
    decision_id: int | None
    symbol: str
    side: str
    entry: float
    stop: float | None = None
    tp1: float | None = None
    size: float | None = None
    status: str = "OPEN"
    pnl: float | None = None
    fees: float | None = None
    opened_at: int = field(default_factory=_now_ms)
    closed_at: int | None = None
    id: int | None = None
    def to_dict(self)->dict: return asdict(self)
    @classmethod
    def from_dict(cls,d:dict)->"PaperTrade": return cls(**{k:d[k] for k in cls.__dataclass_fields__ if k in d})

@dataclass
class ValidationResult:
    valid: bool
    reason: str = ""
    details: dict = field(default_factory=dict)
    def to_dict(self)->dict: return asdict(self)

@dataclass
class Features:
    symbol: str = ""
    timeframe: str = ""
    ts: int = 0
    ema20: float | None = None
    ema50: float | None = None
    sma20: float | None = None
    rsi14: float | None = None
    atr14: float | None = None
    momentum: float | None = None
    vol: float | None = None
    returns: float | None = None
    volume_anomaly: float | None = None
    def to_dict(self)->dict: return asdict(self)
