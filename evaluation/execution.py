"""Realistic vs ideal execution model."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class ExecutionConfig:
    fee: float = 0.0004
    slippage: float = 0.0005
    spread: float = 0.0005
    mode: str = "realistic"  # realistic | ideal
    def effective_slippage(self)->float:
        return 0.0 if self.mode=="ideal" else self.slippage
    def effective_fee(self)->float:
        return 0.0 if self.mode=="ideal" else self.fee

REALISTIC=ExecutionConfig(mode="realistic")
IDEAL=ExecutionConfig(fee=0.0, slippage=0.0, spread=0.0, mode="ideal")
