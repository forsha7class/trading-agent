from .base import Strategy, StrategySignal

class TrendStrategy(Strategy):
    name = "trend"
    def generate(self, market_state: dict) -> StrategySignal:
        f = (market_state or {}).get("features", market_state or {})
        tf = (market_state or {}).get("timeframe", "1h")
        ema20 = f.get("ema20"); ema50 = f.get("ema50")
        close = f.get("close", f.get("price")); atr = f.get("atr14", f.get("atr"))
        mom = f.get("momentum", 0) or 0
        rsi = f.get("rsi14", f.get("rsi"))
        if ema20 is None or ema50 is None or close is None:
            return StrategySignal(self.name, "NEUTRAL", 0.0, tf, close, None, ["missing ema/close"], [], "swing")
        try:
            e20=float(ema20); e50=float(ema50); c=float(close); a=float(atr) if atr else c*0.015
        except Exception:
            return StrategySignal(self.name, "NEUTRAL", 0.0, tf, close, None, ["invalid values"], [], "swing")
        sep = abs(e20-e50)/c if c else 0
        bull = e20>e50 and c>e20
        bear = e20<e50 and c<e20
        # strength from separation + momentum alignment
        base = min(1, sep*40)  # 0.5% sep => 0.2, 2% =>0.8
        mom_boost = max(0, min(0.3, abs(float(mom))*8)) if (bull and float(mom)>0) or (bear and float(mom)<0) else -0.1
        strength = max(0, min(1, base + mom_boost))
        if rsi is not None:
            try:
                rv=float(rsi)
                if (bull and rv>78) or (bear and rv<22): strength *= 0.7
            except Exception: pass
        if bull:
            return StrategySignal(self.name,"LONG",round(strength,3),tf,c,round(e50,6),[f"ema20>ema50 sep={sep:.3%}",f"mom={mom}"],[],"swing")
        if bear:
            return StrategySignal(self.name,"SHORT",round(strength,3),tf,c,round(e50,6),[f"ema20<ema50 sep={sep:.3%}",f"mom={mom}"],[],"swing")
        return StrategySignal(self.name,"NEUTRAL",round(min(0.3,base),3),tf,c,None,[f"no trend sep={sep:.3%}"],[f"ema20={e20:.2f} ema50={e50:.2f}"],"swing")
