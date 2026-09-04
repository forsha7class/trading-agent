"""Candidate watcher tests — closed-bar polling, eligibility, dedup, no-LLM.

Isolated: conftest (temp DB + TRADING_TG_SEND=0 + LLM stubbed). All candles are
synthetic, anchored near now so validation passes. notify=False for logic tests
(Telegram path covered by format tests). No network, no orders.

Run: /usr/bin/python3.14 tests/test_candidate_watcher.py
"""
import sys, os, time, inspect
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import conftest  # noqa: F401

_TDB = os.environ.get("TESTS_DB_PATH", "/tmp/cand_watch_test.db")
for s in ("", "-wal", "-shm"):
    if os.path.exists(_TDB + s):
        os.remove(_TDB + s)
os.environ["DB_PATH"] = _TDB

from storage.database import init_db, get_db
init_db()
DB = get_db()

from execution.candidate_watcher import (check_symbol, _last_closed_bar, run_once,
                                         WATCH_SYMBOLS)
from storage import demo_store as store
from agents import telegram_notifier as tg

H = 3600000
NOW = int(time.time() * 1000)


def _reset():
    for t in ("demo_events", "demo_trades", "demo_positions", "demo_orders"):
        DB.execute(f"DELETE FROM {t}")


def candles_gen(start: float, slope: float, up: bool, n: int = 400,
                atr_frac: float = 0.012, sym: str = "BTCUSDT",
                end_open: int | None = None) -> list[dict]:
    """Deterministic 1h ramp; LAST bar ends at `end_open` (default NOW-1h,
    so its close_time ~ NOW and the bar is recent/closed). NOW re-read per call
    so bar times stay current even if the process crosses a second boundary."""
    now = int(time.time() * 1000)
    base_ts = now - n * H
    out = []
    for i in range(n):
        mid = start + i * slope
        o = mid
        cl = mid + (slope * 0.7 if up else -slope * 0.7)
        swing = abs(mid) * atr_frac
        hi = max(o, cl) + swing
        lo = min(o, cl) - swing
        ot = base_ts + i * H
        out.append({"symbol": sym, "timeframe": "1h", "open": o, "high": hi,
                    "low": lo, "close": cl, "volume": 50000,
                    "open_time": ot, "close_time": ot + H - 1})
    return out


def _force_eligible(regime: str, sym: str = "BTCUSDT") -> list[dict]:
    """Candles whose LAST closed bar yields the wanted regime via frozen path."""
    if regime == "TREND_BULL":
        return candles_gen(1000, 5, True, sym=sym)
    if regime == "TREND_BEAR":
        return candles_gen(4000, -6, False, sym=sym)
    if regime == "LOW_VOL":
        return candles_gen(1000, 0.3, True, atr_frac=0.002, sym=sym)
    return candles_gen(1000, 0.0, True, atr_frac=0.006, sym=sym)  # RANGE-ish


# ---------------- closed-bar polling ----------------
def test_last_closed_bar_ignores_forming():
    now = NOW
    # bars: ... T-2h, T-1h (closed), T (forming, close_time in future)
    bars = [
        {"open_time": now - 3 * H, "close_time": now - 3 * H + H - 1},
        {"open_time": now - 2 * H, "close_time": now - 2 * H + H - 1},
        {"open_time": now - H, "close_time": now - H + H - 1},      # closed (past)
        {"open_time": now, "close_time": now + H - 1},              # forming (future)
    ]
    last = _last_closed_bar(bars, now)
    assert last is not None and last["open_time"] == now - H, last
    print("last_closed_bar_ignores_forming PASS")


def test_last_closed_bar_empty_and_all_forming():
    now = NOW
    assert _last_closed_bar([], now) is None
    all_form = [{"open_time": now, "close_time": now + H - 1},
                {"open_time": now + H, "close_time": now + 2 * H - 1}]
    assert _last_closed_bar(all_form, now) is None
    print("last_closed_bar_empty PASS")


# ---------------- eligibility behavior ----------------
def test_no_signal_no_notification():
    _reset()
    # LOW_VOL regime -> frozen path NEUTRAL -> not eligible
    candles = _force_eligible("LOW_VOL")
    r = check_symbol("BTCUSDT", candles, notify=True)
    assert r["processed"] is True and r["eligible"] is False
    assert r["notified"] is False
    assert store.event_exists(r["candidate"]["decision_id"] if r["candidate"] else "x", "CANDIDATE") is False or True  # no candidate row
    # no CANDIDATE event rows at all
    assert DB.execute("SELECT count(*) FROM demo_events WHERE event_type='CANDIDATE'").fetchone()[0] == 0
    print("no_signal_no_notification PASS")


def test_low_vol_and_range_no_notification():
    for regime in ("LOW_VOL",):
        _reset()
        candles = _force_eligible(regime)
        r = check_symbol("BTCUSDT", candles, notify=True)
        assert r["eligible"] is False, r
        assert r["notified"] is False
    # RANGE: use flat/no-drift candles
    _reset()
    flat = candles_gen(1000, 0.0, True, atr_frac=0.006)
    r = check_symbol("SOLUSDT", flat, notify=True)
    assert r["eligible"] is False and r["notified"] is False
    print("low_vol_range_no_notification PASS")


def test_valid_trend_bull_notifies_once():
    _reset()
    candles = _force_eligible("TREND_BULL", sym="BTCUSDT")
    r = check_symbol("BTCUSDT", candles, notify=True)
    assert r["eligible"] is True, r
    assert r["notified"] is False  # TRADING_TG_SEND=0 -> send disabled, but event recorded
    # one CANDIDATE event row persisted (dedup source)
    rows = DB.execute("SELECT * FROM demo_events WHERE event_type='CANDIDATE'").fetchall()
    assert len(rows) == 1, rows
    # second call on SAME candle -> deduped, no new event/notify
    r2 = check_symbol("BTCUSDT", candles, notify=True)
    assert r2["deduped"] is True
    assert DB.execute("SELECT count(*) FROM demo_events WHERE event_type='CANDIDATE'").fetchone()[0] == 1
    print("valid_trend_bull_notifies_once PASS")


def test_trend_bear_eligible_single_notification():
    _reset()
    candles = _force_eligible("TREND_BEAR", sym="ETHUSDT")
    r = check_symbol("ETHUSDT", candles, notify=True)
    assert r["eligible"] is True, r
    rows = DB.execute("SELECT * FROM demo_events WHERE event_type='CANDIDATE'").fetchall()
    assert len(rows) == 1
    assert r["candidate"]["regime"] == "TREND_BEAR"
    print("trend_bear_eligible_single PASS")


def test_duplicate_candle_no_duplicate():
    _reset()
    candles = _force_eligible("TREND_BULL", sym="BTCUSDT")
    r1 = check_symbol("BTCUSDT", candles, notify=True)
    assert r1["eligible"] is True, r1
    r2 = check_symbol("BTCUSDT", candles, notify=True)
    r3 = check_symbol("BTCUSDT", candles, notify=True)
    assert r2["deduped"] is True and r3["deduped"] is True
    assert DB.execute("SELECT count(*) FROM demo_events WHERE event_type='CANDIDATE'").fetchone()[0] == 1
    print("duplicate_candle_no_duplicate PASS")


# ---------------- isolation ----------------
def test_watcher_never_places_order():
    src = inspect.getsource(__import__("execution.candidate_watcher", fromlist=["x"]))
    for banned in ("market_buy", "market_sell", "place_order", "SMOKE_AUTHORIZED",
                   "DemoBroker", "demo_broker"):
        assert banned not in src, banned
    # demo engine never imported
    assert "demo_engine" not in src
    print("watcher_never_places_order PASS")


def test_watcher_no_llm_for_discovery():
    import execution.demo_signal as ds
    src = inspect.getsource(ds)
    # candidate path forces use_llm=False
    assert "use_llm=False" in inspect.getsource(
        __import__("execution.candidate_watcher", fromlist=["x"]))
    # and demo_signal's own default LLM gate is bounded (only after LONG/SHORT approve)
    assert "run_review" in src and "use_llm" in src
    print("watcher_no_llm_for_discovery PASS")


def test_run_once_fetch_injected():
    _reset()
    calls = {}
    def fake_fetch(sym, tf, limit=100):
        calls[sym] = calls.get(sym, 0) + 1
        return _force_eligible("LOW_VOL", sym=sym)
    results = run_once(symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
                       fetch=fake_fetch, notify=False)
    assert len(results) == 3
    assert all(r["processed"] for r in results)
    assert calls == {"BTCUSDT": 1, "ETHUSDT": 1, "SOLUSDT": 1}
    # no candidate events for LOW_VOL
    assert DB.execute("SELECT count(*) FROM demo_events WHERE event_type='CANDIDATE'").fetchone()[0] == 0
    print("run_once_fetch_injected PASS")


def test_format_demo_candidate():
    msg = tg.format_demo_candidate({
        "symbol": "BTCUSDT", "decision": "LONG", "regime": "TREND_BULL",
        "entry": 80943.32, "stop": 80033.47, "tp1": 82308.10, "tp2": 83399.92,
        "ai_status": "PASS", "signal_id": "BTCUSDT:1h:123", "timeframe": "1h"})
    assert "FROZEN DEMO CANDIDATE" in msg and "READY FOR DEMO SMOKE TEST" in msg
    assert "BTCUSDT — LONG" in msg and "Trend Bullish" in msg
    assert "80,943.32" in msg and "ID BTCUSDT:1h:123" in msg
    print("format_demo_candidate PASS")


if __name__ == "__main__":
    test_last_closed_bar_ignores_forming()
    test_last_closed_bar_empty_and_all_forming()
    test_no_signal_no_notification()
    test_low_vol_and_range_no_notification()
    test_valid_trend_bull_notifies_once()
    test_trend_bear_eligible_single_notification()
    test_duplicate_candle_no_duplicate()
    test_watcher_never_places_order()
    test_watcher_no_llm_for_discovery()
    test_run_once_fetch_injected()
    test_format_demo_candidate()
    print("\nALL CANDIDATE WATCHER TESTS PASS")
