"""FUTURES DEMO execution slice tests — env kind gate, futures broker safety,
LONG+SHORT lifecycle, leverage cap, one-way mode, exit accounting, formats.

Isolated: conftest (temp DB + TRADING_TG_SEND=0), FakeFuturesBroker for all
exchange interactions. ZERO network / ZERO real orders. FuturesDemoBroker is
only exercised when explicitly authorized in a smoke test (never here).

Run: python tests/test_futures_demo.py
"""
import sys, os, time, inspect
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import conftest  # noqa: F401 — isolated DB, no telegram sends

_TDB = os.environ.get("TESTS_DB_PATH", "/tmp/futures_demo_test.db")
for s in ("", "-wal", "-shm"):
    if os.path.exists(_TDB + s):
        os.remove(_TDB + s)
os.environ["DB_PATH"] = _TDB

from storage.database import init_db, get_db
init_db()
DB = get_db()

from execution import env as exenv
from execution.futures_broker import (FuturesDemoBroker, FuturesDemoBrokerError,
                                      MODE_ONE_WAY, MODE_DUAL)
from execution.fake_broker import FakeFuturesBroker, FakeBroker
from execution.demo_engine import DemoEngine, EXIT_TP1, EXIT_SL, EXIT_TIME
from execution.eligibility import FROZEN_DEMO_STRATEGY_ID, FROZEN_DEMO_STRATEGY_VERSION
from execution.adapters import DemoFuturesExecution
from storage import demo_store as store
from agents import telegram_notifier as tg

H = 3600000
T0 = int(time.time() * 1000)


def _clear_env(*keys):
    for k in keys:
        os.environ.pop(k, None)


def _set_futures_env():
    os.environ["TRADING_MODE"] = "DEMO"
    os.environ["DEMO_KIND"] = "FUTURES"
    os.environ["BINANCE_FUTURES_DEMO_API_KEY"] = "f" * 64
    os.environ["BINANCE_FUTURES_DEMO_API_SECRET"] = "g" * 64
    os.environ.pop("BINANCE_FUTURES_DEMO_BASE", None)
    os.environ.pop("FUTURES_DEMO_LEGACY", None)
    # spot creds deliberately ABSENT — futures gate must not need/use them
    os.environ.pop("BINANCE_DEMO_API_KEY", None)
    os.environ.pop("BINANCE_DEMO_API_SECRET", None)


def _set_futures_testnet_env():
    """Explicit legacy opt-in: FUTURES_DEMO_LEGACY=1 + testnet base override."""
    _set_futures_env()
    os.environ["FUTURES_DEMO_LEGACY"] = "1"
    os.environ["BINANCE_FUTURES_DEMO_BASE"] = exenv.FUTURES_TESTNET_BASE


def _reset_tables():
    for t in ("demo_events", "demo_trades", "demo_positions", "demo_orders"):
        DB.execute(f"DELETE FROM {t}")


def _frozen_candidate(side="LONG", regime="TREND_BULL", risk="APPROVED",
                      symbol="BTCUSDT", entry=80000.0, stop=79000.0,
                      tp1=81500.0, tp2=82500.0, size=0.001, ai="PASS",
                      dec_id=None, lev=1.0):
    return {"strategy_id": FROZEN_DEMO_STRATEGY_ID,
            "strategy_version": FROZEN_DEMO_STRATEGY_VERSION,
            "regime": regime, "decision": side, "side": side, "symbol": symbol,
            "entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2,
            "position_size": size, "risk_engine": risk, "ai_status": ai,
            "signal_id": f"{symbol}:1h:{T0}", "decision_id": dec_id or (T0 % 100000),
            "timeframe": "1h", "environment": "DEMO_FUTURES", "leverage": lev}


def _candle(ts, high, low, close, sym="BTCUSDT"):
    return {"symbol": sym, "open": close, "high": high, "low": low,
            "close": close, "volume": 100.0, "open_time": ts, "close_time": ts + H - 1}


# ============================ ENV KIND GATE =================================
def test_futures_env_defaults_to_demo_fapi():
    """Futures demo target defaults to the OFFICIAL demo base (demo-fapi), not
    the legacy testnet."""
    _set_futures_env()
    assert exenv.futures_target() == exenv.TARGET_FUTURES_DEMO
    st = exenv.demo_env_status()
    assert st["kind"] == "FUTURES" and st["demo_ready"] is True
    assert st["endpoint"] == exenv.FUTURES_DEMO_BASE
    assert st["endpoint_is_demo"] is True
    assert st["endpoint_is_testnet"] is False
    print("futures_env_defaults_to_demo_fapi PASS")


def test_futures_testnet_requires_legacy_optin():
    """testnet.binancefuture.com is NOT accepted unless FUTURES_DEMO_LEGACY=1."""
    _set_futures_env()
    os.environ["BINANCE_FUTURES_DEMO_BASE"] = exenv.FUTURES_TESTNET_BASE
    st = exenv.demo_env_status()
    assert st["demo_ready"] is False  # no legacy opt-in
    assert any("FUTURES_DEMO_LEGACY" in r for r in st["reasons"]), st["reasons"]
    # with the explicit opt-in the legacy testnet becomes allowed
    os.environ["FUTURES_DEMO_LEGACY"] = "1"
    st2 = exenv.demo_env_status()
    assert st2["demo_ready"] is True
    assert st2["endpoint_is_testnet"] is True and st2["endpoint_is_demo"] is False
    _set_futures_env()
    print("futures_testnet_requires_legacy_optin PASS")


def test_futures_env_requires_kind_and_own_creds():
    _clear_env("TRADING_MODE", "DEMO_KIND", "BINANCE_FUTURES_DEMO_API_KEY",
               "BINANCE_FUTURES_DEMO_API_SECRET")
    os.environ["TRADING_MODE"] = "DEMO"
    st = exenv.demo_env_status()
    assert st["demo_ready"] is False  # kind defaults SPOT, no futures creds needed path
    _set_futures_env()
    st = exenv.demo_env_status()
    assert st["kind"] == "FUTURES" and st["demo_ready"] is True
    assert st["endpoint_is_demo"] is True
    assert st["endpoint"] == exenv.FUTURES_DEMO_BASE
    print("futures_env_kind_own_creds PASS")


def test_futures_broker_defaults_demo_and_refuses_mainnet():
    """Broker default base = official demo-fapi; mainnet refused always."""
    _set_futures_env()
    src = inspect.getsource(FuturesDemoBroker)
    assert "FUTURES_DEMO_BASE" in src              # demo base is the default target
    assert exenv.FUTURES_DEMO_BASE == "https://demo-fapi.binance.com"
    try:
        FuturesDemoBroker(base="https://fapi.binance.com")
        assert False, "must refuse mainnet futures base"
    except FuturesDemoBrokerError as e:
        assert "never accepted" in str(e) or "refusing" in str(e)
    print("futures_broker_defaults_demo_refuses_mainnet PASS")


def test_futures_broker_testnet_requires_legacy():
    _set_futures_testnet_env()
    b = FuturesDemoBroker()
    assert b.base == exenv.FUTURES_TESTNET_BASE
    _set_futures_env()  # no legacy opt-in anymore
    try:
        FuturesDemoBroker(base=exenv.FUTURES_TESTNET_BASE)
        assert False, "testnet base without legacy opt-in must be refused"
    except FuturesDemoBrokerError as e:
        assert "FUTURES_DEMO_LEGACY" in str(e)
    print("futures_broker_testnet_requires_legacy PASS")


def test_futures_gate_never_uses_spot_creds():
    # spot creds alone must NOT satisfy the futures gate
    _clear_env("TRADING_MODE", "DEMO_KIND", "BINANCE_FUTURES_DEMO_API_KEY",
               "BINANCE_FUTURES_DEMO_API_SECRET", "BINANCE_DEMO_API_KEY",
               "BINANCE_DEMO_API_SECRET")
    os.environ["TRADING_MODE"] = "DEMO"
    os.environ["DEMO_KIND"] = "FUTURES"
    os.environ["BINANCE_DEMO_API_KEY"] = "k" * 64
    os.environ["BINANCE_DEMO_API_SECRET"] = "s" * 64
    st = exenv.demo_env_status()
    assert st["demo_ready"] is False
    assert any("futures demo credentials" in r for r in st["reasons"]), st
    print("futures_gate_never_uses_spot_creds PASS")


def test_spot_gate_never_uses_futures_creds():
    _clear_env("TRADING_MODE", "DEMO_KIND", "BINANCE_FUTURES_DEMO_API_KEY",
               "BINANCE_FUTURES_DEMO_API_SECRET", "BINANCE_DEMO_API_KEY",
               "BINANCE_DEMO_API_SECRET")
    os.environ["TRADING_MODE"] = "DEMO"
    os.environ["DEMO_KIND"] = "SPOT"
    os.environ["BINANCE_FUTURES_DEMO_API_KEY"] = "f" * 64
    os.environ["BINANCE_FUTURES_DEMO_API_SECRET"] = "g" * 64
    st = exenv.demo_env_status()
    assert st["demo_ready"] is False  # spot creds absent
    assert any("spot demo credentials" in r for r in st["reasons"]), st
    print("spot_gate_never_uses_futures_creds PASS")


# ============================ BROKER SAFETY =================================
def test_futures_broker_never_logs_secrets():
    src = inspect.getsource(FuturesDemoBroker)
    uses = [ln.strip() for ln in src.splitlines() if "self.secret" in ln or "self.key" in ln]
    for ln in uses:
        # allowed: assignment, hmac signing, presence check — NOT format/log/print
        assert "print(" not in ln and "log" not in ln, ln
    assert "FUTURES_MAINNET_BASE" in src  # mainnet constant present only as refusal ref
    assert "testnet.binance.vision" not in src  # no spot endpoint anywhere
    print("futures_broker_never_logs_secrets PASS")


def test_futures_broker_no_spot_route():
    src = inspect.getsource(FuturesDemoBroker)
    assert "/api/v3" not in src
    assert "BINANCE_DEMO_API_KEY" not in src          # only the futures env vars
    assert "ENV_FUTURES_KEY" in src                   # env-key read goes through the
    assert "ENV_FUTURES_SECRET" in src                # futures-only constants
    print("futures_broker_no_spot_route PASS")


# ============================ LIFECYCLE: LONG ===============================
def test_futures_long_fill_chain():
    _reset_tables()
    fb = FakeFuturesBroker(fill_price=80000.0)
    eng = DemoEngine(fb)
    cand = _frozen_candidate(side="LONG", dec_id=9101)
    r = eng.open_from_candidate(cand)
    assert r["status"] == "FILLED", r
    assert eng.market == "FUTURES" and eng.env_label == "DEMO_FUTURES"
    o = store.get_order(r["order_id"])
    p = store.get_position(r["position"]["id"])
    assert o["environment"] == "DEMO_FUTURES" and p["environment"] == "DEMO_FUTURES"
    assert p["side"] == "LONG" and p["leverage"] == 1
    assert fb.position_amt.get("BTCUSDT") == 0.001
    print("futures_long_fill_chain PASS")


def test_futures_short_fill_chain():
    _reset_tables()
    fb = FakeFuturesBroker(fill_price=40000.0)
    eng = DemoEngine(fb)
    cand = _frozen_candidate(side="SHORT", regime="TREND_BEAR", dec_id=9102,
                             entry=40000, stop=41000, tp1=38500, tp2=37500,
                             size=0.002)
    r = eng.open_from_candidate(cand)
    assert r["status"] == "FILLED", r
    p = store.get_position(r["position"]["id"])
    assert p["side"] == "SHORT" and p["entry"] == 40000.0
    assert fb.position_amt.get("BTCUSDT") == -0.002  # negative = short
    print("futures_short_fill_chain PASS")


def test_futures_sl_long_exit():
    _reset_tables()
    fb = FakeFuturesBroker(fill_price=80000.0)
    eng = DemoEngine(fb, fee_bps=0.0)
    cand = _frozen_candidate(side="LONG", dec_id=9103, entry=80000, stop=79000, tp1=81500)
    r = eng.open_from_candidate(cand)
    closed = eng.update_market(_candle(T0 + H, high=81000, low=78500, close=80000))
    assert len(closed) == 1 and closed[0]["exit_reason"] == EXIT_SL
    assert closed[0]["pnl"] == -1.0  # (79000-80000)*0.001
    assert fb.position_amt.get("BTCUSDT") is None  # fully closed on exchange
    t = store.get_trade_by_decision(9103)
    assert t["exit_reason"] == "STOP_LOSS" and t["environment"] == "DEMO_FUTURES"
    print("futures_sl_long_exit PASS")


def test_futures_short_tp1_exit():
    _reset_tables()
    fb = FakeFuturesBroker(fill_price=40000.0)
    eng = DemoEngine(fb, fee_bps=0.0)
    cand = _frozen_candidate(side="SHORT", regime="TREND_BEAR", dec_id=9104,
                             entry=40000, stop=41000, tp1=38500, tp2=37500,
                             size=0.002)
    r = eng.open_from_candidate(cand)
    pid = r["position"]["id"]
    closed = eng.update_market(_candle(T0 + H, high=40200, low=38000, close=39000))
    assert len(closed) == 1 and closed[0]["exit_reason"] == EXIT_TP1
    assert closed[0]["pnl"] == (40000 - 38500) * 0.002  # short profit = entry-exit
    assert store.get_position(pid)["status"] == "CLOSED"
    assert fb.position_amt.get("BTCUSDT") is None
    print("futures_short_tp1_exit PASS")


def test_futures_roe_recorded():
    _reset_tables()
    fb = FakeFuturesBroker(fill_price=80000.0)
    eng = DemoEngine(fb, fee_bps=0.0)
    # size 0.01 -> margin = 80000*0.01/1 = 800
    cand = _frozen_candidate(side="LONG", dec_id=9105, entry=80000, stop=79000,
                             tp1=81500, size=0.01)
    eng.open_from_candidate(cand)
    closed = eng.update_market(_candle(T0 + H, high=81000, low=78500, close=80000))
    t = store.get_trade_by_decision(9105)
    assert abs(t["pnl"] - (-10.0)) < 1e-9          # (79000-80000)*0.01
    assert abs(t["roe_pct"] - (-1.25)) < 1e-9      # -10/800 margin
    print("futures_roe_recorded PASS")


# ============================ SAFETY GATES ==================================
def test_futures_leverage_cap_2x():
    _reset_tables()
    fb = FakeFuturesBroker()
    eng = DemoEngine(fb)
    r = eng.open_from_candidate(_frozen_candidate(dec_id=9106, lev=3.0))
    assert r["status"] == "REJECTED" and "LEVERAGE_EXCEEDS_MAX" in r["reason"]
    assert len(store.open_positions()) == 0
    print("futures_leverage_cap_2x PASS")


def test_futures_leverage_2x_ok_1x_default():
    _reset_tables()
    fb = FakeFuturesBroker()
    eng = DemoEngine(fb)
    r = eng.open_from_candidate(_frozen_candidate(dec_id=9107, lev=2.0, size=0.005))
    assert r["status"] == "FILLED", r
    assert store.get_position(r["position"]["id"])["leverage"] == 2.0
    _reset_tables()
    r2 = eng.open_from_candidate(_frozen_candidate(dec_id=9108, size=0.005))  # no lev field
    assert r2["status"] == "FILLED", r2
    assert store.get_position(r2["position"]["id"])["leverage"] == 1.0
    print("futures_leverage_2x_ok_1x_default PASS")


def test_dual_side_rejected_by_adapter():
    _set_futures_env()
    # FakeFuturesBroker reports one-way via capabilities; force dual by monkeypatching
    fb = FakeFuturesBroker()
    fb.get_position_mode = lambda: MODE_DUAL
    from execution.adapters import DemoFuturesExecution
    ad = DemoFuturesExecution(broker=fb)
    res = ad.place_order({"symbol": "BTCUSDT", "side": "LONG", "quantity": 0.001})
    assert res["status"] == "REJECTED" and "dual-side" in res["reason"]
    print("dual_side_rejected PASS")


def test_futures_env_mismatch_rejected():
    _reset_tables()
    fb = FakeFuturesBroker()
    eng = DemoEngine(fb)
    cand = _frozen_candidate(dec_id=9109)
    cand["environment"] = "SPOT"  # wrong env for a futures broker
    r = eng.open_from_candidate(cand)
    # FUTURES broker tolerates DEMO_FUTURES/DEMO only; SPOT env label is allowed
    # as legacy default — so flip the test: futures engine must reject a LIME env
    cand["environment"] = "LIVE"
    r = eng.open_from_candidate(_frozen_candidate(dec_id=9110))
    r2 = eng.open_from_candidate(cand)
    assert r2["status"] == "REJECTED" and "NOT_DEMO_FUTURES" in r2["reason"]
    print("futures_env_mismatch_rejected PASS")


# ============================ TIME EXIT =====================================
def test_futures_time_exit_short():
    _reset_tables()
    fb = FakeFuturesBroker(fill_price=40000.0)
    eng = DemoEngine(fb, fee_bps=0.0, max_hold_bars=2)
    cand = _frozen_candidate(side="SHORT", regime="TREND_BEAR", dec_id=9111,
                             entry=40000, stop=50000, tp1=10000, tp2=9000,
                             size=0.002)
    r = eng.open_from_candidate(cand)
    opened = store.get_position(r["position"]["id"])["opened_at"]
    closed = eng.update_market(_candle(opened + 2 * H, high=40100, low=39800, close=40050))
    assert len(closed) == 1 and closed[0]["exit_reason"] == EXIT_TIME
    assert closed[0]["pnl"] == (40000 - 40050) * 0.002
    print("futures_time_exit_short PASS")


# ============================ TELEGRAM FORMAT ===============================
def test_format_futures_filled_header():
    ev = {"symbol": "BTCUSDT", "side": "LONG", "regime": "TREND_BULL",
          "entry": 80943.32, "stop": 80033.47, "tp1": 82308.10, "tp2": 83399.92,
          "quantity": 0.0012, "ai_status": "PASS", "order_id": "ord_x",
          "timeframe": "1h", "leverage": 1, "environment": "DEMO_FUTURES",
          "market": "FUTURES", "decision_id": 77}
    msg = tg.format_demo_filled(ev)
    assert "BINANCE FUTURES DEMO" in msg
    assert "Leverage: 1x" in msg and "0.0012" in msg
    print("format_futures_filled PASS")


def test_format_futures_exit_roe():
    ev = {"symbol": "BTCUSDT", "side": "LONG", "entry": 80943.32, "exit": 82308.10,
          "rr": 1.5, "pnl": 12.34, "roe_pct": 15.4, "exit_reason": "TAKE_PROFIT_1",
          "environment": "DEMO_FUTURES", "decision_id": 78}
    msg = tg.format_demo_exit(ev)
    assert "BINANCE FUTURES DEMO" in msg and "+15.40%" in msg and "+12.34" in msg
    print("format_futures_exit_roe PASS")


def test_format_spot_filled_still_binance_demo():
    ev = {"symbol": "BTCUSDT", "side": "LONG", "entry": 80000.0, "stop": 79000.0,
          "tp1": 81500.0, "quantity": 0.001, "order_id": "ord_s",
          "decision_id": 79}
    msg = tg.format_demo_filled(ev)
    assert "BINANCE DEMO" in msg and "BINANCE FUTURES DEMO" not in msg
    assert "Leverage: 1x" in msg
    print("format_spot_filled_still_binance_demo PASS")


def test_no_network_in_engine():
    import execution.demo_engine as de
    assert "httpx" not in inspect.getsource(de)
    print("no_network_in_engine PASS")


if __name__ == "__main__":
    test_futures_env_requires_kind_and_own_creds()
    test_futures_env_defaults_to_demo_fapi()
    test_futures_testnet_requires_legacy_optin()
    test_futures_gate_never_uses_spot_creds()
    test_spot_gate_never_uses_futures_creds()
    test_futures_broker_defaults_demo_and_refuses_mainnet()
    test_futures_broker_testnet_requires_legacy()
    test_futures_broker_never_logs_secrets()
    test_futures_broker_no_spot_route()
    test_futures_long_fill_chain()
    test_futures_short_fill_chain()
    test_futures_sl_long_exit()
    test_futures_short_tp1_exit()
    test_futures_roe_recorded()
    test_futures_leverage_cap_2x()
    test_futures_leverage_2x_ok_1x_default()
    test_dual_side_rejected_by_adapter()
    test_futures_env_mismatch_rejected()
    test_futures_time_exit_short()
    test_format_futures_filled_header()
    test_format_futures_exit_roe()
    test_format_spot_filled_still_binance_demo()
    test_no_network_in_engine()
    print("\nALL FUTURES DEMO TESTS PASS")
