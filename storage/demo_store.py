"""DEMO lifecycle persistence — orders/positions/trades/events rows (task §10).

One row per entity; `decision_id` UNIQUE on orders/positions/trades guarantees a
single lifecycle chain per decision (never duplicated rows). demo_events carries
UNIQUE(decision_id, event_type) so one lifecycle event -> one Telegram message.

All functions are pure sqlite via storage.database.get_db(). No credentials,
no network, no Telegram here.
"""
from __future__ import annotations
import time, uuid
from storage.database import get_db


def _now_ms() -> int:
    return int(time.time() * 1000)


def _oid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---- orders ----------------------------------------------------------------
def insert_demo_order(o: dict) -> dict:
    db = get_db()
    order_id = o.get("id") or _oid("ord")
    db.execute(
        "INSERT OR IGNORE INTO demo_orders("
        "id,decision_id,signal_id,symbol,side,requested_qty,executed_qty,"
        "requested_price,executed_price,stop,tp1,tp2,status,strategy_id,"
        "strategy_version,regime,risk_engine,ai_status,environment,created_at,"
        "opened_at,closed_at,reject_reason,leverage)"
        " VALUES(:id,:decision_id,:signal_id,:symbol,:side,:requested_qty,"
        ":executed_qty,:requested_price,:executed_price,:stop,:tp1,:tp2,:status,"
        ":strategy_id,:strategy_version,:regime,:risk_engine,:ai_status,"
        ":environment,:created_at,:opened_at,:closed_at,:reject_reason,:leverage)",
        {"id": order_id, "decision_id": o.get("decision_id"), "signal_id": o.get("signal_id"),
         "symbol": o.get("symbol"), "side": o.get("side"),
         "requested_qty": o.get("requested_qty"), "executed_qty": o.get("executed_qty", 0),
         "requested_price": o.get("requested_price"), "executed_price": o.get("executed_price"),
         "stop": o.get("stop"), "tp1": o.get("tp1"), "tp2": o.get("tp2"),
         "status": o.get("status", "NEW"),
         "strategy_id": o.get("strategy_id"), "strategy_version": o.get("strategy_version"),
         "regime": o.get("regime"), "risk_engine": o.get("risk_engine"),
         "ai_status": o.get("ai_status"), "environment": o.get("environment", "DEMO"),
         "created_at": o.get("created_at", _now_ms()), "opened_at": o.get("opened_at"),
         "closed_at": o.get("closed_at"), "reject_reason": o.get("reject_reason"),
         "leverage": o.get("leverage", 1)})
    return get_order(order_id) or {"id": order_id}


def get_order(order_id: str) -> dict | None:
    r = get_db().execute("SELECT * FROM demo_orders WHERE id=?", (order_id,)).fetchone()
    return dict(r) if r else None


def get_order_by_decision(decision_id) -> dict | None:
    r = get_db().execute("SELECT * FROM demo_orders WHERE decision_id=?", (decision_id,)).fetchone()
    return dict(r) if r else None


def update_order(order_id: str, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    get_db().execute(f"UPDATE demo_orders SET {cols} WHERE id=?",
                     (*fields.values(), order_id))


# ---- positions -------------------------------------------------------------
def insert_demo_position(p: dict) -> dict:
    db = get_db()
    pid = p.get("id") or _oid("pos")
    db.execute(
        "INSERT OR IGNORE INTO demo_positions("
        "id,order_id,decision_id,symbol,side,entry,stop,tp1,tp2,size,open_qty,"
        "status,opened_at,closed_at,environment,leverage,margin,notional,"
        "liquidation_price,mark_price,unrealized_pnl)"
        " VALUES(:id,:order_id,:decision_id,:symbol,:side,:entry,:stop,:tp1,:tp2,"
        ":size,:open_qty,:status,:opened_at,:closed_at,:environment,:leverage,"
        ":margin,:notional,:liquidation_price,:mark_price,:unrealized_pnl)",
        {"id": pid, "order_id": p.get("order_id"), "decision_id": p.get("decision_id"),
         "symbol": p.get("symbol"), "side": p.get("side"), "entry": p.get("entry"),
         "stop": p.get("stop"), "tp1": p.get("tp1"), "tp2": p.get("tp2"),
         "size": p.get("size"), "open_qty": p.get("open_qty"),
         "status": p.get("status", "OPEN"),
         "opened_at": p.get("opened_at", _now_ms()), "closed_at": p.get("closed_at"),
         "environment": p.get("environment", "DEMO"),
         "leverage": p.get("leverage", 1),
         "margin": p.get("margin"), "notional": p.get("notional"),
         "liquidation_price": p.get("liquidation_price"),
         "mark_price": p.get("mark_price"), "unrealized_pnl": p.get("unrealized_pnl")})
    return get_position(pid) or {"id": pid}


def get_position(pid: str) -> dict | None:
    r = get_db().execute("SELECT * FROM demo_positions WHERE id=?", (pid,)).fetchone()
    return dict(r) if r else None


def get_position_by_decision(decision_id) -> dict | None:
    r = get_db().execute("SELECT * FROM demo_positions WHERE decision_id=?",
                         (decision_id,)).fetchone()
    return dict(r) if r else None


def open_positions() -> list[dict]:
    rows = get_db().execute("SELECT * FROM demo_positions WHERE status='OPEN'").fetchall()
    return [dict(r) for r in rows]


def update_position(pid: str, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    get_db().execute(f"UPDATE demo_positions SET {cols} WHERE id=?",
                     (*fields.values(), pid))


# ---- trades ----------------------------------------------------------------
def insert_demo_trade(t: dict) -> dict:
    db = get_db()
    tid = t.get("id") or _oid("trd")
    db.execute(
        "INSERT OR IGNORE INTO demo_trades("
        "id,position_id,order_id,decision_id,symbol,side,entry,exit_price,size,"
        "qty,pnl,fees,exit_reason,mae,mfe,opened_at,closed_at,environment,"
        "leverage,roe_pct,mark_price)"
        " VALUES(:id,:position_id,:order_id,:decision_id,:symbol,:side,:entry,"
        ":exit_price,:size,:qty,:pnl,:fees,:exit_reason,:mae,:mfe,:opened_at,"
        ":closed_at,:environment,:leverage,:roe_pct,:mark_price)",
        {"id": tid, "position_id": t.get("position_id"), "order_id": t.get("order_id"),
         "decision_id": t.get("decision_id"), "symbol": t.get("symbol"),
         "side": t.get("side"), "entry": t.get("entry"), "exit_price": t.get("exit_price"),
         "size": t.get("size"), "qty": t.get("qty"), "pnl": t.get("pnl"),
         "fees": t.get("fees"), "exit_reason": t.get("exit_reason"),
         "mae": t.get("mae"), "mfe": t.get("mfe"),
         "opened_at": t.get("opened_at", _now_ms()), "closed_at": t.get("closed_at"),
         "environment": t.get("environment", "DEMO"),
         "leverage": t.get("leverage", 1),
         "roe_pct": t.get("roe_pct"), "mark_price": t.get("mark_price")})
    return get_trade(tid) or {"id": tid}


def get_trade(tid: str) -> dict | None:
    r = get_db().execute("SELECT * FROM demo_trades WHERE id=?", (tid,)).fetchone()
    return dict(r) if r else None


def get_trade_by_decision(decision_id) -> dict | None:
    r = get_db().execute("SELECT * FROM demo_trades WHERE decision_id=?",
                         (decision_id,)).fetchone()
    return dict(r) if r else None


def close_trade(pid: str, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    get_db().execute(f"UPDATE demo_trades SET {cols} WHERE position_id=?",
                     (*fields.values(), pid))


def mark_entry_pnl(decision_id, **fields) -> None:
    """Record current mark/entry PnL on an OPEN position (futures observability).
    No-op when no OPEN position exists for the decision (never fabricates)."""
    p = get_position_by_decision(decision_id)
    if p is None or p.get("status") != "OPEN":
        return None
    if not fields:
        return p
    cols = ", ".join(f"{k}=?" for k in fields)
    get_db().execute(f"UPDATE demo_positions SET {cols} WHERE id=?",
                     (*fields.values(), p["id"]))
    return get_position(p["id"])


# ---- lifecycle events (dedup: decision_id + event_type) ---------------------
def mark_event(decision_id, event_type: str, telegram_sent: int = 0,
               telegram_error: str | None = None, meta: dict | None = None) -> bool:
    """Insert event row; returns False if (decision_id, event_type) already exists
    (dedup — one lifecycle event -> one Telegram message)."""
    import json
    cur = get_db().execute(
        "INSERT OR IGNORE INTO demo_events(decision_id,event_type,ts,telegram_sent,"
        "telegram_error,meta) VALUES(?,?,?,?,?,?)",
        (decision_id, event_type, _now_ms(), telegram_sent, telegram_error,
         json.dumps(meta or {}, default=str)))
    return cur.rowcount == 1


def event_exists(decision_id, event_type: str) -> bool:
    r = get_db().execute("SELECT 1 FROM demo_events WHERE decision_id=? AND event_type=?",
                         (decision_id, event_type)).fetchone()
    return r is not None


def demo_status() -> dict:
    db = get_db()
    def _c(q):
        return db.execute(q).fetchone()[0]
    return {
        "orders": _c("SELECT count(*) FROM demo_orders"),
        "open_positions": _c("SELECT count(*) FROM demo_positions WHERE status='OPEN'"),
        "closed_positions": _c("SELECT count(*) FROM demo_positions WHERE status='CLOSED'"),
        "trades": _c("SELECT count(*) FROM demo_trades"),
        "events": _c("SELECT count(*) FROM demo_events"),
    }
