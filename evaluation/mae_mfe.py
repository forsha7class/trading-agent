"""MAE/MFE per trade."""
from __future__ import annotations

def compute_mae_mfe(candles, entry_idx: int, entry: float, side: str, horizon:int=20, stop: float|None=None, tp: float|None=None):
    n=len(candles)
    mae=0; mfe=0; exit_reason="TIME_EXIT"; exit_price=None
    for j in range(entry_idx+1, min(n, entry_idx+1+horizon)):
        hi=float(candles[j]["high"]); lo=float(candles[j]["low"])
        if side=="LONG":
            # adverse is low, favorable high
            mae = max(mae, entry - lo)
            mfe = max(mfe, hi - entry)
            if stop is not None and lo <= stop: exit_reason="STOP_LOSS"; exit_price=stop; break
            if tp is not None and hi >= tp: exit_reason="TAKE_PROFIT"; exit_price=tp; break
        else:
            mae = max(mae, hi - entry)
            mfe = max(mfe, entry - lo)
            if stop is not None and hi >= stop: exit_reason="STOP_LOSS"; exit_price=stop; break
            if tp is not None and lo <= tp: exit_reason="TAKE_PROFIT"; exit_price=tp; break
    return {"mae":round(mae,2),"mfe":round(mfe,2),"exit_reason":exit_reason,"exit_price":exit_price}

def enrich_trades(candles, trades: list[dict], horizon:int=20):
    out=[]
    for t in trades:
        idx=t.get("bar",0); entry=t.get("entry"); side=t.get("side")
        mae=compute_mae_mfe(candles, idx, entry, side, horizon=horizon, stop=t.get("stop"), tp=t.get("tp"))
        nt=dict(t); nt.update(mae)
        nt["holding_bars"]=1  # placeholder
        out.append(nt)
    return out
