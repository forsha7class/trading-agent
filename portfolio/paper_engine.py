"""Paper trading engine — LIVE DATA → decision → paper order → position → trade chain.

Single long-lived PaperEngine instance is expected: it holds the PaperPortfolio
in memory (SL/TP/TIME_EXIT resolution per candle) AND mirrors every state change
to sqlite (paper_orders / paper_positions / paper_trades) so a run is auditable
and resumable. No real execution anywhere.

Traceability (unchanged contract):
  decisions.id (persisted once by Coordinator.run) -> paper_orders.decision_id
  -> paper_positions.order_id -> paper_trades.decision_id (one row per position,
  OPEN then CLOSED update — persisted exactly once).
"""
from __future__ import annotations
import time, uuid
from storage.database import get_db, init_db, insert_paper_trade
from agents.coordinator import Coordinator
from portfolio.paper_portfolio import PaperPortfolio


def ensure_paper_tables():
    db = get_db()
    # NOTE: real schema lives in storage/database.init_db() (kept in one place so
    # create + migrate never diverge). Here we just guarantee they exist.
    init_db()
    return db


def _dec_dict(dec) -> dict:
    if isinstance(dec, dict):
        return dec
    if hasattr(dec, "to_dict"):
        return dec.to_dict()
    if hasattr(dec, "__dict__"):
        return dec.__dict__
    return {}


class PaperEngine:
    def __init__(self, equity: float = 10000, portfolio: PaperPortfolio | None = None):
        self.coordinator = Coordinator()
        self.portfolio = portfolio or PaperPortfolio(equity=equity)
        self.equity = float(self.portfolio.equity)
        init_db()
        ensure_paper_tables()
        self._reopen_open_positions()

    # ---- persistence helpers -------------------------------------------------
    def _insert_order(self, decision_id: int, dd: dict, symbol: str, side: str) -> str:
        order_id = str(uuid.uuid4())[:8]
        db = get_db()
        db.execute(
            "INSERT INTO paper_orders(id,decision_id,symbol,side,entry,stop,tp1,tp2,size,created_at,status)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,'CREATED')",
            (order_id, decision_id, symbol, side, dd.get("entry"), dd.get("stop"),
             dd.get("tp1"), dd.get("tp2"), dd.get("position_size"), int(time.time() * 1000)))
        return order_id

    def _persist_position(self, decision_id: int, order_id: str, pos: dict) -> None:
        db = get_db()
        db.execute(
            "INSERT INTO paper_positions(id,order_id,decision_id,symbol,side,entry,raw_entry,stop,tp1,tp2,size,opened_at,entry_bar,status)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'OPEN')",
            (pos["id"], order_id, decision_id, pos["symbol"], pos["side"], pos["entry"],
             pos["raw_entry"], pos.get("stop"), pos.get("tp1"), pos.get("tp2"),
             pos["size"], pos["opened_at"], pos["entry_bar"]))
        # one paper_trades row per position: OPEN at creation, CLOSED updated once below
        self._trade_id = insert_paper_trade({
            "decision_id": decision_id, "symbol": pos["symbol"], "side": pos["side"],
            "entry": pos["entry"], "stop": pos.get("stop"), "tp1": pos.get("tp1"),
            "tp2": pos.get("tp2"), "size": pos["size"], "status": "OPEN",
            "opened_at": pos["opened_at"],
        })

    def _reopen_open_positions(self) -> None:
        """Resume in-memory state from paper_positions rows (process restart / crash)."""
        try:
            rows = get_db().execute(
                "SELECT * FROM paper_positions WHERE status='OPEN'").fetchall()
        except Exception:
            return
        for r in rows:
            pos = {"id": r["id"], "symbol": r["symbol"], "side": r["side"],
                   "entry": r["entry"], "raw_entry": r["raw_entry"], "stop": r["stop"],
                   "tp1": r["tp1"], "tp2": r["tp2"], "size": r["size"],
                   "opened_at": r["opened_at"], "entry_bar": r["entry_bar"],
                   "status": "OPEN", "decision_id": r["decision_id"]}
            if any(p.get("symbol") == pos["symbol"] and p.get("side") == pos["side"]
                   and p.get("entry_bar") == pos["entry_bar"] for p in self.portfolio.positions):
                continue
            self.portfolio.positions.append(pos)

    # ---- tick: decide + open -------------------------------------------------
    def tick(self, candles: list[dict], symbol: str | None = None, timeframe: str | None = None) -> dict:
        """One decision tick from provided candles (causal). Coordinator persists the
        decision exactly once; this engine then opens a paper position ONLY if the
        decision is a RiskEngine-approved LONG/SHORT and no OPEN position already
        exists for this symbol (no duplicate stacking on the same signal/trend)."""
        symbol = symbol or candles[0].get("symbol", "BTCUSDT")
        timeframe = timeframe or candles[0].get("timeframe", "1h")
        dec = self.coordinator.run(symbol=symbol, timeframe=timeframe, candles=candles,
                                   equity=self.portfolio.equity,
                                   positions=len([p for p in self.portfolio.positions if p.get("status") == "OPEN"]))
        dd = _dec_dict(dec)
        decision = str(dd.get("decision") or dd.get("signal") or "NO_TRADE").upper()
        did = dd.get("id")
        if did is None:
            # Coordinator run() persisted the row; fetch it back by ts/symbol if needed
            try:
                row = get_db().execute(
                    "SELECT id FROM decisions WHERE symbol=? AND ts=? ORDER BY id DESC LIMIT 1",
                    (symbol, dd.get("ts") or dd.get("timestamp"))).fetchone()
                did = int(row["id"]) if row else None
            except Exception:
                did = None
        order_id = None
        pos = None
        if decision in ("LONG", "SHORT") and dd.get("entry") is not None and dd.get("stop") is not None:
            can_open = (not self._has_open_for_symbol(symbol)
                        and len(self.portfolio.open_positions) < self.portfolio.max_positions)
            if not can_open:
                decision = f"{decision}_NO_OPEN"  # duplicate prevention / capacity (no new order)
            else:
                order_id = self._insert_order(did, dd, symbol, decision)
                pos = self.portfolio.open_position(dd)
                if pos:
                    pos["id"] = str(uuid.uuid4())[:8]
                    pos["decision_id"] = did
                    # entry_bar from portfolio's current bar count is set inside open_position;
                    # reopen map uses decision_id as trade key
                    self._persist_position(did, order_id, pos)
                else:
                    # open refused (defensive) — drop the just-created order, keep state clean
                    try:
                        get_db().execute("DELETE FROM paper_orders WHERE id=?", (order_id,))
                    except Exception:
                        pass
                    order_id = None
                    decision = f"{decision}_NO_OPEN"
        return {"decision": dec, "decision_id": did, "order_id": order_id,
                "position": pos,
                "chain": {"decision_id": did, "order_id": order_id}}

    def update_market(self, candle: dict) -> list[dict]:
        """Feed the next candle to the portfolio; close any SL/TP1/TP2/TIME_EXIT hits
        and persist each completed trade EXACTLY once (CLOSED update on the OPEN row)."""
        closed = self.portfolio.update(candle)
        for rec in closed:
            self._close_trade_row(rec)
        self.equity = float(self.portfolio.equity)
        return closed

    def _close_trade_row(self, rec: dict) -> None:
        did = rec.get("decision_id")
        db = get_db()
        if did is not None:
            # update the matching OPEN row (there is exactly one per position)
            db.execute(
                "UPDATE paper_trades SET status='CLOSED', pnl=?, fees=?, hit=?, closed_at=? "
                "WHERE decision_id=? AND status='OPEN'",
                (rec.get("pnl"), rec.get("fees"), rec.get("hit"),
                 rec.get("closed_at"), did))
        # position row -> CLOSED
        pid = rec.get("id")
        if pid:
            db.execute("UPDATE paper_positions SET status='CLOSED' WHERE id=?", (pid,))
        # order row -> FILLED/CLOSED
        try:
            row = db.execute("SELECT order_id FROM paper_positions WHERE id=?", (pid,)).fetchone()
            if row:
                db.execute("UPDATE paper_orders SET status='CLOSED', opened_at=? WHERE id=?",
                           (rec.get("closed_at"), row["order_id"]))
        except Exception:
            pass

    # ---- helpers ---------------------------------------------------------------
    def _has_open_for_symbol(self, symbol: str) -> bool:
        return any(p.get("symbol") == symbol and p.get("status") == "OPEN"
                   for p in self.portfolio.positions)

    def status(self) -> dict:
        m = self.portfolio.metrics()
        return {"equity": self.portfolio.equity, "open": len(self.portfolio.positions),
                "closed": len(self.portfolio.closed), "metrics": m,
                "equity_curve": self.portfolio.equity_curve[-20:]}
