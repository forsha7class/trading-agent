"""Binance USDT-M FUTURES DEMO TRADING REST client — signed, secret-safe, LONG+SHORT.

Base defaults to the OFFICIAL Binance Futures Demo endpoint
(https://demo-fapi.binance.com, the demo.binance.com portal). The legacy
futures TESTNET (https://testnet.binancefuture.com — decommissioned by Binance)
is reachable ONLY under the explicit FUTURES_DEMO_LEGACY=1 opt-in enforced by
execution/env. Credentials come from the environment
(BINANCE_FUTURES_DEMO_API_KEY / BINANCE_FUTURES_DEMO_API_SECRET) and are NEVER
printed, logged, persisted, or sent anywhere but the signed request. Spot and
futures demo credentials are intentionally separate (§9) — this module never
reads the spot BINANCE_DEMO_* vars and has no spot route.

No mainnet route exists in this module. Signed calls use HMAC-SHA256 +
X-MBX-APIKEY against the USDT-M futures API (/fapi/*). Callers MUST pass the
demo env gate (execution/env.demo_env_status) before using this broker.

Position model: ONE-WAY mode assumed (verified before the first smoke order;
the broker exposes get_position_mode() so the engine/operator can check).
Market orders open LONG (BUY) or SHORT (SELL); closing reduces the position by
the same side it was opened (exactly mirrors the futures position held).
"""
from __future__ import annotations
import os, time, hmac, hashlib, urllib.parse
import httpx

from .env import (FUTURES_DEMO_BASE, FUTURES_TESTNET_BASE, FUTURES_MAINNET_BASE,
                  ENV_FUTURES_KEY, ENV_FUTURES_SECRET, demo_env_status)

_TIMEOUT = 15.0

# One-way position mode ("dual" hedging would change open/close semantics).
MODE_ONE_WAY = "one-way"
MODE_DUAL = "dual"


class FuturesDemoBrokerError(RuntimeError):
    pass


class FuturesDemoBroker:
    """Signed USDT-M futures demo client. Raises unless the FUTURES demo env
    gate is green (TRADING_MODE=DEMO + DEMO_KIND=FUTURES + futures demo creds +
    confirmed futures demo/testnet endpoint)."""

    def __init__(self, base: str | None = None, key: str | None = None,
                 secret: str | None = None):
        st = demo_env_status()
        if not st["demo_ready"]:
            raise FuturesDemoBrokerError(
                "futures demo environment not ready: " + "; ".join(st["reasons"] or []))
        self.base = (base or st["endpoint"] or FUTURES_DEMO_BASE).rstrip("/")
        # Only the official demo base or (legacy opt-in) the testnet base is
        # accepted; mainnet and anything else is refused.
        if self.base not in (FUTURES_DEMO_BASE, FUTURES_TESTNET_BASE):
            raise FuturesDemoBrokerError(
                f"refusing futures base {self.base} — only the official demo "
                f"({FUTURES_DEMO_BASE}) or the legacy testnet "
                f"({FUTURES_TESTNET_BASE}) are accepted; mainnet "
                f"({FUTURES_MAINNET_BASE}) is never accepted)")
        if self.base == FUTURES_TESTNET_BASE:
            from .env import futures_target, TARGET_FUTURES_TESTNET
            if futures_target() != TARGET_FUTURES_TESTNET:
                raise FuturesDemoBrokerError(
                    "legacy futures testnet requires FUTURES_DEMO_LEGACY=1")
        self.key = key or os.getenv(ENV_FUTURES_KEY, "").strip()
        self.secret = secret or os.getenv(ENV_FUTURES_SECRET, "").strip()
        if not (self.key and self.secret):
            raise FuturesDemoBrokerError("missing futures demo credentials")

    # ---- signed plumbing ------------------------------------------------------
    def _signed(self, method: str, path: str, params: dict) -> dict:
        params = dict(params)
        params["timestamp"] = int(params.get("timestamp") or time.time() * 1000)
        params["recvWindow"] = int(params.get("recvWindow") or 5000)
        qs = urllib.parse.urlencode(params)
        sig = hmac.new(self.secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
        url = f"{self.base}{path}?{qs}&signature={sig}"
        headers = {"X-MBX-APIKEY": self.key}
        try:
            r = httpx.request(method, url, headers=headers, timeout=_TIMEOUT)
        except httpx.HTTPError as e:
            # never include the URL (it carries the signature); error type only
            raise FuturesDemoBrokerError(
                f"futures demo request failed: {type(e).__name__}") from e
        if r.status_code >= 400:
            try:
                msg = r.json().get("msg", r.text[:120])
            except Exception:
                msg = r.text[:120]
            raise FuturesDemoBrokerError(
                f"binance futures demo error {r.status_code}: {msg}")
        return r.json()

    def _public(self, path: str, params: dict | None = None) -> dict:
        try:
            r = httpx.get(f"{self.base}{path}", params=params or {}, timeout=_TIMEOUT)
            r.raise_for_status()
            j = r.json()
            return j if isinstance(j, dict) else {"data": j}
        except httpx.HTTPError as e:
            raise FuturesDemoBrokerError(
                f"futures demo public request failed: {type(e).__name__}") from e

    # ---- account / market ------------------------------------------------------
    def ping(self) -> bool:
        self._public("/fapi/v1/ping")
        return True

    def server_time(self) -> int:
        return int(self._public("/fapi/v1/time")["serverTime"])

    def exchange_info(self) -> dict:
        return self._public("/fapi/v1/exchangeInfo")

    def symbol_info(self, symbol: str) -> dict:
        """Per-symbol filters (LOT_SIZE step, MIN_NOTIONAL, price tick) — used to
        validate/floored qty/price exactly like the exchange would."""
        sym = (symbol or "").upper()
        for s in self.exchange_info().get("symbols", []):
            if s["symbol"] == sym:
                return s
        raise FuturesDemoBrokerError(f"unknown futures symbol {sym}")

    def last_price(self, symbol: str) -> float:
        j = self._public("/fapi/v1/ticker/price", {"symbol": symbol})
        return float(j["price"])

    def _map_order(self, j: dict) -> dict:
        fills = j.get("fills") or []
        # fapi fills carry qty/price as strings; spot testnet used floats
        avg = 0.0
        cum = 0.0
        for f in fills:
            q = float(f.get("qty", 0))
            avg += float(f.get("price", 0)) * q
            cum += q
        avg = (avg / cum) if cum > 0 else float(j.get("avgPrice") or 0)
        return {
            "order_id": j.get("clientOrderId") or j.get("orderId"),
            "exchange_order_id": j.get("orderId"),
            "symbol": j.get("symbol"),
            "side": j.get("side"),
            "type": j.get("type"),
            "status": j.get("status"),
            "executed_qty": float(j.get("executedQty") or 0),
            "orig_qty": float(j.get("origQty") or 0),
            "avg_price": avg,
            "price": float(j.get("price") or 0),
            "commission": sum(float(f.get("commission", 0)) for f in fills),
            "commission_asset": (fills[0].get("commissionAsset") if fills else None),
            "fills": fills,
            "ts": int(time.time() * 1000),
        }

    # ---- position mode / leverage (account state, verified pre-order) ---------
    def get_position_mode(self) -> str:
        """One-way (hedgeMode=false) or dual-side. Engine requires ONE-WAY (§10)."""
        j = self._signed("GET", "/fapi/v1/positionSide/dual", {})
        return MODE_DUAL if j.get("dualSidePosition") is True else MODE_ONE_WAY

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        """Set per-symbol leverage. Returns broker response (raises on error)."""
        return self._signed("POST", "/fapi/v1/leverage",
                            {"symbol": (symbol or "").upper(), "leverage": int(leverage)})

    def account(self) -> dict:
        return self._signed("GET", "/fapi/v2/account", {})

    def account_snapshot(self) -> dict:
        acct = self.account()
        bal = {b["asset"]: {"wallet": float(b.get("walletBalance", 0)),
                            "available": float(b.get("availableBalance", 0)),
                            "margin": float(b.get("marginBalance", 0))}
               for b in acct.get("assets", []) if float(b.get("walletBalance", 0)) != 0}
        return {"mode": "DEMO_FUTURES", "endpoint": self.base, "balances": bal,
                "ts": int(time.time() * 1000)}

    def position(self, symbol: str) -> dict | None:
        """USDT-M futures position for symbol (positionAmt != 0), or None."""
        sym = (symbol or "").upper()
        j = self._signed("GET", "/fapi/v2/positionRisk",
                         {"symbol": sym, "recvWindow": 5000})
        row = j[0] if isinstance(j, list) and j else {}
        amt = float(row.get("positionAmt") or 0)
        if amt == 0:
            return None
        entry = float(row.get("entryPrice") or 0)
        mark = float(row.get("markPrice") or 0)
        side = "LONG" if amt > 0 else "SHORT"
        notional = abs(amt) * mark
        # margin = notional / leverage (isolated cross default); never fabricate
        lev = float(row.get("leverage") or 1)
        return {
            "symbol": sym, "side": side, "quantity": abs(amt), "position_amt": amt,
            "entry_price": entry, "mark_price": mark, "notional": notional,
            "leverage": lev,
            "margin": notional / lev if lev > 0 else 0.0,
            "liquidation_price": float(row.get("liquidationPrice") or 0) or None,
            "unrealized_pnl": float(row.get("unRealizedProfit") or 0),
            "status": "OPEN", "mode": "DEMO_FUTURES",
        }

    # ---- orders ----------------------------------------------------------------
    def market_order(self, symbol: str, side: str, quantity: float) -> dict:
        """Open/reduce a futures MARKET position. side: LONG->BUY, SHORT->SELL.
        The engine decides the close side from the open position (never here)."""
        side = str(side or "").upper()
        if side not in ("LONG", "SHORT"):
            raise FuturesDemoBrokerError(f"invalid side {side} (LONG/SHORT only)")
        j = self._signed("POST", "/fapi/v1/order", {
            "symbol": (symbol or "").upper(),
            "side": "BUY" if side == "LONG" else "SELL",
            "type": "MARKET",
            "quantity": f"{float(quantity):.8f}",
            "newOrderRespType": "RESULT",
        })
        return self._map_order(j)

    def close_market(self, symbol: str, side: str, quantity: float) -> dict:
        """Close an existing futures position at market. side = OPEN side
        (LONG -> SELL to close, SHORT -> BUY to close), mirroring ONE-WAY mode."""
        return self.market_order(symbol,
                                 "SHORT" if str(side).upper() == "LONG" else "LONG",
                                 quantity)

    def order_status(self, order_id: str, symbol: str) -> dict:
        j = self._signed("GET", "/fapi/v1/order",
                         {"symbol": (symbol or "").upper(), "origClientOrderId": order_id})
        return self._map_order(j)

    def cancel(self, order_id: str, symbol: str) -> dict:
        j = self._signed("DELETE", "/fapi/v1/order",
                         {"symbol": (symbol or "").upper(), "origClientOrderId": order_id})
        return self._map_order(j)

    # ---- validation (LOT_SIZE / MIN_NOTIONAL — deterministic, no order) ---------
    def validate(self, symbol: str, qty: float, price: float | None = None) -> dict:
        """Check symbol/qty/notional against the futures exchangeInfo filters."""
        sym = (symbol or "").upper()
        if qty is None or float(qty) <= 0:
            return {"ok": False, "reason": "invalid quantity"}
        try:
            info = self.symbol_info(sym)
        except Exception as e:
            return {"ok": False, "reason": str(e)}
        if info.get("status") != "TRADING":
            return {"ok": False, "reason": f"symbol not trading: {info.get('status')}"}
        px = float(price or self.last_price(sym))
        fil = {f["filterType"]: f for f in info.get("filters", [])}
        lot = fil.get("LOT_SIZE") or {}
        step = float(lot.get("stepSize") or 1e-8)
        # floor to the exchange step (never round up past available margin)
        qty_f = int(float(qty) / step + 1e-9) * step
        qty_f = round(qty_f, 10)
        if qty_f < float(lot.get("minQty") or 0):
            return {"ok": False, "reason": f"qty below LOT_SIZE min {lot.get('minQty')}"}
        if qty_f > float(lot.get("maxQty") or 1e18):
            return {"ok": False, "reason": f"qty above LOT_SIZE max {lot.get('maxQty')}"}
        notional = qty_f * px
        min_not = float((fil.get("MIN_NOTIONAL") or {}).get("notional") or 0)
        if notional < min_not:
            return {"ok": False, "reason": f"notional {notional:.2f} < MIN_NOTIONAL {min_not}"}
        return {"ok": True, "reason": None, "quantity": qty_f, "price": px,
                "notional": notional}
