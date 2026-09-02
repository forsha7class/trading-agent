from __future__ import annotations
import time, asyncio
from typing import Any
import httpx

def _base() -> str:
    try:
        from config.settings import get_settings
        return get_settings().binance_base.rstrip("/")
    except Exception:
        return "https://api.binance.com"

def _klines_to_candles(symbol: str, interval: str, raw: list) -> list[dict]:
    out=[]
    for r in raw:
        # [open_time, open, high, low, close, volume, close_time, ...]
        out.append({"symbol":symbol,"timeframe":interval,"open":float(r[1]),"high":float(r[2]),"low":float(r[3]),"close":float(r[4]),"volume":float(r[5]),"open_time":int(r[0]),"close_time":int(r[6])})
    return out

def _retry_sleep(attempt:int, headers:dict)->float:
    ra = headers.get("retry-after")
    if ra:
        try: return float(ra)
        except: pass
    return min(2**attempt, 8)

# ---- sync ----
def fetch_klines(symbol:str, interval:str="1h", limit:int=100) -> list[dict]:
    url=f"{_base()}/api/v3/klines"
    for attempt in range(5):
        try:
            r=httpx.get(url, params={"symbol":symbol,"interval":interval,"limit":limit}, timeout=15)
            if r.status_code==429:
                time.sleep(_retry_sleep(attempt, r.headers)); continue
            r.raise_for_status()
            return _klines_to_candles(symbol, interval, r.json())
        except httpx.HTTPStatusError as e:
            if e.response.status_code==429:
                time.sleep(_retry_sleep(attempt, e.response.headers)); continue
            raise
    raise RuntimeError("fetch_klines 429 retries exhausted")

def fetch_ticker24(symbol:str)->dict:
    url=f"{_base()}/api/v3/ticker/24hr"
    for attempt in range(5):
        r=httpx.get(url, params={"symbol":symbol}, timeout=10)
        if r.status_code==429:
            time.sleep(_retry_sleep(attempt, r.headers)); continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("429")

def fetch_orderbook(symbol:str, limit:int=20)->dict:
    url=f"{_base()}/api/v3/depth"
    for attempt in range(5):
        r=httpx.get(url, params={"symbol":symbol,"limit":limit}, timeout=10)
        if r.status_code==429:
            time.sleep(_retry_sleep(attempt, r.headers)); continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("429")

# ---- async ----
async def fetch_klines_async(symbol:str, interval:str="1h", limit:int=100)->list[dict]:
    url=f"{_base()}/api/v3/klines"
    async with httpx.AsyncClient(timeout=15) as c:
        for attempt in range(5):
            r=await c.get(url, params={"symbol":symbol,"interval":interval,"limit":limit})
            if r.status_code==429:
                await asyncio.sleep(_retry_sleep(attempt, r.headers)); continue
            r.raise_for_status()
            return _klines_to_candles(symbol, interval, r.json())
    raise RuntimeError("429")

async def fetch_ticker24_async(symbol:str)->dict:
    url=f"{_base()}/api/v3/ticker/24hr"
    async with httpx.AsyncClient(timeout=10) as c:
        for attempt in range(5):
            r=await c.get(url, params={"symbol":symbol})
            if r.status_code==429:
                await asyncio.sleep(_retry_sleep(attempt, r.headers)); continue
            r.raise_for_status()
            return r.json()
    raise RuntimeError("429")

async def fetch_orderbook_async(symbol:str, limit:int=20)->dict:
    url=f"{_base()}/api/v3/depth"
    async with httpx.AsyncClient(timeout=10) as c:
        for attempt in range(5):
            r=await c.get(url, params={"symbol":symbol,"limit":limit})
            if r.status_code==429:
                await asyncio.sleep(_retry_sleep(attempt, r.headers)); continue
            r.raise_for_status()
            return r.json()
    raise RuntimeError("429")
