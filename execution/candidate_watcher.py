"""Frozen DEMO candidate watcher — read-only, closed-bar, non-fatal.

Polling wrapper over execution/demo_signal.build_demo_candidate() (the frozen
RegimeGatedTrend 0.1.0 path) + execution/eligibility (deterministic gate).

Guarantees:
  - Processes ONLY CLOSED candles (caller passes candle(s) whose bar is done;
    the watcher itself never reads the forming bar as decision input).
  - No orders, no authorization flags, no continuous execution, no mainnet
    path. Pure decision-support observability.
  - No LLM call for candidate discovery: build_demo_candidate is called with
    use_llm=False; ordinary NO_TRADE → zero LLM, zero Telegram.
  - Telegram notify ONLY when eligibility == ELIGIBLE, deduped by signal id
    (symbol:tf:bar_open_time) via demo_events UNIQUE(decision_id,event_type)
    so one closed candle → at most one alert, even across restarts.
  - Non-fatal: a failure on one symbol is logged and skipped, never raised.
"""
from __future__ import annotations
import time
from storage.database import init_db, get_db
from storage import demo_store as store
from agents import telegram_notifier as tg

EVENT_CANDIDATE = "CANDIDATE"
NOTIFY_HEADER = "FROZEN DEMO CANDIDATE / READY FOR DEMO SMOKE TEST"
WATCH_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
TIMEFRAME = "1h"


def _last_closed_bar(klines: list[dict], now_ms: int | None = None) -> dict | None:
    """Return the newest fully-closed candle (never the forming one).

    A 1h bar at open_time T closes at T+3600s. The forming bar is the one whose
    close_time > now. We return the newest bar with close_time <= now.
    """
    now_ms = now_ms or int(time.time() * 1000)
    closed = [c for c in (klines or []) if int(c.get("close_time") or 0) <= now_ms]
    return closed[-1] if closed else None


def check_symbol(symbol: str, candles: list[dict],
                 equity: float = 10000.0, notify: bool = True,
                 now_ms: int | None = None) -> dict:
    """Evaluate ONE symbol's latest CLOSED bar. Read-only.

    Returns a status dict. Sends a Telegram candidate alert ONLY when the frozen
    candidate is ELIGIBLE and that candle has not already been notified.
    """
    out = {"symbol": symbol, "processed": False, "eligible": False,
           "notified": False, "deduped": False, "reason": None,
           "bar_open_time": None, "candidate": None}
    try:
        bar = _last_closed_bar(candles, now_ms)
        if bar is None:
            out["reason"] = "NO_CLOSED_BAR"
            return out
        bar_open = int(bar.get("open_time") or 0)
        out["bar_open_time"] = bar_open

        from execution.demo_signal import build_demo_candidate, traceable_chain
        # frozen path, discovery only: LLM explicitly OFF (task: no LLM to find candidates)
        cand = build_demo_candidate(candles, symbol=symbol, timeframe=TIMEFRAME,
                                    equity=equity, use_llm=False)
        elig = cand.get("eligibility") or {}
        chain = traceable_chain(cand)
        out["candidate"] = chain
        out["processed"] = True
        if not elig.get("eligible"):
            out["reason"] = elig.get("reason") or "NOT_ELIGIBLE"
            return out
        out["eligible"] = True

        # dedup by candle: (decision_id, CANDIDATE) unique in demo_events
        decision_id = cand.get("decision_id") or cand.get("signal_id")
        if decision_id is None:
            out["reason"] = "NO_SIGNAL_ID"
            return out
        inserted = store.mark_event(decision_id, EVENT_CANDIDATE, telegram_sent=0,
                                    meta={"symbol": symbol, "reason": elig.get("reason")})
        if not inserted:
            out["deduped"] = True
            out["reason"] = "DUPLICATE_CANDLE"
            return out

        if notify:
            ev = {"symbol": symbol, "decision": cand.get("decision"),
                  "side": cand.get("side"), "regime": cand.get("regime"),
                  "entry": cand.get("entry"), "stop": cand.get("stop"),
                  "tp1": cand.get("tp1"), "tp2": cand.get("tp2"),
                  "rr": cand.get("rr"), "risk_pct": cand.get("risk_pct"),
                  "ai_status": cand.get("ai_status"),
                  "signal_id": cand.get("signal_id"),
                  "decision_id": cand.get("decision_id"),
                  "strategy_id": cand.get("strategy_id"),
                  "strategy_version": cand.get("strategy_version"),
                  "timeframe": TIMEFRAME, "mode": "DEMO",
                  "header": NOTIFY_HEADER, "ts": int(time.time() * 1000)}
            res = tg.notify(tg.EVENT_DEMO_CANDIDATE, ev)
            out["notified"] = bool(res.get("sent"))
            out["telegram"] = res
            try:
                get_db().execute(
                    "UPDATE demo_events SET telegram_sent=?, telegram_error=? "
                    "WHERE decision_id=? AND event_type=?",
                    (1 if res.get("sent") else 0,
                     (res.get("error") or "")[:200] if not res.get("sent") else None,
                     decision_id, EVENT_CANDIDATE))
            except Exception:
                pass
        return out
    except Exception as e:
        out["reason"] = f"ERROR: {type(e).__name__}: {e}"
        return out


def check_all(candles_by_symbol: dict[str, list[dict]], equity: float = 10000.0,
              notify: bool = True) -> list[dict]:
    """Run check_symbol over every symbol (closed-bar per symbol). Non-fatal."""
    results = []
    for sym in WATCH_SYMBOLS:
        results.append(check_symbol(sym, candles_by_symbol.get(sym, []),
                                    equity=equity, notify=notify))
    return results


def run_once(symbols=WATCH_SYMBOLS, equity: float = 10000.0, notify: bool = True,
             fetch=None) -> list[dict]:
    """One watcher pass: fetch live candles per symbol, evaluate CLOSED bar only.

    `fetch` injectable for tests; default = ingestion.market_data.fetch_klines.
    """
    if fetch is None:
        from ingestion.market_data import fetch_klines
        fetch = fetch_klines
    init_db()
    results = []
    for sym in symbols:
        try:
            candles = fetch(sym, TIMEFRAME, limit=100)
        except Exception as e:
            results.append({"symbol": sym, "processed": False,
                            "reason": f"FETCH_ERROR: {type(e).__name__}: {e}"})
            continue
        results.append(check_symbol(sym, candles, equity=equity, notify=notify))
    return results
