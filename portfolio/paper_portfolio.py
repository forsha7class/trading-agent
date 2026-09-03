"""Paper portfolio — simulates entry/SL/TP/fees/slippage."""
from __future__ import annotations
import time
try:
    from config.settings import FEES_BPS, SLIPPAGE_BPS
except ImportError:
    try:
        from trading_agent.config.settings import FEES_BPS, SLIPPAGE_BPS
    except Exception:
        FEES_BPS=0.0004; SLIPPAGE_BPS=0.0005

class PaperPortfolio:
    def __init__(self, equity: float=10000.0, initial_equity: float|None=None, fee: float|None=None, fees_bps: float|None=None, slippage: float|None=None, slippage_bps: float|None=None, max_positions:int=3, max_hold_bars:int=20, **kw):
        # alias handling: ponytail: unify naming when live execution added
        if initial_equity is not None: equity=initial_equity
        if kw.get("initial_equity") is not None: equity=kw["initial_equity"]
        if fees_bps is not None: fee=fees_bps
        if kw.get("fees_bps") is not None: fee=kw["fees_bps"]
        if slippage_bps is not None: slippage=slippage_bps
        if kw.get("slippage_bps") is not None: slippage=kw["slippage_bps"]
        if fee is None: fee=FEES_BPS
        if slippage is None: slippage=SLIPPAGE_BPS
        # also support config dict keys fee/slippage
        if kw.get("fee") is not None: fee=kw["fee"]
        if kw.get("slippage") is not None: slippage=kw["slippage"]
        self.initial_equity=float(equity)
        self.equity=float(equity)
        self.fee=float(fee); self.slippage=float(slippage); self.max_positions=int(max_positions)
        self.max_hold_bars=int(max_hold_bars)  # TIME_EXIT horizon (frozen spec: 20)
        self.positions:list[dict]=[]
        self.closed:list[dict]=[]
        self.trades=self.closed  # alias
        self.equity_curve=[self.equity]
        self._peak=self.equity
        self.max_drawdown=0.0
        self._bar_count=0  # bars since portfolio start; TIME_EXIT uses entry_bar

    @property
    def open_positions(self): return [p for p in self.positions if p.get("status")=="OPEN"]
    @property
    def open_count(self): return len(self.positions)
    @property
    def drawdown(self)->float:
        if not self.equity_curve: return 0.0
        peak=max(self.equity_curve)
        return (peak-self.equity)/peak if peak else 0.0

    def open_position(self, decision)->dict|None:
        d=decision if isinstance(decision, dict) else getattr(decision,"__dict__",{})
        # Decision dataclass -> dict
        if hasattr(decision,"signal") and not isinstance(decision, dict):
            d={"symbol":getattr(decision,"symbol",None),"signal":getattr(decision,"signal",None),"entry":getattr(decision,"entry",None),"stop":getattr(decision,"stop",None),"tp1":getattr(decision,"tp1",None),"tp2":getattr(decision,"tp2",None),"position_size":getattr(decision,"position_size",None),"risk_pct":getattr(decision,"risk_pct",None)}
        if len(self.positions)>=self.max_positions: return None
        side=str(d.get("signal",d.get("decision",""))).upper()
        if side not in ("LONG","SHORT"): return None
        entry=d.get("entry")
        if entry is None: return None
        entry=float(entry)
        size=d.get("position_size") or d.get("size")
        if size is None or float(size)<=0:
            stop=d.get("stop")
            sd=abs(entry-float(stop)) if stop is not None else entry*0.02
            size=self.equity*0.005/max(1e-9,sd)
        size=float(size)
        slip=entry*self.slippage*(1 if side=="LONG" else -1)
        eff_entry=entry+slip
        pos={"symbol":d.get("symbol","BTCUSDT"),"side":side,"entry":eff_entry,"raw_entry":entry,"stop":float(d["stop"]) if d.get("stop") is not None else None,"tp1":float(d["tp1"]) if d.get("tp1") is not None else None,"tp2":float(d["tp2"]) if d.get("tp2") is not None else None,"size":size,"opened_at":int(time.time()*1000),"entry_bar":self._bar_count,"status":"OPEN"}
        self.positions.append(pos)
        return pos

    def _resolve_exit(self, p:dict, high:float, low:float, close:float, bar_close_time:int)->tuple|None:
        """Frozen paper exit rules (per bar, SL checked first; SL wins if both touched).
        LONG: SL low<=stop, TP1 high>=tp1, TP2 high>=tp2. SHORT mirrored.
        TIME_EXIT: position held max_hold_bars bars -> close at bar close."""
        side=p["side"]
        if side=="LONG":
            if p.get("stop") is not None and low<=float(p["stop"]): return ("SL",float(p["stop"]))
            if p.get("tp2") is not None and high>=float(p["tp2"]): return ("TP2",float(p["tp2"]))
            if p.get("tp1") is not None and high>=float(p["tp1"]): return ("TP1",float(p["tp1"]))
        else:
            if p.get("stop") is not None and high>=float(p["stop"]): return ("SL",float(p["stop"]))
            if p.get("tp2") is not None and low<=float(p["tp2"]): return ("TP2",float(p["tp2"]))
            if p.get("tp1") is not None and low<=float(p["tp1"]): return ("TP1",float(p["tp1"]))
        if p.get("entry_bar") is not None and (self._bar_count - p["entry_bar"]) >= self.max_hold_bars:
            return ("TIME_EXIT", close)
        return None

    def update(self, candle:dict)->list[dict]:
        closed=[]
        high=float(candle.get("high",candle.get("h") or 0))
        low=float(candle.get("low",candle.get("l") or 0))
        close=float(candle.get("close",candle.get("c") or high))
        bar_ts=candle.get("close_time",int(time.time()*1000))
        sym=candle.get("symbol")
        # multi-symbol safety: a candle may only resolve positions of ITS symbol,
        # else a BTC position is SL/TP-triggered by an ETH candle (wrong prices)
        self._bar_count += 1
        for p in list(self.positions):
            if sym and p.get("symbol") and p["symbol"] != sym:
                continue
            hit_exit=self._resolve_exit(p, high, low, close, bar_ts)
            if not hit_exit: continue
            hit,exit_price=hit_exit
            if hit=="TIME_EXIT":
                eff_exit=close
            elif hit=="SL":
                # adverse slippage: LONG sells below stop, SHORT buys above stop
                eff_exit=exit_price-exit_price*self.slippage if p["side"]=="LONG" else exit_price+exit_price*self.slippage
            else:
                # TP fills at level (favorable); slight adverse on re-entry not modeled (frozen spec: eff_exit=exit)
                eff_exit=exit_price
            gross=(eff_exit-p["entry"])*p["size"] if p["side"]=="LONG" else (p["entry"]-eff_exit)*p["size"]
            fees=(abs(p["entry"]*p["size"])+abs(eff_exit*p["size"]))*self.fee
            net=gross-fees
            self.equity+=net
            self.equity_curve.append(self.equity)
            self._peak=max(self._peak,self.equity)
            dd=(self._peak-self.equity)/self._peak if self._peak else 0
            self.max_drawdown=max(self.max_drawdown,dd)
            rec={**p,"exit":eff_exit,"hit":hit,"pnl":net,"fees":fees,"closed_at":bar_ts,"status":"CLOSED"}
            self.closed.append(rec); self.positions.remove(p); closed.append(rec)
        if not closed: self.equity_curve.append(self.equity)
        # keep _peak tracking
        if self.equity>self._peak: self._peak=self.equity
        return closed
    # compatibility
    def metrics_summary(self): 
        if not self.closed: return {"trades":0,"win_rate":0,"profit_factor":0,"max_drawdown":self.drawdown,"pnl":self.equity-self.initial_equity}
        wins=[t for t in self.closed if t["pnl"]>0]; losses=[t for t in self.closed if t["pnl"]<=0]
        pf=sum(t["pnl"] for t in wins)/abs(sum(t["pnl"] for t in losses) or 1e-9)
        return {"trades":len(self.closed),"win_rate":len(wins)/len(self.closed),"profit_factor":pf,"max_drawdown":self.drawdown,"pnl":self.equity-self.initial_equity}
    def metrics(self): return self.metrics_summary()
    def get_metrics(self): return self.metrics_summary()

# MAE/MFE helpers added Phase3 (appended, not rewrite)
def _mae_mfe_for_position(pos, candles_window):
    # candles_window: list of candles after entry, used to compute excursions (simplified placeholder)
    return 0.0, 0.0
