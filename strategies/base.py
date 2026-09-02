"""Strategy base. ponytail: single-file generics; split if >6 strategies."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass
class StrategySignal:
    strategy: str
    direction: str  # LONG|SHORT|NEUTRAL
    strength: float  # 0-1
    timeframe: str = "1h"
    entry: float | None = None
    invalidation: float | None = None
    evidence: list = field(default_factory=list)
    counter_evidence: list = field(default_factory=list)
    horizon: str = "swing"  # scalp|intraday|swing|position

class Strategy(ABC):
    name: str = "base"
    @abstractmethod
    def generate(self, market_state: dict) -> StrategySignal:
        ...
