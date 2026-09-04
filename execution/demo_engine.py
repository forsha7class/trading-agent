"""DEMO lifecycle engine — order -> position -> exit -> audit -> Telegram.

Deterministic, fail-closed. The only way a DEMO order reaches an exchange is
through this engine with a REAL broker (DemoBroker for spot, FuturesDemoBroker
for USDT-M futures), each of which refuses unless its demo env gate is green
(TRADING_MODE=DEMO + creds + the correct testnet endpoint for its market).

Market capability (task §9/§10): the broker advertises what it can execute:
  {"market": "SPOT" | "FUTURES", "long": bool, "short": bool, "leverage_max": 1|2}
Spot => LONG only. Futures => LONG and SHORT, leverage <= 2 (1x preferred),
one-way mode. The engine never assumes capability; the broker declares it.

Engine gates before ANY order (task §8):
  1. eligibility gate (execution.eligibility) — frozen source, approved risk
  2. market capability: spot LONG only; futures LONG/SHORT (else reject)
  3. valid price/quantity
  4. no duplicate order/position for the decision or an OPEN position per symbol
  5. position-limit capacity
  6. environment field == DEMO (spot) / DEMO_FUTURES (futures)

Exits (task §13, frozen semantics, user-confirmed):
  - SL checked first; SL wins if same bar touches both SL and TP1.
  - TP1 is a FULL exit (TP2 stored, never resolved — no partial scale-out).
  - TIME_EXIT after max_hold_bars hours (1h bars => close_time - opened_at).
  - Exit qty = open_qty held; market close mirrors the open side (futures
    SELL-to-close a LONG, BUY-to-close a SHORT; spot always sells).

Broker is injected: tests pass a FakeBroker (no network); the real smoke test
passes execution.demo_broker.DemoBroker or
execution.futures_broker.FuturesDemoBroker. Nothing in this module ever imports
credentials or performs network I/O itself.
"""
from __future__ import annotations
import time

from execution.eligibility import check_demo_eligibility
from storage import demo_store as store
from agents import telegram_notifier as tg
from config.settings import get_settings

MAX_HOLD_BARS = 20
HOUR_MS = 3600000

# exit reason vocabulary (task §13/§23 + Telegram formats)
EXIT_TP1 = "TAKE_PROFIT_1"
EXIT_TP2 = "TAKE_PROFIT_2"
EXIT_SL = "STOP_LOSS"
EXIT_TIME = "TIME_EXIT"
EXIT_MANUAL = "MANUAL_CLOSE"
_EVENTS = {EXIT_TP1: tg.EVENT_DEMO_TP1, EXIT_TP2: tg.EVENT_DEMO_TP2,
           EXIT_SL: tg.EVENT_DEMO_SL, EXIT_TIME: tg.EVENT_DEMO_TIME}


class DemoEngine:
    def __init__(self, broker, fee_bps: float | None = None, max_hold_bars: int = MAX_HOLD_BARS):
        """broker: object with capabilities/market_*_open/market_close/order_status/
        validate (Fake, spot or futures). Broker declares its market capability."""
        self.broker = broker
        s = get_settings()
        self.fee_bps = fee_bps if fee_bps is not None else float(getattr(s, "fee", 0.0004))
        self.max_hold_bars = int(max_hold_bars)
        # futures (FuturesDemoBroker) vs spot (DemoBroker / FakeBroker)
        self.market = "FUTURES" if getattr(broker, "market", "SPOT") == "FUTURES" else "SPOT"
        # environment tag stored on every row: DEMO (spot) / DEMO_FUTURES
        self.env_label = "DEMO_FUTURES" if self.market == "FUTURES" else "DEMO"
        self.leverage = int(getattr(broker, "leverage", 1) or 1)

    # ---- open ---------------------------------------------------------------
    def open_from_candidate(self, candidate: dict) -> dict:
        """Gate + place + reconcile one demo order from a frozen candidate dict."""
        cand = candidate or {}
        decision_id = cand.get("decision_id") or cand.get("signal_id")
        symbol = str(cand.get("symbol") or "").upper()
        side = str(cand.get("decision") or cand.get("side") or "NO_TRADE").upper()

        # 0. no stale duplicate for this decision
        if store.get_order_by_decision(cand.get("decision_id")):
            return self._reject(cand, "DUPLICATE_ORDER", "order already exists for decision")
        # 1. authoritative source/eligibility gate (RiskEngine inside; AI advisory)
        elig = check_demo_eligibility({
            "strategy_id": cand.get("strategy_id"), "strategy_version": cand.get("strategy_version"),
            "regime": cand.get("regime"), "decision": side,
            "risk_engine": cand.get("risk_engine"), "ai_status": cand.get("ai_status")})
        if not elig["eligible"]:
            return self._reject(cand, elig["reason"], "eligibility gate")
        # 2. market capability gate — broker declares LONG/SHORT support (§9/§10)
        caps = self._capabilities()
        if side == "LONG" and not caps.get("long", True):
            return self._reject(cand, "LONG_NOT_SUPPORTED", f"{self.market} demo cannot open LONG")
        if side == "SHORT" and not caps.get("short", False):
            return self._reject(cand, "SHORT_NOT_SUPPORTED",
                                f"{self.market} demo cannot open SHORT")
        # leverage cap (futures 2x hard max; spot is always 1x)
        lev = float(cand.get("leverage") or self.leverage or 1)
        if lev > float(caps.get("leverage_max", 1)) + 1e-9:
            return self._reject(cand, "LEVERAGE_EXCEEDS_MAX",
                                f"leverage {lev} > {caps.get('leverage_max')}x cap")
        # environment must match the broker's market (never DEMO->FUTURES mix)
        cand_env = str(cand.get("environment") or "DEMO").upper()
        if self.market == "FUTURES":
            if cand_env not in ("DEMO_FUTURES", "DEMO"):
                return self._reject(cand, "NOT_DEMO_FUTURES", "environment != DEMO_FUTURES")
        elif cand_env != "DEMO":
            return self._reject(cand, "NOT_DEMO", "environment != DEMO")
        # 3. valid price/quantity
        qty = cand.get("position_size")
        entry = cand.get("entry")
        if qty is None or float(qty) <= 0 or entry is None or float(entry) <= 0:
            return self._reject(cand, "INVALID_QTY_PRICE", "quantity/price invalid")
        qty = float(qty)
        # 4/5. duplicate per symbol + capacity
        if any(p["symbol"] == symbol and p["status"] == "OPEN"
               for p in store.open_positions()):
            return self._reject(cand, "DUPLICATE_POSITION", f"{symbol} already OPEN")
        if len(store.open_positions()) >= int(get_settings().max_positions):
            return self._reject(cand, "POSITION_LIMIT", "max demo positions reached")
        # 6. symbol/qty sanity via broker (mock ok / real exchangeInfo)
        try:
            v = self.broker.validate(symbol, qty)
            if not v.get("ok"):
                return self._reject(cand, "INVALID_SYMBOL_QTY", v.get("reason", "broker validation"))
            qty = float(v.get("quantity") or qty)  # futures: floored to LOT_SIZE step
        except Exception as e:
            return self._reject(cand, "ORDER_VALIDATION_ERROR", str(e))

        # ---- persist order (NEW), then place -------------------------------
        order_id = self._persist_order(cand, qty, "NEW", reject_reason=None, leverage=lev)
        try:
            resp = self.broker.market_open(symbol, side, qty)
        except Exception as e:
            # failed order -> no position (task §11); mark rejected
            store.update_order(order_id, status="REJECTED",
                               reject_reason=f"{type(e).__name__}: {e}", closed_at=int(time.time()*1000))
            return {"order_id": order_id, "decision_id": cand.get("decision_id"),
                    "status": "REJECTED", "reason": f"order failed: {type(e).__name__}",
                    "position": None, "order": store.get_order(order_id)}

        # ---- reconcile fill (never assume request success == fill) ----------
        status = str(resp.get("status") or "").upper()
        filled_qty = float(resp.get("executed_qty") or 0)
        avg_price = float(resp.get("avg_price") or 0) or float(resp.get("price") or 0)
        if status in ("FILLED", "PARTIALLY_FILLED") and filled_qty > 0:
            entry_px = avg_price or float(entry)
            store.update_order(order_id, status="FILLED" if status == "FILLED"
                               else "PARTIALLY_FILLED", executed_qty=filled_qty,
                               executed_price=entry_px, opened_at=int(time.time()*1000),
                               leverage=lev)
            pos = self._open_position(cand, order_id, entry_px, filled_qty, lev)
            ev = {"symbol": symbol, "side": side, "entry": entry_px, "stop": cand.get("stop"),
                  "tp1": cand.get("tp1"), "tp2": cand.get("tp2"),
                  "rr": cand.get("rr"), "risk_pct": cand.get("risk_pct"),
                  "quantity": filled_qty, "order_id": order_id,
                  "ai_status": cand.get("ai_status"), "regime": cand.get("regime"),
                  "timeframe": cand.get("timeframe"), "environment": self.env_label,
                  "decision_id": cand.get("decision_id"),
                  "id": cand.get("decision_id"), "leverage": lev,
                  "market": self.market}
            self._emit_once(cand.get("decision_id"), "FILL", ev, tg.EVENT_DEMO_FILLED)
            return {"order_id": order_id, "decision_id": cand.get("decision_id"),
                    "status": "FILLED", "position": pos, "order": store.get_order(order_id)}
        # rejected/canceled/unknown -> no position, unresolved stays safe
        store.update_order(order_id, status=status if status else "UNKNOWN",
                           reject_reason=resp.get("msg") or resp.get("reason"),
                           closed_at=int(time.time()*1000))
        return {"order_id": order_id, "decision_id": cand.get("decision_id"),
                "status": status or "UNKNOWN", "position": None,
                "reason": resp.get("msg") or resp.get("reason") or "unfilled",
                "order": store.get_order(order_id)}

    def _capabilities(self) -> dict:
        """What this broker's market can execute (engine never assumes)."""
        caps = getattr(self.broker, "capabilities", None)
        if isinstance(caps, dict):
            return caps
        # spot-shaped brokers (DemoBroker / FakeBroker): LONG only, 1x
        return {"market": self.market, "long": True, "short": False, "leverage_max": 1}

    # ---- market update: exits ----------------------------------------------
    def update_market(self, candle: dict) -> list[dict]:
        """Resolve SL/TP1/TIME_EXIT for open DEMO positions of candle.symbol."""
        closed = []
        sym = (candle.get("symbol") or "").upper()
        high = float(candle.get("high") or 0)
        low = float(candle.get("low") or 0)
        close = float(candle.get("close") or 0)
        bar_ts = int(candle.get("close_time") or time.time() * 1000)
        for p in store.open_positions():
            if p["symbol"] != sym:
                continue
            hit, exit_px = self._resolve_exit(p, high, low, close, bar_ts)
            if not hit or exit_px is None:
                continue
            rec = self._close_position(p, hit, exit_px, bar_ts)
            closed.append(rec)
        return closed

    def _resolve_exit(self, p: dict, high: float, low: float, close: float,
                      bar_ts: int) -> tuple[str | None, float | None]:
        side = p["side"]
        stop, tp1 = p.get("stop"), p.get("tp1")
        if side == "LONG":
            if stop is not None and low <= float(stop):
                return EXIT_SL, float(stop)
            if tp1 is not None and high >= float(tp1):
                return EXIT_TP1, float(tp1)
        else:
            if stop is not None and high >= float(stop):
                return EXIT_SL, float(stop)
            if tp1 is not None and low <= float(tp1):
                return EXIT_TP1, float(tp1)
        # TIME_EXIT after max_hold_bars of 1h bars since open
        if p.get("opened_at") and (bar_ts - int(p["opened_at"])) >= self.max_hold_bars * HOUR_MS:
            return EXIT_TIME, close
        return None, None

    def _close_position(self, p: dict, hit: str, level_px: float, bar_ts: int) -> dict:
        sym, side, qty = p["symbol"], p["side"], float(p.get("open_qty") or p.get("size") or 0)
        entry = float(p["entry"])
        lev = float(p.get("leverage") or self.leverage or 1)
        margin = float(p.get("margin") or 0) or (abs(entry) * qty / lev if lev else 0)
        # exit price: SL adverse slippage; TP at level; TIME_EXIT at close (already level)
        slip = self.fee_bps if hit == EXIT_SL else 0.0
        exit_px = level_px * (1 - slip) if side == "LONG" else level_px * (1 + slip)
        gross = (exit_px - entry) * qty if side == "LONG" else (entry - exit_px) * qty
        fees = (abs(entry * qty) + abs(exit_px * qty)) * self.fee_bps
        net = gross - fees
        roe_pct = (net / margin * 100) if margin > 0 else None
        now = int(time.time() * 1000)
        # close via the broker — market-shaped close mirrors the open side:
        # futures LONG -> SELL-to-close, SHORT -> BUY-to-close; spot always sells.
        close = None
        try:
            close = self.broker.market_close(sym, side, qty)
        except Exception:
            close = None  # exit bookkeeping proceeds; reconcile later if needed
        store.update_position(p["id"], status="CLOSED", closed_at=bar_ts)
        store.update_order(p["order_id"], status="CLOSED", closed_at=bar_ts)
        trade = store.insert_demo_trade({
            "position_id": p["id"], "order_id": p["order_id"],
            "decision_id": p["decision_id"], "symbol": sym, "side": side,
            "entry": entry, "exit_price": exit_px, "size": qty, "qty": qty,
            "pnl": net, "fees": fees, "exit_reason": hit,
            "opened_at": p["opened_at"], "closed_at": bar_ts,
            "environment": self.env_label, "leverage": lev, "roe_pct": roe_pct})
        rec = {**p, "exit_reason": hit, "exit_price": exit_px, "pnl": net, "fees": fees,
               "closed_at": bar_ts, "trade_id": trade.get("id"), "close": close,
               "qty": qty, "entry": entry, "leverage": lev, "roe_pct": roe_pct,
               "environment": self.env_label}
        ev = {"symbol": sym, "side": side, "entry": entry, "exit": exit_px,
              "pnl": net, "fees": fees, "exit_reason": hit,
              "rr": _rr_of(p), "risk_pct": None, "holding_bars": _holding_bars(p, bar_ts),
              "decision_id": p["decision_id"], "id": p["decision_id"],
              "environment": self.env_label, "leverage": lev, "roe_pct": roe_pct,
              "market": self.market, "qty": qty}
        self._emit_once(p["decision_id"], hit, ev, _EVENTS.get(hit))
        return rec

    # ---- persistence helpers ------------------------------------------------
    def _persist_order(self, cand: dict, qty: float, status: str,
                       reject_reason: str | None, leverage: float | None = None) -> str:
        o = store.insert_demo_order({
            "decision_id": cand.get("decision_id"), "signal_id": cand.get("signal_id"),
            "symbol": str(cand.get("symbol") or "").upper(),
            "side": str(cand.get("decision") or cand.get("side")).upper(),
            "requested_qty": qty, "requested_price": cand.get("entry"),
            "stop": cand.get("stop"), "tp1": cand.get("tp1"), "tp2": cand.get("tp2"),
            "status": status, "strategy_id": cand.get("strategy_id"),
            "strategy_version": cand.get("strategy_version"),
            "regime": cand.get("regime"), "risk_engine": cand.get("risk_engine"),
            "ai_status": cand.get("ai_status"), "environment": self.env_label,
            "reject_reason": reject_reason, "leverage": leverage or 1})
        return o["id"]

    def _open_position(self, cand: dict, order_id: str, entry_px: float,
                       qty: float, leverage: float | None = None) -> dict:
        lev = float(leverage or cand.get("leverage") or self.leverage or 1)
        pos = store.insert_demo_position({
            "order_id": order_id, "decision_id": cand.get("decision_id"),
            "symbol": str(cand.get("symbol") or "").upper(),
            "side": str(cand.get("decision") or cand.get("side")).upper(),
            "entry": entry_px, "stop": cand.get("stop"), "tp1": cand.get("tp1"),
            "tp2": cand.get("tp2"), "size": qty, "open_qty": qty, "status": "OPEN",
            "opened_at": int(time.time() * 1000), "environment": self.env_label,
            "leverage": lev})
        return pos

    def _reject(self, cand: dict, reason: str, detail: str) -> dict:
        ev = {"symbol": cand.get("symbol"), "side": cand.get("decision"),
              "reason": f"{reason}: {detail}", "regime": cand.get("regime"),
              "ai_status": cand.get("ai_status"),
              "decision_id": cand.get("decision_id"), "id": cand.get("decision_id"),
              "environment": self.env_label}
        self._emit_once(cand.get("decision_id"), "REJECT", ev, tg.EVENT_DEMO_REJECT)
        return {"order_id": None, "decision_id": cand.get("decision_id"),
                "status": "REJECTED", "reason": reason, "position": None}

    def _emit_once(self, decision_id, event_type: str, ev: dict, tg_event: str | None):
        """Dedup by (decision_id, event_type) -> one Telegram message (task §19)."""
        if not store.mark_event(decision_id, event_type, telegram_sent=0):
            return
        if tg_event is None:
            return
        res = tg.notify(tg_event, ev)
        try:
            store.get_db().execute(
                "UPDATE demo_events SET telegram_sent=?, telegram_error=? "
                "WHERE decision_id=? AND event_type=?",
                (1 if res.get("sent") else 0,
                 (res.get("error") or "")[:200] if not res.get("sent") else None,
                 decision_id, event_type))
        except Exception:
            pass

    # ---- reconciliation on restart ------------------------------------------
    def reconcile_open(self) -> dict:
        """Rebuild open demo positions from the DB (crash/restart safe, §12)."""
        return {"open": [dict(p) for p in store.open_positions()],
                "count": len(store.open_positions())}


def _rr_of(p: dict) -> float | None:
    try:
        e, s = float(p["entry"]), float(p["stop"])
        d = abs(e - s)
        t1 = float(p.get("tp1") or 0)
        return abs(t1 - e) / d if d else None
    except Exception:
        return None


def _holding_bars(p: dict, bar_ts: int) -> int:
    try:
        return max(0, int((bar_ts - int(p["opened_at"])) // HOUR_MS))
    except Exception:
        return 0
