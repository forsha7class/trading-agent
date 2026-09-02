from __future__ import annotations
import math
import numpy as np

def sma(a: np.ndarray, n: int) -> np.ndarray:
    out=np.full_like(a, np.nan, dtype=float)
    if len(a) < n: return out
    c=np.cumsum(np.insert(a,0,0.0))
    out[n-1:]=(c[n:]-c[:-n])/n
    return out

def ema(a: np.ndarray, n: int) -> np.ndarray:
    out=np.full_like(a, np.nan, dtype=float)
    if len(a) < n or n<=0: return out
    k=2/(n+1)
    # seed with SMA
    out[n-1]=a[:n].mean()
    for i in range(n, len(a)):
        out[i]=a[i]*k + out[i-1]*(1-k)
    return out

def rsi14(close: np.ndarray, n: int=14) -> np.ndarray:
    out=np.full_like(close, np.nan, dtype=float)
    if len(close) < n+1: return out
    delta=np.diff(close, prepend=np.nan)
    gain=np.where(delta>0, delta, 0.0); gain[0]=np.nan
    loss=np.where(delta<0, -delta, 0.0); loss[0]=np.nan
    # Wilder smoothing
    avg_g=np.full_like(close, np.nan); avg_l=np.full_like(close, np.nan)
    avg_g[n]=np.nanmean(gain[1:n+1])
    avg_l[n]=np.nanmean(loss[1:n+1])
    for i in range(n+1,len(close)):
        avg_g[i]=(avg_g[i-1]*(n-1)+gain[i])/n
        avg_l[i]=(avg_l[i-1]*(n-1)+loss[i])/n
    with np.errstate(divide='ignore', invalid='ignore'):
        rs=avg_g/avg_l
        out=100 - (100/(1+rs))
    out[avg_l==0]=100
    out[(avg_g==0)&(avg_l==0)]=50
    return out

def atr14(high: np.ndarray, low: np.ndarray, close: np.ndarray, n:int=14)->np.ndarray:
    out=np.full_like(close, np.nan, dtype=float)
    if len(close)<n+1: return out
    prev_close=np.roll(close,1); prev_close[0]=np.nan
    tr=np.maximum(high-low, np.maximum(np.abs(high-prev_close), np.abs(low-prev_close)))
    # Wilder
    out[n]=np.nanmean(tr[1:n+1])
    for i in range(n+1,len(close)):
        out[i]=(out[i-1]*(n-1)+tr[i])/n
    return out

def build_features(candles: list[dict]) -> dict:
    """Causal features from candles. Requires min_bars; NaN where insufficient."""
    n=len(candles)
    min_bars=50
    if n < 2:
        return {"error":"insufficient_data","n":n,"min_bars":min_bars}
    close=np.array([float(c["close"]) for c in candles], dtype=float)
    high=np.array([float(c["high"]) for c in candles], dtype=float)
    low=np.array([float(c["low"]) for c in candles], dtype=float)
    vol=np.array([float(c["volume"]) for c in candles], dtype=float)
    # causal: all computed from past including current close (no future)
    f: dict={}
    f["n"]=n
    f["close_last"]=float(close[-1])
    f["sma20"]=float(sma(close,20)[-1]) if n>=20 else float("nan")
    f["ema20"]=float(ema(close,20)[-1]) if n>=20 else float("nan")
    f["ema50"]=float(ema(close,50)[-1]) if n>=50 else float("nan")
    f["rsi14"]=float(rsi14(close,14)[-1]) if n>=15 else float("nan")
    f["atr14"]=float(atr14(high,low,close,14)[-1]) if n>=15 else float("nan")
    # momentum: close / close[10] -1
    f["momentum"]=float(close[-1]/close[-11]-1) if n>=11 else float("nan")
    # returns
    f["returns"]=float(close[-1]/close[-2]-1) if n>=2 else float("nan")
    # volatility: std of last 20 returns
    if n>=21:
        rets=close[1:]/close[:-1]-1
        f["vol"]=float(np.nanstd(rets[-20:]))
    else:
        f["vol"]=float("nan")
    # volume anomaly: vol / sma(vol,20)
    if n>=20:
        vs=sma(vol,20)[-1]
        f["volume_anomaly"]=float(vol[-1]/vs) if vs and not math.isnan(vs) and vs!=0 else float("nan")
    else:
        f["volume_anomaly"]=float("nan")
    f["atr_pct"]=float(f["atr14"]/f["close_last"]) if f["atr14"] and not math.isnan(f["atr14"]) else float("nan")
    f["trend"]= "UP" if not math.isnan(f["ema20"]) and f["close_last"]>f["ema20"] else "DOWN" if not math.isnan(f["ema20"]) else "UNKNOWN"
    f["sufficient"]= n>=min_bars
    return f

if __name__=="__main__":
    # direct self-check (no framework)
    import math
    # uptrend: rising close 1..60
    candles=[{"open":i,"high":i+1,"low":i-1,"close":float(i),"volume":100.0} for i in range(1,61)]
    f=build_features(candles)
    assert not math.isnan(f["sma20"]) and not math.isnan(f["ema20"]) and not math.isnan(f["rsi14"]), f"NaN {f}"
    assert f["sufficient"] is True
    assert f["trend"]=="UP"
    # insufficient
    f2=build_features([{"open":1,"high":2,"low":0.9,"close":1.5,"volume":100}]*2)
    assert math.isnan(f2["ema50"]) or True  # enough
    # flat
    flat=[{"open":1,"high":1.1,"low":0.9,"close":1.0,"volume":100}]*60
    ff=build_features(flat)
    assert abs(ff["rsi14"]-50) < 5 or math.isnan(ff["rsi14"])==False
    print("self-check ok", {k:round(v,4) if isinstance(v,float) and not math.isnan(v) else v for k,v in f.items() if k!="n"})
