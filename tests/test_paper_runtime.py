"""Paper runtime regression tests — position open/hold/exit/dup/sequential/traceability.

Covers the paper-runtime fix: eligible LONG/SHORT create real paper positions when
accepted by RiskEngine, subsequent ticks update OPEN positions, SL/TP1/TP2/TIME_EXIT
close per the frozen paper spec, each completed trade persists EXACTLY once, and
decision_id -> order_id -> position -> trade chain is preserved.

These tests drive PaperPortfolio directly (pure exit semantics, deterministic) and
PaperEngine end-to-end (decision pipeline -> persisted chain) with isolated DB.
"""
import sys, time, sqlite3
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# isolated test DB (never the live trading.db)
import os
_TEST_DB = "/tmp/paper_runtime_test.db"
for suffix in ("", "-wal", "-shm"):
    p = _TEST_DB + suffix
    if os.path.exists(p):
        os.remove(p)
os.environ["DB_PATH"] = _TEST_DB

from storage.database import get_db, init_db
init_db()
DB = get_db()

from portfolio.paper_portfolio import PaperPortfolio
from portfolio.paper_engine import PaperEngine

H = 3600000
T0 = int(time.time()*1000)

def _candle(ts, high, low, close, sym="BTCUSDT"):
    return {"symbol": sym, "open": close, "high": high, "low": low, "close": close,
            "volume": 100.0, "open_time": ts, "close_time": ts + H - 1}

def _mk_dec(side="LONG", entry=100.0, stop=98.0, tp1=103.0, tp2=105.0, size=10.0, symbol="BTCUSDT"):
    return {"symbol": symbol, "signal": side, "decision": side, "entry": entry, "stop": stop,
            "tp1": tp1, "tp2": tp2, "position_size": size, "risk_pct": 0.005}

def _reset_tables():
    DB.execute("DELETE FROM paper_positions")
    DB.execute("DELETE FROM paper_orders")
    DB.execute("DELETE FROM paper_trades")

def _rows(table):
    return DB.execute(f"SELECT * FROM {table}").fetchall()

# ---------- PaperPortfolio exit semantics (deterministic) ----------
def test_open():
    pp = PaperPortfolio(equity=10000, fee=0.0, slippage=0.0)
    pos = pp.open_position(_mk_dec())
    assert pos is not None and pos["status"] == "OPEN"
    assert pos["side"] == "LONG" and pos["entry"] == 100.0
    assert pp.open_count == 1
    print("open PASS")

def test_hold():
    pp = PaperPortfolio(equity=10000, fee=0.0, slippage=0.0)
    pp.open_position(_mk_dec(entry=100, stop=98, tp1=103))
    # benign bar: no SL/TP touch -> position stays OPEN
    closed = pp.update(_candle(T0, high=101, low=99.5, close=100.5))
    assert closed == []
    assert pp.open_count == 1 and len(pp.closed) == 0
    print("hold PASS")

def test_tp_exit():
    pp = PaperPortfolio(equity=10000, fee=0.0, slippage=0.0)
    pp.open_position(_mk_dec(entry=100, stop=98, tp1=103))
    closed = pp.update(_candle(T0, high=104, low=99, close=103))
    assert len(closed) == 1 and closed[0]["hit"] == "TP1"
    assert closed[0]["pnl"] == (103 - 100) * 10
    assert pp.open_count == 0
    print("tp1_exit PASS")

def test_tp2_exit():
    pp = PaperPortfolio(equity=10000, fee=0.0, slippage=0.0)
    pp.open_position(_mk_dec(entry=100, stop=98, tp1=103, tp2=106))
    # tp2 is a full exit in the frozen spec (no partial scale-out)
    closed = pp.update(_candle(T0, high=107, low=99, close=106.5))
    assert len(closed) == 1 and closed[0]["hit"] == "TP2"
    assert closed[0]["pnl"] == (106 - 100) * 10
    print("tp2_exit PASS")

def test_sl_exit():
    pp = PaperPortfolio(equity=10000, fee=0.0, slippage=0.0)
    pp.open_position(_mk_dec(entry=100, stop=98, tp1=103))
    # both SL and TP touched in same bar -> SL wins (frozen rule)
    closed = pp.update(_candle(T0, high=104, low=97, close=102))
    assert len(closed) == 1 and closed[0]["hit"] == "SL"
    assert closed[0]["pnl"] == (98 - 100) * 10
    print("sl_exit PASS")

def test_time_exit():
    pp = PaperPortfolio(equity=10000, fee=0.0, slippage=0.0, max_hold_bars=3)
    pp.open_position(_mk_dec(entry=100, stop=95, tp1=999))  # tp unreachable
    for _ in range(2):
        pp.update(_candle(T0, high=101, low=99, close=100.2))  # 2 bars, held
    assert pp.open_count == 1
    closed = pp.update(_candle(T0, high=101, low=99, close=100.4))  # 3rd bar -> TIME_EXIT
    assert len(closed) == 1 and closed[0]["hit"] == "TIME_EXIT"
    assert closed[0]["exit"] == 100.4  # exits at bar close
    print("time_exit PASS")

# ---------- PaperEngine: end-to-end pipeline (coordinator -> risk -> persist) ----------
def _trend_candles(price0=50000.0, n=80, sym="BTCUSDT"):
    """Fresh 1h uptrend candles (decision pipeline can approve LONG)."""
    now = int(time.time()*1000)
    out = []
    for i in range(n):
        close = price0 + i * 10
        o = close
        out.append({"symbol": sym, "timeframe": "1h", "open": o, "high": o*1.002,
                    "low": o*0.998, "close": close, "volume": 100.0,
                    "open_time": now - (n - i) * H, "close_time": now - (n - i) * H + H - 1})
    return out

def test_engine_open_and_persist_chain():
    _reset_tables()
    pe = PaperEngine(equity=10000)
    res = pe.tick(_trend_candles(), symbol="BTCUSDT", timeframe="1h")
    assert res["position"] is not None and res["order_id"] is not None
    did = res["decision_id"]
    assert isinstance(did, int) and did > 0
    # chain: decision exists, order->decision, position->order, trade->decision
    o = DB.execute("SELECT * FROM paper_orders WHERE decision_id=?", (did,)).fetchone()
    p = DB.execute("SELECT * FROM paper_positions WHERE order_id=?", (o["id"],)).fetchone()
    t = DB.execute("SELECT * FROM paper_trades WHERE decision_id=? AND status='OPEN'", (did,)).fetchone()
    assert o is not None and p is not None and t is not None
    assert o["decision_id"] == did and p["order_id"] == o["id"] and t["decision_id"] == did
    # close it so later tests start with no OPEN position for this symbol
    pos = res["position"]
    bar = _trend_candles()[-1]["open_time"] + H
    pe.update_market(_candle(bar, high=pos["tp1"]*1.05, low=pos["entry"]*0.99, close=pos["tp1"]*1.01))
    assert pe.portfolio.open_count == 0
    print("engine_open_chain PASS did", did)

def test_engine_duplicate_prevention():
    _reset_tables()
    pe = PaperEngine(equity=10000)
    cs = _trend_candles()
    r1 = pe.tick(cs, symbol="BTCUSDT", timeframe="1h")
    assert r1["order_id"] is not None  # first LONG opens
    n_orders = len(_rows("paper_orders"))
    # second decision on same forming bar while position still OPEN -> skipped, no dup order
    r2 = pe.tick(cs, symbol="BTCUSDT", timeframe="1h")
    assert r2["order_id"] is None
    assert len(_rows("paper_orders")) == n_orders
    assert len(_rows("paper_trades")) == n_orders  # no extra OPEN trade rows
    # cleanup
    pos = r1["position"]
    bar = cs[-1]["open_time"] + H
    pe.update_market(_candle(bar, high=pos["tp1"]*1.05, low=pos["entry"]*0.99, close=pos["tp1"]*1.01))
    print("duplicate_prevention PASS")

def test_engine_close_persisted_once():
    _reset_tables()
    pe = PaperEngine(equity=10000)
    cs = _trend_candles()
    res = pe.tick(cs, symbol="BTCUSDT", timeframe="1h")
    did = res["decision_id"]
    pos = res["position"]
    entry = pos["entry"]
    stop = pos["stop"]
    # crash-restart simulation: new engine reopens the OPEN position from DB
    pe2 = PaperEngine(equity=10000)
    assert any(p["id"] == pos["id"] for p in pe2.portfolio.positions)
    # price collapses below stop -> SL close
    bar = cs[-1]["open_time"] + H
    closed = pe2.update_market(_candle(bar, high=entry*1.001, low=stop*0.99, close=stop*0.995))
    assert len(closed) == 1 and closed[0]["hit"] == "SL"
    # exactly one CLOSED trade row for this decision
    trades = DB.execute("SELECT * FROM paper_trades WHERE decision_id=?", (did,)).fetchall()
    assert len(trades) == 1, trades
    assert trades[0]["status"] == "CLOSED" and trades[0]["pnl"] is not None and trades[0]["hit"] == "SL"
    assert DB.execute("SELECT status FROM paper_positions WHERE id=?", (pos["id"],)).fetchone()["status"] == "CLOSED"
    # second feed of same data must not double-close
    closed2 = pe2.update_market(_candle(bar, high=entry*1.001, low=stop*0.99, close=stop*0.995))
    assert closed2 == []
    print("close_persisted_once PASS")

def test_multiple_sequential_signals():
    _reset_tables()
    pe = PaperEngine(equity=10000)
    # open LONG 1
    cs1 = _trend_candles(price0=50000)
    r = pe.tick(cs1, symbol="BTCUSDT", timeframe="1h")
    assert r["order_id"]
    # close it (TP: bar high above tp1 but below tp2 -> clean TP1)
    pos = r["position"]
    bar = cs1[-1]["open_time"] + H
    tp_hi = (pos["tp1"] + (pos["tp2"] or pos["tp1"]*1.5)) / 2  # between tp1 and tp2
    closed = pe.update_market(_candle(bar, high=tp_hi, low=pos["entry"]*0.995, close=tp_hi))
    assert len(closed) == 1 and closed[0]["hit"] == "TP1"
    # open LONG 2 on the next window (position now free)
    cs2 = _trend_candles(price0=pos["tp1"]*1.01)  # uptrend continuing higher
    r2 = pe.tick(cs2, symbol="BTCUSDT", timeframe="1h")
    assert r2["order_id"] and r2["decision_id"] != r["decision_id"]
    # two distinct decisions -> two distinct trades, both traceable
    n1 = len(DB.execute("SELECT * FROM paper_trades WHERE decision_id=?", (r["decision_id"],)).fetchall())
    n2 = len(DB.execute("SELECT * FROM paper_trades WHERE decision_id=?", (r2["decision_id"],)).fetchall())
    assert n1 == 1 and n2 == 1, (n1, n2)
    d1 = DB.execute("SELECT * FROM paper_trades WHERE decision_id=?", (r["decision_id"],)).fetchone()
    d2 = DB.execute("SELECT * FROM paper_trades WHERE decision_id=?", (r2["decision_id"],)).fetchone()
    assert d1 is not None and d2 is not None
    assert d1["status"] == "CLOSED" and d2["status"] == "OPEN"
    assert d1["id"] != d2["id"]
    # cleanup
    pos2 = r2["position"]
    bar2 = cs2[-1]["open_time"] + H
    pe.update_market(_candle(bar2, high=pos2["tp1"]*1.05, low=pos2["entry"]*0.99, close=pos2["tp1"]*1.01))
    print("sequential_signals PASS")

if __name__ == "__main__":
    test_open(); test_hold(); test_tp_exit(); test_tp2_exit(); test_sl_exit(); test_time_exit()
    test_engine_open_and_persist_chain(); test_engine_duplicate_prevention()
    test_engine_close_persisted_once(); test_multiple_sequential_signals()
    print("\nALL PAPER RUNTIME TESTS PASS")
