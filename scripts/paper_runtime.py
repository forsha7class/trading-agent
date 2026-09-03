"""Continuous PAPER/RESEARCH observation runtime (single scheduled window).

Runs the existing decision pipeline in PAPER mode on live 1h data at a fixed
interval, records observability for post-run analysis, and STOPs automatically at a
scheduled wall-clock time WITHOUT restarting.

This is an OPERATIONAL WRAPPER ONLY. It does not modify:
  strategy, RiskEngine, agents, model selection (DeepSeek-only via 9Router),
  paper execution, Telegram pipeline, AI contract, or any quant/frozen logic.

Model remains ts/thirty/deepseek-v4-flash. NO real order execution. NO retune.
Ordinary NO_TRADE -> 0 LLM calls (skip is active in Coordinator). Eligible
LONG/SHORT -> 1 DeepSeek review.

Usage:
  TRADING_STOP_UTC=<epoch_ms> python scripts/paper_runtime.py   (or edit STOP_UTC_MS)
Env: source ~/.hermes/.env for secrets.
"""
from __future__ import annotations
import os, sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.market_data import fetch_klines
from agents.llm import _reset_calls, CALLS
from agents import telegram_notifier as tg
from storage.database import get_db, init_db, log_event

# ---- config (single scheduled window) ----
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
TF = "1h"
TICK_INTERVAL_S = 3600  # 1 decision tick per hour (synchronized with new 1h bar)
# Automatic stop: 2026-09-03 22:00:00 UTC  (2026-09-04 06:00 WITA / Bali)
STOP_UTC_MS = int(os.getenv("TRADING_STOP_UTC", "1788472800000"))
MIN_UPDATE_INTERVAL_S = 3500  # never decision-tick the same 1h bar more than ~hourly
LOG_PATH = Path(__file__).parent.parent / "docs" / "paper_runtime_log.jsonl"

_run = {"start_ms": int(time.time()*1000), "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stop_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(STOP_UTC_MS/1000)),
        "symbols": SYMBOLS, "timeframe": TF, "model": "ts/thirty/deepseek-v4-flash",
        "mode": "PAPER/RESEARCH", "interval_s": TICK_INTERVAL_S,
        "ticks": [], "llm_calls": [], "errors": [], "telegram": []}


def _emit(rec: dict):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    _run["ticks"].append(rec)


def _decision_tick(engine, symbol: str) -> dict:
    """One PaperEngine tick on latest live 1h candles: reconcile (mark/close) any
    OPEN position against the newest completed bar first, then run the frozen
    decision pipeline and open a paper position if RiskEngine approves a LONG/SHORT
    and no position for this symbol is already OPEN (duplicate prevention)."""
    candles = fetch_klines(symbol, TF, limit=100)
    if len(candles) >= 2:
        # the last two bars: [newest closed bar, current forming bar]. Feed the
        # newest CLOSED bar to resolve SL/TP before deciding on the forming bar.
        closed_bar = candles[-2]
        engine.update_market({
            "symbol": symbol, "open": closed_bar["open"], "high": closed_bar["high"],
            "low": closed_bar["low"], "close": closed_bar["close"],
            "close_time": closed_bar["close_time"],
        })
    res = engine.tick(candles, symbol=symbol, timeframe=TF)
    dd = res["decision"]
    dd = dd.to_dict() if hasattr(dd, "to_dict") else (dd.__dict__ if hasattr(dd, "__dict__") else dd)
    dd = dd or {}
    decision = str((res.get("position") or {}).get("side") or dd.get("decision") or dd.get("signal") or "NO_TRADE").upper()
    # reflect skip decision so observability shows it was a signal but not a new entry
    if decision in ("LONG", "SHORT") and res.get("order_id") is None:
        decision = f"{decision}_NO_OPEN"
    return {
        "ts": int(time.time()*1000),
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "symbol": symbol, "decision": decision,
        "decision_id": res.get("decision_id"), "order_id": res.get("order_id"),
        "position_id": res.get("position", {}).get("id") if isinstance(res.get("position"), dict) else None,
        "reason": str(dd.get("reason") or ""),
        "regime": dd.get("regime"), "signal": dd.get("signal"),
        "rr": dd.get("rr"), "risk_pct": dd.get("risk_pct"),
        "entry": dd.get("entry"), "stop": dd.get("stop"), "tp1": dd.get("tp1"),
        "close": candles[-1]["close"] if candles else None,
    }


def _snapshot_llm_calls():
    """Copy accumulated raw usage metadata since last tick (reset not needed; we diff by count)."""
    # CALLS grows monotonically; we snapshot current and later diff via count in summary.
    return [{"ok": c.get("ok"), "model": c.get("model"), "usage": c.get("usage"),
             "credit": c.get("credit"), "ts": c.get("ts")} for c in CALLS]


def main():
    init_db()
    db = get_db()
    _reset_calls()
    tg._last_sent.clear()
    _run["llm_calls"] = _snapshot_llm_calls()
    # single long-lived paper engine: in-memory portfolio + DB mirror (SL/TP/TIME_EXIT)
    from portfolio.paper_engine import PaperEngine
    engine = PaperEngine(equity=10000)
    print(f"RUNTIME START {_run['start_utc']}", flush=True)
    print(f"STOP AT     {_run['stop_utc']} (UTC) — will not restart after", flush=True)
    print(f"MODE={_run['mode']} MODEL={_run['model']} TF={TF} interval={TICK_INTERVAL_S}s", flush=True)
    print(f"RESUMED open positions: {len([p for p in engine.portfolio.positions if p.get('status')=='OPEN'])}", flush=True)
    log_event("paper_runtime", "info", f"runtime start mode=PAPER model={_run['model']} stop_utc={_run['stop_utc']}",
              {"start": _run["start_ms"], "stop": STOP_UTC_MS})

    last_tick_ts = 0
    try:
        while True:
            now_ms = int(time.time()*1000)
            if now_ms >= STOP_UTC_MS:
                print(f"STOP REACHED at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}", flush=True)
                break
            # tick if enough time has passed since the previous decision tick
            if now_ms - last_tick_ts >= MIN_UPDATE_INTERVAL_S * 1000:
                for sym in SYMBOLS:
                    try:
                        rec = _decision_tick(engine, sym)
                        _emit(rec)
                        _run["llm_calls"] = _snapshot_llm_calls()
                        cand = "YES" if rec["decision"] in ("LONG", "SHORT") else "no"
                        print(f"[{rec['utc']}] {sym} -> {rec['decision']} (candidate={cand}) "
                              f"{(rec['reason'] or '')[:60]}", flush=True)
                    except Exception as e:
                        err = {"ts": now_ms, "sym": sym, "err": f"{type(e).__name__}: {e}"}
                        _run["errors"].append(err)
                        log_event("paper_runtime", "error", f"tick failed {sym}: {err['err']}", {})
                        print(f"  tick error {sym}: {err['err']}", flush=True)
                last_tick_ts = now_ms
            # sleep in small increments so stop is honored promptly
            time.sleep(min(30, max(1, (STOP_UTC_MS - now_ms)/1000)))
    except KeyboardInterrupt:
        print("RUNTIME INTERRUPTED", flush=True)

    _run["end_ms"] = int(time.time()*1000)
    _run["end_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _run["llm_calls"] = _snapshot_llm_calls()
    _write_summary()
    print(f"RUNTIME END {_run['end_utc']} — not restarting", flush=True)


def _write_summary():
    ticks = _run["ticks"]
    eligible = [t for t in ticks if t["decision"] in ("LONG", "SHORT")]
    llm_calls = _run["llm_calls"]
    n_llm_ok = sum(1 for c in llm_calls if c.get("ok"))
    summary = {
        "runtime_start": _run["start_utc"], "runtime_end": _run.get("end_utc"),
        "scheduled_stop": _run["stop_utc"], "mode": _run["mode"], "model": _run["model"],
        "decision_ticks": len(ticks),
        "long_short_candidates": len(eligible),
        "no_trade_count": len(ticks) - len(eligible),
        "no_trade_reasons": _count_by(ticks, "reason"),
        "regime_counts": _count_by(ticks, "regime"),
        "llm_calls": len(llm_calls), "llm_ok": n_llm_ok,
        "llm_calls_per_eligible_signal": (len(llm_calls)/len(eligible)) if eligible else 0,
        "errors": len(_run["errors"]),
        "token_input": sum((c.get("usage") or {}).get("prompt_tokens", 0) for c in llm_calls if c.get("ok")),
        "token_output": sum((c.get("usage") or {}).get("completion_tokens", 0) for c in llm_calls if c.get("ok")),
        "token_total": sum((c.get("usage") or {}).get("total_tokens", 0) for c in llm_calls if c.get("ok")),
        "raw_llm_calls": llm_calls,
        "credit_status": "CREDIT_USAGE_UNAVAILABLE (customer_credits non-monotonic across calls; not verifiable)",
    }
    out = Path(__file__).parent.parent / "docs" / "paper_runtime_summary.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str), flush=True)


def _count_by(items, key):
    d = {}
    for it in items:
        v = it.get(key)
        d[v] = d.get(v, 0) + 1
    return d


if __name__ == "__main__":
    main()
