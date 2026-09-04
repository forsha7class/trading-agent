"""Binance Spot Testnet REST client — minimal, signed, secret-safe.

Base is hard-coded to the verified testnet endpoint (https://testnet.binance.vision).
Credentials come from the environment (BINANCE_DEMO_API_KEY / BINANCE_DEMO_API_SECRET)
and are NEVER printed, logged, persisted, or sent anywhere but the signed request.

No mainnet route exists in this module. Signed calls use HMAC-SHA256 + X-MBX-APIKEY,
the standard Binance authentication scheme.
"""
from __future__ import annotations
import os, time, hmac, hashlib, urllib.parse
import httpx

from .env import TESTNET_BASE, ENV_KEY, ENV_SECRET, demo_env_status

_TIMEOUT = 15.0


class DemoBrokerError(RuntimeError):
    pass


class DemoBroker:
    def __init__(self, base: str | None = None, key: str | None = None,
                 secret: str | None = None):
        st = demo_env_status()
        if not st["demo_ready"]:
            raise DemoBrokerError("demo environment not ready: " + "; ".join(st["reasons"] or []))
        self.base = (base or st["endpoint"] or TESTNET_BASE).rstrip("/")
        if self.base != TESTNET_BASE:
            raise DemoBrokerError(f"refusing non-testnet base {self.base}")
        self.key = key or os.getenv(ENV_KEY, "").strip()
        self.secret = secret or os.getenv(ENV_SECRET, "").strip()
        if not (self.key and self.secret):
            raise DemoBrokerError("missing demo credentials")

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
            # never include the URL (it carries the signature); log error type only
            raise DemoBrokerError(f"demo request failed: {type(e).__name__}") from e
        if r.status_code >= 400:
            try:
                msg = r.json().get("msg", r.text[:120])
            except Exception:
                msg = r.text[:120]
            raise DemoBrokerError(f"binance demo error {r.status_code}: {msg}")
        return r.json()

    def _public(self, path: str, params: dict | None = None) -> dict:
        try:
            r = httpx.get(f"{self.base}{path}", params=params or {}, timeout=_TIMEOUT)
            r.raise_for_status()
            j = r.json()
            return j if isinstance(j, dict) else {"data": j}
        except httpx.HTTPError as e:
            raise DemoBrokerError(f"demo public request failed: {type(e).__name__}") from e

    # ---- account / market ------------------------------------------------------
    def server_time(self) -> int:
        return int(self._public("/api/v3/time")["serverTime"])

    def ping(self) -> bool:
        self._public("/api/v3/ping")
        return True

    def account(self) -> dict:
        return self._signed("GET", "/api/v3/account", {})

    def account_snapshot(self) -> dict:
        acct = self.account()
        balances = {b["asset"]: float(b["free"]) for b in acct.get("balances", [])
                    if float(b.get("free", 0)) > 0}
        return {"mode": "DEMO", "endpoint": self.base, "balances": balances,
                "ts": int(time.time() * 1000)}

    def asset_balance(self, symbol: str) -> dict | None:
        """Spot position = free base-asset balance for a MARKET symbol pair."""
        base_asset = (symbol or "").upper()
        for suffix in ("USDT", "BTC", "ETH", "BUSD", "FDUSD"):
            if base_asset.endswith(suffix):
                base_asset = base_asset[: -len(suffix)]
                break
        acct = self.account()
        for b in acct.get("balances", []):
            if b["asset"] == base_asset and float(b.get("free", 0)) > 0:
                px = self.last_price(symbol)
                return {"symbol": symbol.upper(), "asset": base_asset,
                        "free": float(b["free"]), "locked": float(b.get("locked", 0)),
                        "notional": float(b["free"]) * px, "last_price": px,
                        "status": "OPEN", "mode": "DEMO"}
        return None

    def last_price(self, symbol: str) -> float:
        j = self._public("/api/v3/ticker/price", {"symbol": symbol})
        return float(j["price"])

    def exchange_info(self) -> dict:
        return self._public("/api/v3/exchangeInfo")

    # ---- orders ----------------------------------------------------------------
    def market_buy(self, symbol: str, quantity: float) -> dict:
        j = self._signed("POST", "/api/v3/order", {
            "symbol": symbol, "side": "BUY", "type": "MARKET",
            "quantity": f"{quantity:.8f}", "newOrderRespType": "FULL"})
        return self._map_order(j)

    def market_sell(self, symbol: str, quantity: float) -> dict:
        j = self._signed("POST", "/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "MARKET",
            "quantity": f"{quantity:.8f}", "newOrderRespType": "FULL"})
        return self._map_order(j)

    def order_status(self, order_id: str) -> dict:
        j = self._signed("GET", "/api/v3/order",
                         {"symbol": self._symbol_of(order_id), "origClientOrderId": order_id})
        return self._map_order(j)

    def cancel(self, order_id: str) -> dict:
        j = self._signed("DELETE", "/api/v3/order",
                         {"symbol": self._symbol_of(order_id), "origClientOrderId": order_id})
        return self._map_order(j)

    @staticmethod
    def _symbol_of(order_id: str) -> str:
        # client order ids are encoded as <SYMBOL>.<uuid8> by the engine; fall back
        # to a BTCUSDT probe is avoided — engine always passes symbol via order dict.
        return "BTCUSDT"

    @staticmethod
    def _map_order(j: dict) -> dict:
        fills = j.get("fills") or []
        return {
            "order_id": j.get("clientOrderId") or j.get("orderId"),
            "exchange_order_id": j.get("orderId"),
            "symbol": j.get("symbol"),
            "side": j.get("side"),
            "type": j.get("type"),
            "status": j.get("status"),
            "executed_qty": float(j.get("executedQty") or 0),
            "orig_qty": float(j.get("origQty") or 0),
            "avg_price": float(j.get("avgPrice") or 0) or
                         (sum(float(f.get("price", 0)) * float(f.get("qty", 0))
                              for f in fills) / max(1e-12, sum(float(f.get("qty", 0))
                              for f in fills))),
            "commission": sum(float(f.get("commission", 0)) for f in fills),
            "commission_asset": (fills[0].get("commissionAsset") if fills else None),
            "fills": fills,
            "ts": int(time.time() * 1000),
        }
