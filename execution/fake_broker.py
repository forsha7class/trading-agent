"""Deterministic in-memory brokers — tests only, no network.

Mirrors the broker surface used by DemoEngine:
  market / capabilities                      (SPOT vs FUTURES, LONG/SHORT, leverage_max)
  validate(symbol, qty) -> {"ok": bool, "reason": ..., "quantity": floored}
  market_open(symbol, side, qty) -> order dict (FILLED at configurable price)
  market_close(symbol, side, qty) -> order dict
  order_status(order_id) -> order dict

FakeBroker is spot-shaped (LONG only, no leverage). FakeFuturesBroker is
futures-shaped: LONG and SHORT, configurable leverage, one-way positions.

Can simulate rejection (validate ok=False) and partial fills (fill_pct < 1).
The engine treats them exactly like the real brokers, so tests exercise the full
lifecycle without touching the exchange. NEVER import in production paths.
"""
from __future__ import annotations
import time

VALID_SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
SUPPORTED_BASE = {"BTC": 1e-5, "ETH": 1e-4, "SOL": 1e-2}  # min qty steps
FUTURES_STEP = {"BTCUSDT": 1e-4, "ETHUSDT": 1e-3, "SOLUSDT": 1e-2}
FUTURES_MIN_NOTIONAL = {"BTCUSDT": 50.0, "ETHUSDT": 20.0, "SOLUSDT": 5.0}


class FakeBroker:
    """Spot-shaped fake: LONG only, 1x, sells the held base to close."""

    market = "SPOT"
    capabilities = {"market": "SPOT", "long": True, "short": False, "leverage_max": 1}

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

    def market_open(self, symbol: str, side: str, qty: float) -> dict:
        v = self.validate(symbol, qty)
        if not v["ok"]:
            return {"status": "REJECTED", "reason": v["reason"], "symbol": symbol}
        if str(side).upper() != "LONG":
            return {"status": "REJECTED", "reason": "spot supports LONG/BUY only",
                    "symbol": symbol}
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

    def market_close(self, symbol: str, side: str, qty: float) -> dict:
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


class FakeFuturesBroker:
    """Futures-shaped fake: LONG+SHORT, configurable leverage (1x default, 2x max),
    one-way positions tracked by signed positionAmt. Mirrors FuturesDemoBroker."""

    market = "FUTURES"
    capabilities = {"market": "FUTURES", "long": True, "short": True,
                    "leverage_max": 2}

    def __init__(self, fill_price: float = 80000.0, fill_pct: float = 1.0,
                 reject_symbol: str | None = None, leverage: int = 1,
                 balances_usdt: float = 10000.0):
        self.fill_price = fill_price
        self.fill_pct = fill_pct
        self.reject_symbol = reject_symbol
        self.leverage = int(leverage)
        self.balances = {"USDT": balances_usdt}
        self.orders: dict[str, dict] = {}
        self.position_amt: dict[str, float] = {}   # signed: +long / -short
        self.entry_price: dict[str, float] = {}
        self.counter = 0
        self.last_price = fill_price

    def _next_id(self) -> str:
        self.counter += 1
        return f"fdemo{self.counter:06d}"

    def validate(self, symbol: str, qty: float) -> dict:
        symbol = (symbol or "").upper()
        if symbol not in VALID_SYMBOLS:
            return {"ok": False, "reason": "unknown symbol"}
        if symbol == self.reject_symbol:
            return {"ok": False, "reason": "simulated validation failure"}
        if qty is None or float(qty) <= 0:
            return {"ok": False, "reason": "invalid quantity"}
        step = FUTURES_STEP.get(symbol, 1e-4)
        if float(qty) < step:
            return {"ok": False, "reason": f"quantity below min step {step}"}
        px = self.fill_price
        qty_f = int(float(qty) / step + 1e-9) * step
        notional = qty_f * px
        if notional < FUTURES_MIN_NOTIONAL.get(symbol, 5):
            return {"ok": False,
                    "reason": f"notional {notional:.2f} < MIN_NOTIONAL {FUTURES_MIN_NOTIONAL.get(symbol, 5)}"}
        return {"ok": True, "reason": None, "quantity": round(qty_f, 10), "price": px}

    def market_open(self, symbol: str, side: str, qty: float) -> dict:
        v = self.validate(symbol, qty)
        if not v["ok"]:
            return {"status": "REJECTED", "reason": v["reason"], "symbol": symbol}
        side = str(side).upper()
        if side not in ("LONG", "SHORT"):
            return {"status": "REJECTED", "reason": "side must be LONG/SHORT", "symbol": symbol}
        filled = float(v.get("quantity", qty)) * self.fill_pct
        if filled <= 0:
            return {"status": "REJECTED", "reason": "zero fill", "symbol": symbol}
        oid = self._next_id()
        price = self.fill_price
        amt = filled if side == "LONG" else -filled
        self.position_amt[symbol] = self.position_amt.get(symbol, 0) + amt
        if abs(self.position_amt[symbol]) <= 1e-12:
            self.position_amt.pop(symbol, None)
        else:
            prev_amt = self.position_amt.get(symbol, 0) - amt
            if prev_amt == 0:
                self.entry_price[symbol] = price
        order = {"order_id": oid, "symbol": symbol,
                 "side": "BUY" if side == "LONG" else "SELL",
                 "type": "MARKET",
                 "status": "FILLED" if self.fill_pct >= 1 else "PARTIALLY_FILLED",
                 "executed_qty": filled, "orig_qty": filled,
                 "avg_price": price, "price": price, "commission": 0.0,
                 "ts": int(time.time() * 1000)}
        self.orders[oid] = order
        return order

    def market_close(self, symbol: str, side: str, qty: float) -> dict:
        """Close by mirroring the open side (LONG -> SELL, SHORT -> BUY)."""
        symbol = (symbol or "").upper()
        side = str(side).upper()
        if side not in ("LONG", "SHORT"):
            return {"status": "REJECTED", "reason": "side must be LONG/SHORT", "symbol": symbol}
        oid = self._next_id()
        price = self.fill_price
        amt = -abs(float(qty)) if side == "LONG" else abs(float(qty))
        cur = self.position_amt.get(symbol, 0)
        # reduce toward zero; error if it would flip the position (mirror mismatch)
        new_amt = cur + amt
        if abs(new_amt) > abs(cur) + 1e-12:
            return {"status": "REJECTED", "reason": "close would flip position",
                    "symbol": symbol}
        order = {"order_id": oid, "symbol": symbol,
                 "side": "SELL" if side == "LONG" else "BUY",
                 "type": "MARKET", "status": "FILLED", "executed_qty": float(qty),
                 "orig_qty": float(qty), "avg_price": price, "price": price,
                 "commission": 0.0, "ts": int(time.time() * 1000)}
        self.orders[oid] = order
        if abs(new_amt) <= 1e-12:
            self.position_amt.pop(symbol, None)
            self.entry_price.pop(symbol, None)
        else:
            self.position_amt[symbol] = new_amt
        return order

    def order_status(self, order_id: str) -> dict:
        return dict(self.orders.get(order_id, {"status": "UNKNOWN", "order_id": order_id}))

    def account(self) -> dict:
        return {"assets": [{"asset": "USDT", "walletBalance": self.balances["USDT"],
                            "availableBalance": self.balances["USDT"],
                            "marginBalance": self.balances["USDT"]}]}
