from .base import Strategy, StrategySignal
class MeanReversionStrategy(Strategy):
    name="mean_reversion"
    def generate(self, market_state: dict) -> StrategySignal:
        f=(market_state or {}).get("features", market_state or {})
        tf=(market_state or {}).get("timeframe","1h")
        regime=(market_state or {}).get("regime","UNCERTAIN")
        close=f.get("close", f.get("price"))
        sma=f.get("sma20", f.get("ema20"))
        atr=f.get("atr14", f.get("atr"))
        rsi=f.get("rsi14", f.get("rsi"))
        if close is None or sma is None:
            return StrategySignal(self.name,"NEUTRAL",0.0,tf,close,None,["missing close/sma"],[],"swing")
        try: c=float(close); s=float(sma); a=float(atr) if atr else c*0.015; rv=float(rsi) if rsi is not None else 50
        except: return StrategySignal(self.name,"NEUTRAL",0.0,tf,close,None,["bad values"],[],"swing")
        dist=(c-s)/a if a else 0
        # only strong signal in RANGE, weak elsewhere
        regime=str(regime).upper()
        weight=1.0 if regime=="RANGE" else 0.35
        if dist>2 and rv>65:
            strength=min(1,0.5+(dist-2)*0.2+(rv-65)/35*0.2)*weight
            return StrategySignal(self.name,"SHORT",round(strength,3),tf,c,round(c+2*a,6),[f"dist={dist:.2f}ATR rsi={rv:.1f} regime={regime}"],[f"counter-trend"], "swing")
        if dist<-2 and rv<35:
            strength=min(1,0.5+(-dist-2)*0.2+(35-rv)/35*0.2)*weight
            return StrategySignal(self.name,"LONG",round(strength,3),tf,c,round(c-2*a,6),[f"dist={dist:.2f}ATR rsi={rv:.1f} regime={regime}"],[f"counter-trend"],"swing")
        return StrategySignal(self.name,"NEUTRAL",0.1*weight,tf,c,None,[f"dist={dist:.2f}"],[],"swing")
