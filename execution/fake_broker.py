"""Deterministic in-memory Binance Spot Testnet broker — tests only, no network.

Mirrors the DemoBroker surface used by DemoEngine:
  validate(symbol, qty) -> {"ok": bool, "reason": ...}
  market_buy(symbol, qty) -> order dict (FILLED at configurable price)
  market_sell(symbol, qty) -> order dict
  order_status(order_id) -> order dict

Can simulate rejection (validate ok=False) and partial fills (fill_pct < 1).
The engine treats it exactly like the real broker, so tests exercise the full
lifecycle without touching the exchange. NEVER import in production paths.
"""
from __future__ import annotations
import time

VALID_SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
SUPPORTED_BASE = {"BTC": 1e-5, "ETH": 1e-4, "SOL": 1e-2}  # min qty steps


class FakeBroker:
    def __init__(self, fill_price: float = 80000.0, fill_pct: float = 1.0,
                 reject_symbol: str | None = None, balances: dict | None = None):
        self.fill_price = fill_price
        self.fill_pct = fill_pct
        self.reject_symbol = reject_symbol
        self.balances = dict(balances or {"BTC": 1.0, "USDT": 10000.0})
        self.orders: dict[str, dict] = {}
        self.counter = 0
        self.last_price = fill_price

    def _next_id(self) -> str:
        self.counter += 1
        return f"demo{self.counter:06d}"

    def validate(self, symbol: str, qty: float) -> dict:
        symbol = (symbol or "").upper()
        if symbol not in VALID_SYMBOLS:
            return {"ok": False, "reason": "unknown symbol"}
        if symbol == self.reject_symbol:
            return {"ok": False, "reason": "simulated validation failure"}
        if qty is None or float(qty) <= 0:
            return {"ok": False, "reason": "invalid quantity"}
        base = symbol.replace("USDT", "")
        step = SUPPORTED_BASE.get(base, 1e-6)
        if float(qty) < step:
            return {"ok": False, "reason": f"quantity below min step {step}"}
        return {"ok": True, "reason": None}

    def market_buy(self, symbol: str, qty: float) -> dict:
        v = self.validate(symbol, qty)
        if not v["ok"]:
            return {"status": "REJECTED", "reason": v["reason"], "symbol": symbol}
        filled = float(qty) * self.fill_pct
        oid = self._next_id()
        price = self.fill_price
        order = {"order_id": oid, "symbol": symbol, "side": "BUY",
                 "type": "MARKET",
                 "status": "FILLED" if self.fill_pct >= 1 else "PARTIALLY_FILLED",
                 "executed_qty": filled, "orig_qty": float(qty),
                 "avg_price": price, "price": price, "commission": 0.0,
                 "ts": int(time.time() * 1000)}
        self.orders[oid] = order
        base = symbol.replace("USDT", "")
        self.balances[base] = self.balances.get(base, 0) + filled
        self.balances["USDT"] = self.balances.get("USDT", 10000) - filled * price
        return order

    def market_sell(self, symbol: str, qty: float) -> dict:
        oid = self._next_id()
        price = self.fill_price
        order = {"order_id": oid, "symbol": symbol, "side": "SELL",
                 "type": "MARKET", "status": "FILLED", "executed_qty": float(qty),
                 "orig_qty": float(qty), "avg_price": price, "price": price,
                 "commission": 0.0, "ts": int(time.time() * 1000)}
        self.orders[oid] = order
        base = symbol.replace("USDT", "")
        self.balances[base] = max(0, self.balances.get(base, 0) - float(qty))
        self.balances["USDT"] = self.balances.get("USDT", 10000) + float(qty) * price
        return order

    def order_status(self, order_id: str) -> dict:
        return dict(self.orders.get(order_id, {"status": "UNKNOWN", "order_id": order_id}))

    def account(self) -> dict:
        return {"balances": [{"asset": k, "free": v, "locked": 0}
                             for k, v in self.balances.items()]}
