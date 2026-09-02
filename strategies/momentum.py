from .base import Strategy, StrategySignal
class MomentumStrategy(Strategy):
    name="momentum"
    def generate(self, market_state: dict) -> StrategySignal:
        f=(market_state or {}).get("features", market_state or {})
        tf=(market_state or {}).get("timeframe","1h")
        rsi=f.get("rsi14", f.get("rsi"))
        mom=f.get("momentum",0) or 0
        close=f.get("close", f.get("price"))
        atr=f.get("atr14", f.get("atr"))
        if rsi is None or close is None:
            return StrategySignal(self.name,"NEUTRAL",0.0,tf,close,None,["missing rsi/close"],[],"swing")
        try:
            rv=float(rsi); m=float(mom); c=float(close)
        except: return StrategySignal(self.name,"NEUTRAL",0.0,tf,close,None,["bad values"],[],"swing")
        a=float(atr) if atr else c*0.015
        if 55 <= rv <= 75 and m>0:
            s=min(1, 0.4 + (rv-55)/20*0.4 + min(0.3, abs(m)*5))
            return StrategySignal(self.name,"LONG",round(s,3),tf,c,round(c-2*a,6),[f"rsi={rv:.1f} mom={m:.4f}"],[],"swing")
        if 25 <= rv <= 45 and m<0:
            s=min(1, 0.4 + (45-rv)/20*0.4 + min(0.3, abs(m)*5))
            return StrategySignal(self.name,"SHORT",round(s,3),tf,c,round(c+2*a,6),[f"rsi={rv:.1f} mom={m:.4f}"],[],"swing")
        if rv>80 or rv<20:
            return StrategySignal(self.name,"NEUTRAL",0.2,tf,c,None,[f"rsi extreme {rv:.1f}"],[f"overextented"], "swing")
        return StrategySignal(self.name,"NEUTRAL",0.15,tf,c,None,[f"rsi={rv:.1f}"],[],"swing")
