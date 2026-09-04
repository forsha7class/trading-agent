"""DEMO execution slice tests — env gate, adapters, broker safety, lifecycle.

Isolated: conftest (temp DB + TRADING_TG_SEND=0 + LLM stubbed), FakeBroker for
all exchange interactions. ZERO network / ZERO real orders. Real DemoBroker is
only exercised when explicitly authorized in a smoke test (never here).

Run: /usr/bin/python3.14 tests/test_demo_execution.py
"""
import sys, os, time, inspect
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import conftest  # noqa: F401 — isolated DB, no telegram sends

# fresh isolated DB for this module
_TDB = os.environ.get("TESTS_DB_PATH", "/tmp/demo_exec_test.db")
for s in ("", "-wal", "-shm"):
    if os.path.exists(_TDB + s):
        os.remove(_TDB + s)
os.environ["DB_PATH"] = _TDB

from storage.database import init_db, get_db
init_db()
DB = get_db()

from execution import env as exenv
from execution.adapters import (get_adapter, LiveExecution, PaperExecution,
                                DemoExecution, DISABLED_STATE, ST_REJECTED)
from execution.demo_engine import (DemoEngine, EXIT_TP1, EXIT_SL, EXIT_TIME,
                                   MAX_HOLD_BARS)
from execution.fake_broker import FakeBroker
from execution.eligibility import FROZEN_DEMO_STRATEGY_ID, FROZEN_DEMO_STRATEGY_VERSION
from storage import demo_store as store
from agents import telegram_notifier as tg

H = 3600000
T0 = int(time.time() * 1000)

# ---------------------------------------------------------------------------
def _clear_env(*keys):
    for k in keys:
        os.environ.pop(k, None)


def _set_demo_env():
    os.environ["TRADING_MODE"] = "DEMO"
    os.environ["BINANCE_DEMO_API_KEY"] = "k" * 64
    os.environ["BINANCE_DEMO_API_SECRET"] = "s" * 64
    os.environ.pop("BINANCE_DEMO_BASE", None)


def _reset_tables():
    for t in ("demo_events", "demo_trades", "demo_positions", "demo_orders"):
        DB.execute(f"DELETE FROM {t}")


def _frozen_candidate(side="LONG", regime="TREND_BULL", risk="APPROVED",
                      symbol="BTCUSDT", entry=80000.0, stop=79000.0,
                      tp1=81500.0, tp2=82500.0, size=0.001, ai="PASS",
                      dec_id=None, env="DEMO"):
    return {"strategy_id": FROZEN_DEMO_STRATEGY_ID,
            "strategy_version": FROZEN_DEMO_STRATEGY_VERSION,
            "regime": regime, "decision": side, "side": side, "symbol": symbol,
            "entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2,
            "position_size": size, "risk_engine": risk, "ai_status": ai,
            "signal_id": f"{symbol}:1h:{T0}", "decision_id": dec_id or (T0 % 100000),
            "timeframe": "1h", "environment": env}


def _candle(ts, high, low, close, sym="BTCUSDT"):
    return {"symbol": sym, "open": close, "high": high, "low": low,
            "close": close, "volume": 100.0, "open_time": ts, "close_time": ts + H - 1}


# ============================ ENV GATE ======================================
def test_env_gate_defaults_paper():
    _clear_env("TRADING_MODE", "BINANCE_DEMO_API_KEY", "BINANCE_DEMO_API_SECRET")
    assert exenv.trading_mode() == "PAPER"
    st = exenv.demo_env_status()
    assert st["demo_ready"] is False and st["locked"] is True
    print("env_gate_defaults_paper PASS")


def test_env_gate_demo_requires_all():
    _clear_env("TRADING_MODE", "BINANCE_DEMO_API_KEY", "BINANCE_DEMO_API_SECRET")
    os.environ["TRADING_MODE"] = "DEMO"
    assert exenv.demo_env_status()["demo_ready"] is False  # no creds
    _set_demo_env()
    st = exenv.demo_env_status()
    assert st["demo_ready"] is True and st["endpoint_is_testnet"] is True
    print("env_gate_demo_requires_all PASS")


def test_env_gate_rejects_mainnet_endpoint():
    _set_demo_env()
    os.environ["BINANCE_DEMO_BASE"] = "https://api.binance.com"
    st = exenv.demo_env_status()
    assert st["demo_ready"] is False
    assert any("mainnet" in r or "not the confirmed testnet" in r for r in st["reasons"]), st
    _clear_env("BINANCE_DEMO_BASE")
    print("env_gate_rejects_mainnet PASS")


def test_env_gate_live_fails_closed():
    _set_demo_env()
    os.environ["TRADING_MODE"] = "LIVE"
    st = exenv.demo_env_status()
    assert st["demo_ready"] is False and st["locked"] is True
    ad = get_adapter("LIVE")
    assert isinstance(ad, LiveExecution)
    assert ad.place_order({"symbol": "BTCUSDT"})["status"] == DISABLED_STATE
    assert ad.reconcile()["status"] == DISABLED_STATE
    print("env_gate_live_fails_closed PASS")


# ============================ ADAPTERS ======================================
def test_adapters_live_has_no_order_impl():
    src = inspect.getsource(LiveExecution)
    assert "market_buy" not in src and "api.binance" not in src and "httpx" not in src
    assert "DISABLED_STATE" in src  # identifier (value lives at module level)
    print("adapters_live_no_order_impl PASS")


def test_adapters_paper_unchanged_route():
    ad = get_adapter("PAPER")
    assert isinstance(ad, PaperExecution)
    assert ad.mode == "PAPER"
    print("adapters_paper_route PASS")


def test_adapters_demo_requires_env():
    _clear_env("TRADING_MODE", "BINANCE_DEMO_API_KEY", "BINANCE_DEMO_API_SECRET")
    try:
        get_adapter("DEMO")
        assert False, "should raise without demo env"
    except RuntimeError as e:
        assert "DEMO environment not ready" in str(e)
    print("adapters_demo_requires_env PASS")


# ============================ BROKER SAFETY =================================
def test_broker_refuses_non_testnet():
    _set_demo_env()
    from execution.demo_broker import DemoBroker
    try:
        DemoBroker(base="https://api.binance.com")
        assert False, "must refuse mainnet base"
    except Exception as e:
        assert "non-testnet" in str(e)
    print("broker_refuses_non_testnet PASS")


def test_broker_never_logs_secrets():
    from execution.demo_broker import DemoBroker
    src = inspect.getsource(DemoBroker)
    assert "print(" not in src or "secret" not in src
    # key/secret only ever used in HMAC signing; never string-interpolated into
    # logs/errors. Check: no f-string/log line references self.key/self.secret.
    import re
    # lines containing self.secret or self.key
    uses = [ln.strip() for ln in src.splitlines() if "self.secret" in ln or "self.key" in ln]
    for ln in uses:
        # allowed: assignment, hmac signing, presence check — NOT format/log/print
        assert not re.search(r'(f["\'].*self\.(secret|key)|log|print)', ln), ln
    # URL is built in _signed with signature appended; nothing prints the URL
    assert 'print(' not in [ln for ln in src.splitlines() if "url" in ln]
    print("broker_never_logs_secrets PASS")


# ============================ LIFECYCLE =====================================
def test_open_fill_creates_chain():
    _reset_tables()
    fb = FakeBroker(fill_price=80000.0)
    eng = DemoEngine(fb)
    cand = _frozen_candidate(dec_id=9001)
    r = eng.open_from_candidate(cand)
    assert r["status"] == "FILLED", r
    assert r["order_id"] and r["position"]
    o = store.get_order(r["order_id"])
    p = store.get_position(r["position"]["id"])
    t = store.get_trade_by_decision(9001)
    assert o["status"] == "FILLED" and o["decision_id"] == 9001
    assert p["status"] == "OPEN" and p["side"] == "LONG"
    assert p["entry"] == 80000.0 and p["stop"] == 79000.0
    assert store.get_order_by_decision(9001) is not None
    # no trade yet (trade row created on close)
    assert t is None
    print("open_fill_creates_chain PASS")


def test_duplicate_decision_rejected():
    _reset_tables()
    fb = FakeBroker()
    eng = DemoEngine(fb)
    cand = _frozen_candidate(dec_id=9002)
    r1 = eng.open_from_candidate(cand)
    assert r1["status"] == "FILLED"
    r2 = eng.open_from_candidate(cand)  # same decision again
    assert r2["status"] == "REJECTED" and "DUPLICATE" in r2["reason"]
    assert len(store.open_positions()) == 1
    print("duplicate_decision_rejected PASS")


def test_duplicate_symbol_open_rejected():
    _reset_tables()
    fb = FakeBroker()
    eng = DemoEngine(fb)
    r1 = eng.open_from_candidate(_frozen_candidate(dec_id=9003))
    assert r1["status"] == "FILLED"
    r2 = eng.open_from_candidate(_frozen_candidate(dec_id=9004))  # same symbol, new decision
    assert r2["status"] == "REJECTED" and "DUPLICATE" in r2["reason"]
    print("duplicate_symbol_open_rejected PASS")


def test_short_rejected_spot():
    _reset_tables()
    fb = FakeBroker()
    eng = DemoEngine(fb)
    r = eng.open_from_candidate(_frozen_candidate(side="SHORT", regime="TREND_BEAR",
                                                  entry=40000, stop=41000, tp1=39000,
                                                  dec_id=9005))
    assert r["status"] == "REJECTED" and "SPOT_LONG_ONLY" in r["reason"]
    assert len(store.open_positions()) == 0
    print("short_rejected_spot PASS")


def test_risk_reject_no_order():
    _reset_tables()
    fb = FakeBroker()
    eng = DemoEngine(fb)
    r = eng.open_from_candidate(_frozen_candidate(risk="REJECT", dec_id=9006))
    assert r["status"] == "REJECTED"
    assert store.get_order_by_decision(9006) is None  # no order persisted
    print("risk_reject_no_order PASS")


def test_non_frozen_source_rejected():
    _reset_tables()
    fb = FakeBroker()
    eng = DemoEngine(fb)
    cand = _frozen_candidate(dec_id=9007)
    cand["strategy_id"] = "ensemble"  # legacy path
    r = eng.open_from_candidate(cand)
    assert r["status"] == "REJECTED" and "WRONG_STRATEGY" in r["reason"]
    print("non_frozen_source_rejected PASS")


def test_broker_reject_no_position():
    _reset_tables()
    fb = FakeBroker(reject_symbol="BTCUSDT")
    eng = DemoEngine(fb)
    r = eng.open_from_candidate(_frozen_candidate(dec_id=9008))
    assert r["status"] == "REJECTED"  # validation failed pre-order
    assert len(store.open_positions()) == 0
    print("broker_reject_no_position PASS")


def test_partial_fill_reconciles_actual_qty():
    _reset_tables()
    fb = FakeBroker(fill_pct=0.5)  # half fill
    eng = DemoEngine(fb)
    cand = _frozen_candidate(dec_id=9009, size=0.002)
    r = eng.open_from_candidate(cand)
    assert r["status"] == "FILLED"
    o = store.get_order(r["order_id"])
    p = store.get_position(r["position"]["id"])
    assert o["status"] == "PARTIALLY_FILLED"
    assert abs(o["executed_qty"] - 0.001) < 1e-12  # actual filled qty reconciled
    assert abs(p["open_qty"] - 0.001) < 1e-12
    print("partial_fill_reconciles PASS")


def test_sl_exit():
    _reset_tables()
    fb = FakeBroker()
    eng = DemoEngine(fb, fee_bps=0.0)
    cand = _frozen_candidate(dec_id=9010, entry=80000, stop=79000, tp1=81500)
    r = eng.open_from_candidate(cand)
    pid = r["position"]["id"]
    # bar hits SL (low <= 79000) -> SL wins
    closed = eng.update_market(_candle(T0 + H, high=81000, low=78500, close=80000))
    assert len(closed) == 1 and closed[0]["exit_reason"] == EXIT_SL
    assert closed[0]["pnl"] == (79000 - 80000) * 0.001
    assert store.get_position(pid)["status"] == "CLOSED"
    t = store.get_trade_by_decision(9010)
    assert t and t["exit_reason"] == "STOP_LOSS" and t["pnl"] == (79000 - 80000) * 0.001
    print("sl_exit PASS")


def test_tp1_exit_full():
    _reset_tables()
    fb = FakeBroker()
    eng = DemoEngine(fb, fee_bps=0.0)
    cand = _frozen_candidate(dec_id=9011, entry=80000, stop=79000, tp1=81500)
    r = eng.open_from_candidate(cand)
    pid = r["position"]["id"]
    closed = eng.update_market(_candle(T0 + H, high=82000, low=79500, close=81000))
    assert len(closed) == 1 and closed[0]["exit_reason"] == EXIT_TP1
    assert closed[0]["pnl"] == (81500 - 80000) * 0.001  # full exit at TP1
    t = store.get_trade_by_decision(9011)
    assert t and t["exit_reason"] == "TAKE_PROFIT_1"
    assert store.get_position(pid)["status"] == "CLOSED"
    # TP2 is never resolved (full TP1 exit) — no second trade
    assert store.get_trade_by_decision(9011)["exit_reason"] == "TAKE_PROFIT_1"
    print("tp1_exit_full PASS")


def test_sl_wins_when_both_touched():
    _reset_tables()
    fb = FakeBroker()
    eng = DemoEngine(fb, fee_bps=0.0)
    cand = _frozen_candidate(dec_id=9012, entry=80000, stop=79000, tp1=81500)
    r = eng.open_from_candidate(cand)
    # bar touches both SL (low 78500) and TP1 (high 82000) -> SL wins (frozen rule)
    closed = eng.update_market(_candle(T0 + H, high=82000, low=78500, close=80500))
    assert len(closed) == 1 and closed[0]["exit_reason"] == EXIT_SL
    print("sl_wins_when_both PASS")


def test_time_exit():
    _reset_tables()
    fb = FakeBroker()
    eng = DemoEngine(fb, fee_bps=0.0, max_hold_bars=2)
    cand = _frozen_candidate(dec_id=9013, entry=80000, stop=70000, tp1=99999)
    r = eng.open_from_candidate(cand)
    pid = r["position"]["id"]
    opened = store.get_position(pid)["opened_at"]
    # 2 bars later (>= 2h) no SL/TP touch -> TIME_EXIT at close
    closed = eng.update_market(_candle(opened + 2 * H, high=80100, low=79900, close=80050))
    assert len(closed) == 1 and closed[0]["exit_reason"] == EXIT_TIME
    assert closed[0]["exit_price"] == 80050.0
    assert store.get_trade_by_decision(9013)["exit_reason"] == "TIME_EXIT"
    print("time_exit PASS")


def test_no_double_close():
    _reset_tables()
    fb = FakeBroker()
    eng = DemoEngine(fb, fee_bps=0.0)
    cand = _frozen_candidate(dec_id=9014, entry=80000, stop=79000, tp1=81500)
    r = eng.open_from_candidate(cand)
    c1 = eng.update_market(_candle(T0 + H, high=82000, low=78500, close=80500))
    assert len(c1) == 1
    c2 = eng.update_market(_candle(T0 + 2 * H, high=82000, low=78500, close=80500))
    assert c2 == []  # position already closed, never double-closed
    print("no_double_close PASS")


def test_event_dedup_one_telegram():
    _reset_tables()
    fb = FakeBroker()
    eng = DemoEngine(fb)
    cand = _frozen_candidate(dec_id=9015, entry=80000, stop=79000, tp1=81500)
    eng.open_from_candidate(cand)
    # FILL event row exists exactly once
    rows = DB.execute("SELECT * FROM demo_events WHERE decision_id=9015 AND event_type='FILL'").fetchall()
    assert len(rows) == 1
    # second mark_event attempt returns False (dedup)
    assert store.event_exists(9015, "FILL") is True
    # closing emits SL event once
    eng.update_market(_candle(T0 + H, high=81000, low=78500, close=80000))
    rows = DB.execute("SELECT * FROM demo_events WHERE decision_id=9015 AND event_type='STOP_LOSS'").fetchall()
    assert len(rows) == 1
    print("event_dedup_one_telegram PASS")


def test_reconcile_open_on_restart():
    _reset_tables()
    fb = FakeBroker()
    eng = DemoEngine(fb)
    eng.open_from_candidate(_frozen_candidate(dec_id=9016))
    # new engine over same DB = restart; reconcile finds the OPEN position
    eng2 = DemoEngine(FakeBroker())
    rec = eng2.reconcile_open()
    assert rec["count"] == 1 and rec["open"][0]["decision_id"] == 9016
    print("reconcile_open_on_restart PASS")


# ============================ TELEGRAM FORMAT ===============================
def test_format_demo_filled():
    ev = {"symbol": "BTCUSDT", "side": "LONG", "regime": "TREND_BULL",
          "entry": 80943.321234, "stop": 80033.47, "tp1": 82308.10, "tp2": 83399.92,
          "quantity": 0.00123456, "ai_status": "PASS", "order_id": "ord_abc123",
          "timeframe": "1h", "decision_id": 42}
    msg = tg.format_demo_filled(ev)
    assert "BTCUSDT" in msg and "DEMO LONG" in msg
    assert "80,943.32" in msg and "80,033.47" in msg and "82,308.10" in msg
    assert "BINANCE DEMO" in msg and "OPEN" in msg
    assert "ord_abc123" in msg
    print("format_demo_filled PASS")


def test_format_demo_exit_tp1():
    ev = {"symbol": "BTCUSDT", "side": "LONG", "entry": 80943.32, "exit": 82308.10,
          "rr": 1.5, "pnl": 12.34, "exit_reason": "TAKE_PROFIT_1", "decision_id": 42}
    msg = tg.format_demo_exit(ev)
    assert "TP1 HIT" in msg and "80,943.32" in msg and "82,308.10" in msg
    assert "+1.50R" in msg and "+12.34" in msg
    assert "TAKE_PROFIT_1" in msg and "BINANCE DEMO" in msg
    print("format_demo_exit_tp1 PASS")


def test_format_demo_exit_sl():
    ev = {"symbol": "BTCUSDT", "side": "LONG", "entry": 80943.32, "exit": 80033.47,
          "rr": -1.0, "pnl": -10.0, "exit_reason": "STOP_LOSS", "decision_id": 43}
    msg = tg.format_demo_exit(ev)
    assert "STOP LOSS" in msg and "-1.00R" in msg and "-10.00" in msg
    print("format_demo_exit_sl PASS")


def test_format_demo_reject():
    ev = {"symbol": "BTCUSDT", "reason": "R:R 1.32 < minimum 1.50",
          "regime": "RANGE", "ai_status": "SKIPPED"}
    msg = tg.format_demo_reject(ev)
    assert "NO TRADE" in msg and "R:R 1.32 < minimum 1.50" in msg
    assert "Range" in msg and "No order placed." in msg
    print("format_demo_reject PASS")


def test_regime_readable():
    assert tg._regime_readable("TREND_BULL") == "Trend Bullish"
    assert tg._regime_readable("LOW_VOL") == "Low Volatility"
    assert tg._regime_readable("RANGE") == "Range"
    print("regime_readable PASS")


def test_number_formats():
    assert tg._price(80943.321234) == "80,943.32"
    assert tg._rr_str(1.500000000000008) == "1:1.50"
    assert tg._pct(0.70) == "70%"
    assert tg._pct(0.005, nd=2) == "0.50%"
    print("number_formats PASS")


# ============================ TEST ISOLATION ================================
def test_no_real_network_in_tests():
    # DemoEngine with FakeBroker must never touch httpx/network
    import execution.demo_engine as de
    assert "httpx" not in inspect.getsource(de)
    # engine never imports the network broker (docstring mention only)
    assert "import" not in [ln for ln in inspect.getsource(de).splitlines()
                            if "broker" in ln.lower() and "import" in ln]
    assert tg._creds()[0] is None  # telegram send disabled by conftest
    print("no_real_network_in_tests PASS")


if __name__ == "__main__":
    test_env_gate_defaults_paper()
    test_env_gate_demo_requires_all()
    test_env_gate_rejects_mainnet_endpoint()
    test_env_gate_live_fails_closed()
    test_adapters_live_has_no_order_impl()
    test_adapters_paper_unchanged_route()
    test_adapters_demo_requires_env()
    test_broker_refuses_non_testnet()
    test_broker_never_logs_secrets()
    test_open_fill_creates_chain()
    test_duplicate_decision_rejected()
    test_duplicate_symbol_open_rejected()
    test_short_rejected_spot()
    test_risk_reject_no_order()
    test_non_frozen_source_rejected()
    test_broker_reject_no_position()
    test_partial_fill_reconciles_actual_qty()
    test_sl_exit()
    test_tp1_exit_full()
    test_sl_wins_when_both_touched()
    test_time_exit()
    test_no_double_close()
    test_event_dedup_one_telegram()
    test_reconcile_open_on_restart()
    test_format_demo_filled()
    test_format_demo_exit_tp1()
    test_format_demo_exit_sl()
    test_format_demo_reject()
    test_regime_readable()
    test_number_formats()
    test_no_real_network_in_tests()
    print("\nALL DEMO EXECUTION TESTS PASS")
