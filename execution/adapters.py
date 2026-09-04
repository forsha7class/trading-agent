"""Execution adapters — unified interface for PAPER / DEMO / LIVE (task §2).

  ExecutionAdapter (base): place_order / get_order_status / cancel_order /
    get_position / close_position / reconcile — deterministic statuses, never
    assumes request success == fill (task §11).

  PaperExecution: thin wrapper over the existing PaperEngine/PaperPortfolio so
    the PAPER path is unchanged but exposed through one interface. No real I/O.

  DemoExecution: Binance Spot Testnet lifecycle. The only environment that may
    touch an exchange, and only when execution/env.demo_env_status() is green.
    Order placement is additionally gated by DemoEngine (eligibility + dup +
    capacity). This class itself performs signed REST calls — callers MUST pass
    through the env gate first.

  LiveExecution: interface only. Every method returns LIVE_EXECUTION_DISABLED
    and raises nothing; there is deliberately no order implementation (task §6).

Spot constraint: Binance SPOT testnet supports LONG (BUY) entries only; SHORT
is not executable on spot — the DEMO engine rejects SHORT candidates for spot
execution (position/close logic is directional for the exit-side accounting,
but no spot SHORT open order is ever placed).
"""
from __future__ import annotations
import time
from .env import (MODE_PAPER, MODE_DEMO, MODE_LIVE, demo_env_status,
                  require_demo_env, TESTNET_BASE)

DISABLED_STATE = "LIVE_EXECUTION_DISABLED"

# ---- deterministic status vocabulary (task §11) ----------------------------
ST_NEW = "NEW"
ST_PENDING = "PENDING"          # request sent, fill not confirmed
ST_OPEN = "OPEN"                # fill confirmed (position open)
ST_FILLED = "FILLED"
ST_PARTIALLY_FILLED = "PARTIALLY_FILLED"
ST_CANCELED = "CANCELED"
ST_REJECTED = "REJECTED"
ST_EXPIRED = "EXPIRED"
ST_CLOSED = "CLOSED"
ST_UNKNOWN = "UNKNOWN"


class ExecutionAdapter:
    """Base class: contract + shared status normalization. No real behavior."""

    mode: str = "ABSTRACT"

    # ---- placeholders: subclasses implement ----
    def place_order(self, order: dict) -> dict:
        raise NotImplementedError

    def get_order_status(self, order_id: str) -> dict:
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> dict:
        raise NotImplementedError

    def get_position(self, symbol: str) -> dict | None:
        raise NotImplementedError

    def close_position(self, position: dict) -> dict:
        raise NotImplementedError

    def reconcile(self) -> dict:
        raise NotImplementedError

    @staticmethod
    def _norm_status(raw: str | None, side: str | None = None) -> str:
        """Map broker status strings onto the deterministic vocabulary."""
        s = (raw or "").upper().replace(" ", "_")
        if s in ("NEW", "PENDING_NEW", "PENDING"):
            return ST_NEW if side else ST_PENDING
        if s == "PARTIALLY_FILLED":
            return ST_PARTIALLY_FILLED
        if s in ("FILLED", "OPEN", "IN_TRADE"):
            return ST_FILLED
        if s == "CANCELED":
            return ST_CANCELED
        if s in ("REJECTED", "EXPIRED", "PENDING_CANCEL"):
            return ST_REJECTED if s == "REJECTED" else ST_EXPIRED
        if s == "CLOSED":
            return ST_CLOSED
        return ST_UNKNOWN


class PaperExecution(ExecutionAdapter):
    """PAPER path — thin adapter over the untouched PaperEngine. No real orders."""

    mode = MODE_PAPER

    def __init__(self, engine=None):
        if engine is None:
            from portfolio.paper_engine import PaperEngine
            engine = PaperEngine(equity=10000)
        self.engine = engine

    def place_order(self, order: dict) -> dict:
        # PAPER order lifecycle is driven by the existing PaperEngine.tick() +
        # PaperPortfolio (SL/TP/TIME_EXIT). This adapter maps an order request to
        # the engine decision tick so the PAPER behavior is unchanged.
        res = self.engine.tick(
            order.get("candles") or [],
            symbol=order.get("symbol", "BTCUSDT"),
            timeframe=order.get("timeframe", "1h"),
        )
        return {"order_id": res.get("order_id"), "position": res.get("position"),
                "status": ST_OPEN if res.get("position") else ST_NEW,
                "decision_id": res.get("decision_id")}

    def get_order_status(self, order_id: str) -> dict:
        return {"order_id": order_id, "status": ST_UNKNOWN, "mode": self.mode}

    def cancel_order(self, order_id: str) -> dict:
        return {"order_id": order_id, "status": ST_CANCELED, "mode": self.mode}

    def get_position(self, symbol: str) -> dict | None:
        for p in self.engine.portfolio.positions:
            if p.get("symbol") == symbol and p.get("status") == "OPEN":
                return dict(p)
        return None

    def close_position(self, position: dict) -> dict:
        return {"status": ST_CLOSED, "mode": self.mode, "position": position}

    def reconcile(self) -> dict:
        return {"mode": self.mode, "open": len(self.engine.portfolio.open_positions)}


class DemoExecution(ExecutionAdapter):
    """Binance Spot Testnet execution. Requires a green demo env gate."""

    mode = MODE_DEMO

    def __init__(self, broker=None):
        if broker is None:
            from execution.demo_broker import DemoBroker
            broker = DemoBroker()
        self.broker = broker
        self._env = demo_env_status()

    def _gate(self) -> None:
        st = demo_env_status()
        if not st["demo_ready"]:
            raise RuntimeError("DEMO environment not ready: " + "; ".join(st["reasons"] or ["unknown"]))
        self._env = st

    # ---- order lifecycle (spot) ----
    def place_order(self, order: dict) -> dict:
        """Place a spot market BUY (LONG) only. Raises unless demo env is green."""
        self._gate()
        side = str(order.get("side") or order.get("decision") or "").upper()
        if side != "LONG":
            return {"status": ST_REJECTED, "reason": "spot supports LONG/BUY only",
                    "mode": self.mode}
        symbol = str(order.get("symbol") or "").upper()
        qty = order.get("quantity")
        if not symbol or qty is None or float(qty) <= 0:
            return {"status": ST_REJECTED, "reason": "invalid symbol/quantity",
                    "mode": self.mode}
        return self.broker.market_buy(symbol, float(qty))

    def get_order_status(self, order_id: str) -> dict:
        self._gate()
        return self.broker.order_status(order_id)

    def cancel_order(self, order_id: str) -> dict:
        self._gate()
        return self.broker.cancel(order_id)

    def get_position(self, symbol: str) -> dict | None:
        self._gate()
        return self.broker.asset_balance(symbol)

    def close_position(self, position: dict) -> dict:
        """Close a spot position by selling the base asset at market."""
        self._gate()
        return self.broker.market_sell(str(position.get("symbol") or "").upper(),
                                       float(position.get("free") or position.get("quantity") or 0))

    def reconcile(self) -> dict:
        self._gate()
        return self.broker.account_snapshot()


class LiveExecution(ExecutionAdapter):
    """Interface only — deliberately disabled. No order implementation exists."""

    mode = MODE_LIVE

    @staticmethod
    def _disabled() -> dict:
        return {"status": DISABLED_STATE, "mode": MODE_LIVE}

    def place_order(self, order: dict) -> dict:
        return self._disabled()

    def get_order_status(self, order_id: str) -> dict:
        return self._disabled()

    def cancel_order(self, order_id: str) -> dict:
        return self._disabled()

    def get_position(self, symbol: str) -> dict | None:
        return self._disabled()

    def close_position(self, position: dict) -> dict:
        return self._disabled()

    def reconcile(self) -> dict:
        return self._disabled()


def get_adapter(mode: str | None = None) -> ExecutionAdapter:
    """Deterministic factory. LIVE -> disabled LiveExecution. DEMO requires the
    env gate to be green at construction, else raises (fail-closed)."""
    mode = (mode or demo_env_status()["mode"] or MODE_PAPER).upper()
    if mode == MODE_LIVE:
        return LiveExecution()
    if mode == MODE_DEMO:
        require_demo_env()          # raises unless creds+testnet endpoint present
        return DemoExecution()
    return PaperExecution()
