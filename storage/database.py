from __future__ import annotations
import sqlite3, json, time
from pathlib import Path
from typing import Any

_conn: sqlite3.Connection | None = None

def _db_path() -> str:
    try:
        from config.settings import get_settings
        return get_settings().db_path
    except Exception:
        return "storage/trading.db"

def get_db(path: str | None = None) -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        try:
            _conn.execute("SELECT 1")
            return _conn
        except sqlite3.ProgrammingError:
            _conn=None
    p = Path(path or _db_path())
    # resolve relative to project root
    if not p.is_absolute():
        p = Path(__file__).parent.parent / p
    p.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(str(p), check_same_thread=False, isolation_level=None)
    _conn.execute("PRAGMA journal_mode=WAL;")
    _conn.execute("PRAGMA foreign_keys=ON;")
    _conn.row_factory = sqlite3.Row
    return _conn

def init_db(path: str | None = None) -> sqlite3.Connection:
    db = get_db(path)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS candles(
        symbol TEXT, timeframe TEXT, open REAL, high REAL, low REAL, close REAL,
        volume REAL, open_time INTEGER, close_time INTEGER,
        PRIMARY KEY(symbol,timeframe,open_time));
    CREATE TABLE IF NOT EXISTS features(
        symbol TEXT, timeframe TEXT, ts INTEGER,
        ema20 REAL, ema50 REAL, rsi14 REAL, atr14 REAL, sma20 REAL, momentum REAL, vol REAL,
        feature_version TEXT,
        PRIMARY KEY(symbol,timeframe,ts));
    CREATE TABLE IF NOT EXISTS regimes(
        symbol TEXT, timeframe TEXT, ts INTEGER, regime TEXT, confidence REAL, evidence TEXT, version TEXT,
        PRIMARY KEY(symbol,timeframe,ts));
    CREATE TABLE IF NOT EXISTS strategy_signals(
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, ts INTEGER, strategy TEXT, direction TEXT,
        strength REAL, entry REAL, invalidation REAL, evidence TEXT, version TEXT);
    CREATE TABLE IF NOT EXISTS decisions(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, symbol TEXT, timeframe TEXT, regime TEXT, signal TEXT,
        probability TEXT, entry REAL, stop REAL, tp1 REAL, tp2 REAL, position_size REAL, risk_pct REAL, rr REAL,
        evidence TEXT, counter_evidence TEXT, reason TEXT, decision TEXT, versions TEXT, data_ts INTEGER);
    CREATE TABLE IF NOT EXISTS paper_trades(
        id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id INTEGER REFERENCES decisions(id), symbol TEXT, side TEXT,
        entry REAL, stop REAL, tp1 REAL, size REAL, status TEXT, pnl REAL, fees REAL, opened_at INTEGER, closed_at INTEGER);
    CREATE TABLE IF NOT EXISTS system_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, module TEXT, level TEXT, message TEXT, meta TEXT);
    CREATE TABLE IF NOT EXISTS model_versions(
        version TEXT PRIMARY KEY, component TEXT, created_at INTEGER, meta TEXT);
    """)
    return db

def insert_candle(c: dict, timeframe: str="1h") -> None:
    db=get_db()
    db.execute("""INSERT OR REPLACE INTO candles(symbol,timeframe,open,high,low,close,volume,open_time,close_time)
        VALUES(:symbol,:timeframe,:open,:high,:low,:close,:volume,:open_time,:close_time)""",
        {"symbol":c["symbol"],"timeframe":c.get("timeframe",timeframe),"open":c["open"],"high":c["high"],"low":c["low"],"close":c["close"],"volume":c["volume"],"open_time":c["open_time"],"close_time":c["close_time"]})

def insert_decision(d: dict) -> int:
    db=get_db()
    # append-only: only INSERT
    cur=db.execute("""INSERT INTO decisions(ts,symbol,timeframe,regime,signal,probability,entry,stop,tp1,tp2,position_size,risk_pct,rr,evidence,counter_evidence,reason,decision,versions,data_ts) VALUES(:ts,:symbol,:timeframe,:regime,:signal,:probability,:entry,:stop,:tp1,:tp2,:position_size,:risk_pct,:rr,:evidence,:counter_evidence,:reason,:decision,:versions,:data_ts)""",
        {"ts":d.get("ts", d.get("timestamp", int(time.time()*1000))),"symbol":d.get("symbol"),"timeframe":d.get("timeframe"),"regime":d.get("regime"),"signal":d.get("signal"),
         "probability":json.dumps(d.get("probability",{})),"entry":d.get("entry"),"stop":d.get("stop"),"tp1":d.get("tp1"),"tp2":d.get("tp2"),
         "position_size":d.get("position_size"),"risk_pct":d.get("risk_pct"),"rr":d.get("rr"),
         "evidence":json.dumps(d.get("evidence",{})),"counter_evidence":json.dumps(d.get("counter_evidence",{})),"reason":d.get("reason",""),"decision":d.get("decision","NO_TRADE"),
         "versions":json.dumps(d.get("versions",{})),"data_ts":d.get("data_ts")})
    return int(cur.lastrowid or 0)

def insert_paper_trade(t: dict) -> int:
    db=get_db()
    cur=db.execute("""INSERT INTO paper_trades(decision_id,symbol,side,entry,stop,tp1,size,status,pnl,fees,opened_at,closed_at)
        VALUES(:decision_id,:symbol,:side,:entry,:stop,:tp1,:size,:status,:pnl,:fees,:opened_at,:closed_at)""",
        {"decision_id":t.get("decision_id"),"symbol":t.get("symbol"),"side":t.get("side"),"entry":t.get("entry"),"stop":t.get("stop"),"tp1":t.get("tp1"),
         "size":t.get("size"),"status":t.get("status","OPEN"),"pnl":t.get("pnl"),"fees":t.get("fees"),"opened_at":t.get("opened_at",int(time.time()*1000)),"closed_at":t.get("closed_at")})
    return int(cur.lastrowid or 0)

def log_event(module: str, level: str, message: str, meta: dict | None=None) -> None:
    db=get_db()
    db.execute("INSERT INTO system_events(ts,module,level,message,meta) VALUES(?,?,?,?,?)",
        (int(time.time()*1000),module,level,message,json.dumps(meta or {})))

# prevent UPDATE/DELETE on decisions via trigger (append-only)
def _append_only_trigger():
    db=get_db()
    db.executescript("""
    CREATE TRIGGER IF NOT EXISTS decisions_no_update BEFORE UPDATE ON decisions BEGIN SELECT RAISE(ABORT,'decisions append-only'); END;
    CREATE TRIGGER IF NOT EXISTS decisions_no_delete BEFORE DELETE ON decisions BEGIN SELECT RAISE(ABORT,'decisions append-only'); END;
    """)

# call on init
try:
    init_db()
    _append_only_trigger()
except Exception:
    pass
