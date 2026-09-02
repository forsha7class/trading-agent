from __future__ import annotations
import time
from storage.models import ValidationResult

TF_MS = {"1m":60_000,"3m":180_000,"5m":300_000,"15m":900_000,"30m":1_800_000,"1h":3_600_000,"2h":7_200_000,"4h":14_400_000,"6h":21_600_000,"8h":28_800_000,"12h":43_200_000,"1d":86_400_000,"3d":259_200_000,"1w":604_800_000}

def validate_candles(candles: list[dict], symbol: str | None=None, timeframe: str | None=None, now_ms: int | None=None) -> ValidationResult:
    if not candles:
        return ValidationResult(False,"EMPTY", {"count":0})
    now_ms = now_ms or int(time.time()*1000)
    tf = timeframe or candles[0].get("timeframe","1h")
    interval = TF_MS.get(tf, 3_600_000)
    # infer symbol if not given
    exp_sym = symbol or candles[0].get("symbol")

    # checks
    seen=set()
    for i,c in enumerate(candles):
        # missing values
        for k in ("open","high","low","close","volume","open_time","close_time"):
            if k not in c or c[k] is None:
                return ValidationResult(False,"MISSING_VALUE", {"index":i,"field":k})
            if k in ("open","high","low","close","volume") and not isinstance(c[k],(int,float)):
                return ValidationResult(False,"MISSING_VALUE", {"index":i,"field":k})
        # symbol mismatch
        if exp_sym and c.get("symbol") and c["symbol"]!=exp_sym:
            return ValidationResult(False,"SYMBOL_MISMATCH", {"index":i,"expected":exp_sym,"got":c["symbol"]})
        # impossible OHLC
        if c["high"] < c["low"] or c["high"] < c["open"] or c["high"] < c["close"] or c["low"] > c["open"] or c["low"] > c["close"]:
            return ValidationResult(False,"IMPOSSIBLE_OHLC", {"index":i,"candle":c})
        if c["open"]<=0 or c["high"]<=0 or c["low"]<=0 or c["close"]<=0:
            return ValidationResult(False,"IMPOSSIBLE_OHLC", {"index":i,"non_positive":True})
        if c["close_time"] <= c["open_time"]:
            return ValidationResult(False,"IMPOSSIBLE_OHLC", {"index":i,"close_time<=open_time":True})
        # duplicate
        key=c["open_time"]
        if key in seen:
            return ValidationResult(False,"DUPLICATE", {"index":i,"open_time":key})
        seen.add(key)
        # out-of-order
        if i>0 and c["open_time"] <= candles[i-1]["open_time"]:
            return ValidationResult(False,"OUT_OF_ORDER", {"index":i})
        # optional: gap detection as missing candle (strict: gap > 1.5*interval)
        if i>0:
            gap=c["open_time"]-candles[i-1]["open_time"]
            if gap > interval*1.5:
                return ValidationResult(False,"MISSING_CANDLE", {"index":i,"gap_ms":gap,"expected_ms":interval})

    # stale: last close_time older than now-2*interval
    last_close = candles[-1]["close_time"]
    if last_close < now_ms - 2*interval:
        return ValidationResult(False,"STALE", {"last_close":last_close,"now":now_ms,"interval":interval})

    # clock skew: data in future
    if candles[-1]["open_time"] > now_ms + 60_000:
        return ValidationResult(False,"FUTURE_TIMESTAMP", {"open_time":candles[-1]["open_time"]})

    return ValidationResult(True,"OK", {"count":len(candles),"timeframe":tf})
