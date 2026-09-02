"""Paper trading engine — LIVE DATA → decision → paper order → traceable chain."""
from __future__ import annotations
import time, json, uuid
from storage.database import get_db, init_db, insert_decision, insert_paper_trade
from agents.coordinator import Coordinator
from portfolio.paper_portfolio import PaperPortfolio

def ensure_paper_tables():
    db=get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS paper_orders(
        id TEXT PRIMARY KEY, decision_id INTEGER, symbol TEXT, side TEXT,
        entry REAL, stop REAL, tp1 REAL, size REAL, created_at INTEGER, status TEXT
    );
    CREATE TABLE IF NOT EXISTS paper_positions(
        id TEXT PRIMARY KEY, order_id TEXT, symbol TEXT, side TEXT,
        entry REAL, stop REAL, tp1 REAL, size REAL, opened_at INTEGER, status TEXT,
        unrealized REAL
    );
    """)
    return db

class PaperEngine:
    def __init__(self, equity:float=10000):
        self.coordinator=Coordinator()
        self.portfolio=PaperPortfolio(equity=equity)
        self.equity=equity
        ensure_paper_tables()

    def tick(self, candles:list[dict], symbol:str|None=None, timeframe:str|None=None)->dict:
        """One decision tick from provided candles (causal). Returns decision + order/position."""
        symbol=symbol or candles[0].get("symbol","BTCUSDT")
        timeframe=timeframe or candles[0].get("timeframe","1h")
        dec=self.coordinator.run(symbol=symbol, timeframe=timeframe, candles=candles, equity=self.portfolio.equity)
        # chain ids
        dec_dict=dec.__dict__ if hasattr(dec,"__dict__") else dec
        did=insert_decision(dec_dict if isinstance(dec_dict,dict) else dec.__dict__)
        order_id=str(uuid.uuid4())[:8]
        # only create order if LONG/SHORT
        decision=str(getattr(dec,"decision", dec.get("decision") if isinstance(dec,dict) else "NO_TRADE"))
        if decision in ("LONG","SHORT"):
            # paper order
            entry=float(getattr(dec,"entry",0) or 0); stop=getattr(dec,"stop",None); tp1=getattr(dec,"tp1",None); size=getattr(dec,"position_size",None)
            from storage.database import get_db
            get_db().execute("INSERT INTO paper_orders(id,decision_id,symbol,side,entry,stop,tp1,size,created_at,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (order_id,did,symbol,decision,entry,stop,tp1,size,int(time.time()*1000),"CREATED"))
            # open via portfolio
            pos=self.portfolio.open_position(dec)
            # also insert paper_trades
            if pos:
                insert_paper_trade({"decision_id":did,"symbol":symbol,"side":decision,"entry":entry,"stop":stop,"tp1":tp1,"size":size,"status":"OPEN","opened_at":int(time.time()*1000)})
            return {"decision":dec,"decision_id":did,"order_id":order_id,"position":pos,"chain":{"decision_id":did,"order_id":order_id}}
        return {"decision":dec,"decision_id":did,"order_id":None,"position":None,"chain":{"decision_id":did}}

    def update_market(self, candle:dict):
        """Feed next candle to portfolio for SL/TP."""
        return self.portfolio.update(candle)

    def status(self)->dict:
        m=self.portfolio.metrics()
        return {"equity":self.portfolio.equity,"open":len(self.portfolio.positions),"closed":len(self.portfolio.closed),"metrics":m,"equity_curve":self.portfolio.equity_curve[-20:]}
