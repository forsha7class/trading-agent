"""Reproducible historical dataset layer — OHLCV with metadata, dedup, gap detection."""
from __future__ import annotations
import time, json, sqlite3
from pathlib import Path
from ingestion.market_data import fetch_klines
from ingestion.validation import validate_candles, TF_MS
from storage.database import get_db, init_db

def ensure_dataset_tables():
    db=get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS datasets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT, timeframe TEXT,
        start_ts INTEGER, end_ts INTEGER,
        row_count INTEGER, source TEXT, downloaded_at INTEGER,
        validation TEXT, meta TEXT
    );
    """)
    return db

def fetch_history(symbol:str, timeframe:str, start_ms:int|None=None, end_ms:int|None=None, limit:int=1000)->list[dict]:
    """Paginated fetch — Binance klines max 1000 per call. If start/end None, fetch `limit` most recent."""
    out=[]
    if start_ms is None and end_ms is None:
        return fetch_klines(symbol, timeframe, limit=limit)
    # paginated by startTime
    cur=start_ms
    end=end_ms or int(time.time()*1000)
    import httpx, time as _time
    try:
        from config.settings import get_settings
        base=get_settings().binance_base.rstrip("/")
    except: base="https://api.binance.com"
    interval_ms=TF_MS.get(timeframe, 3_600_000)
    while cur < end:
        url=f"{base}/api/v3/klines"
        params={"symbol":symbol,"interval":timeframe,"limit":1000,"startTime":cur,"endTime":min(cur+1000*interval_ms, end)}
        r=httpx.get(url, params=params, timeout=20)
        r.raise_for_status()
        raw=r.json()
        if not raw: break
        from ingestion.market_data import _klines_to_candles
        batch=_klines_to_candles(symbol, timeframe, raw)
        out.extend(batch)
        # advance
        cur=batch[-1]["close_time"]+1
        if len(raw)<1000: break
        _time.sleep(0.2)
        if len(out)>10000: break
    return out

def store_dataset(candles:list[dict], symbol:str, timeframe:str, source:str="binance")->int:
    """Dedup, validate, insert candles, record metadata. Returns dataset id."""
    init_db(); ensure_dataset_tables()
    db=get_db()
    # dedup by open_time
    seen=set(); uniq=[]
    for c in sorted(candles, key=lambda x: x["open_time"]):
        if c["open_time"] not in seen:
            seen.add(c["open_time"]); uniq.append(c)
    # validate
    vr=validate_candles(uniq, symbol=symbol, timeframe=timeframe) if uniq else None
    # gap detection already in validate; also store gaps explicitly
    gaps=[]
    iv=TF_MS.get(timeframe, 3_600_000)
    for i in range(1,len(uniq)):
        gap=uniq[i]["open_time"]-uniq[i-1]["open_time"]
        if gap!=iv: gaps.append({"index":i,"gap_ms":gap,"expected_ms":iv})
    # insert candles
    from storage.database import insert_candle
    for c in uniq:
        insert_candle(c, timeframe=timeframe)
    start_ts=min(c["open_time"] for c in uniq) if uniq else 0
    end_ts=max(c["close_time"] for c in uniq) if uniq else 0
    meta=json.dumps({"gaps":gaps[:10],"gap_count":len(gaps)})
    val=json.dumps({"valid":bool(vr.valid) if vr else False,"reason":vr.reason if vr else "empty","details":vr.details if vr else {}})
    cur=db.execute("INSERT INTO datasets(symbol,timeframe,start_ts,end_ts,row_count,source,downloaded_at,validation,meta) VALUES(?,?,?,?,?,?,?,?,?)",
        (symbol,timeframe,start_ts,end_ts,len(uniq),source,int(time.time()*1000),val,meta))
    return int(cur.lastrowid)

def load_dataset(symbol:str, timeframe:str, start_ms:int|None=None, end_ms:int|None=None)->list[dict]:
    db=get_db()
    q="SELECT * FROM candles WHERE symbol=? AND timeframe=?"
    args=[symbol,timeframe]
    if start_ms is not None:
        q+=" AND open_time>=?"; args.append(start_ms)
    if end_ms is not None:
        q+=" AND open_time<=?"; args.append(end_ms)
    q+=" ORDER BY open_time ASC"
    rows=db.execute(q, args).fetchall()
    return [dict(r) for r in rows]

def dataset_metadata(dataset_id:int|None=None):
    db=get_db()
    if dataset_id:
        r=db.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        return dict(r) if r else None
    return [dict(r) for r in db.execute("SELECT * FROM datasets ORDER BY downloaded_at DESC").fetchall()]
