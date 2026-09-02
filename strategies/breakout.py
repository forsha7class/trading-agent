from .base import Strategy, StrategySignal
class BreakoutStrategy(Strategy):
    name="breakout"
    def generate(self, market_state: dict) -> StrategySignal:
        f=(market_state or {}).get("features", market_state or {})
        tf=(market_state or {}).get("timeframe","1h")
        candles=(market_state or {}).get("candles",[])
        close=f.get("close", f.get("price"))
        atr=f.get("atr14", f.get("atr"))
        vol_anom=f.get("volume_anomaly", f.get("vol_anomaly",1))
        if close is None:
            return StrategySignal(self.name,"NEUTRAL",0.0,tf,None,None,["no close"],[],"scalp")
        try: c=float(close)
        except: return StrategySignal(self.name,"NEUTRAL",0.0,tf,close,None,["bad close"],[],"scalp")
        a=float(atr) if atr else c*0.015
        # need history for 20-bar high/low
        if isinstance(candles,list) and len(candles)>=20:
            closes=[float(x.get("close",x[4] if isinstance(x,list) else 0)) for x in candles[-20:-1]]
            hi=max(closes) if closes else c
            lo=min(closes) if closes else c
            is_break_up=c>hi
            is_break_dn=c<lo
            va=float(vol_anom) if vol_anom else 1
            if is_break_up:
                s=0.55 + min(0.3, (va-1)*0.2)
                if va>1.5: s+=0.1
                return StrategySignal(self.name,"LONG",round(min(1,s),3),tf,c,round(c-1.5*a,6),[f"breakout hi {hi:.2f} vol_anom={va:.2f}"],[],"scalp")
            if is_break_dn:
                s=0.55 + min(0.3, (va-1)*0.2)
                if va>1.5: s+=0.1
                return StrategySignal(self.name,"SHORT",round(min(1,s),3),tf,c,round(c+1.5*a,6),[f"breakdown lo {lo:.2f} vol_anom={va:.2f}"],[],"scalp")
        return StrategySignal(self.name,"NEUTRAL",0.1,tf,c,None,["no breakout"],[],"scalp")
