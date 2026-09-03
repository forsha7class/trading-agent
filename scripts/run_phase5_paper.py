"""Phase 5 — FINAL PAPER OBSERVATION (frozen RegimeGatedTrend, live data, single forward window).

Injects the Phase-4-frozen RegimeGatedTrend into the paper chain on the newest
available live 1h candles that follow the Phase 4 TEST segment (no overlap with the
data used for the Phase 4 OOS claim). Spec: docs/PAPER_FINAL_SPEC.md. No retune.
"""
from __future__ import annotations
import json, sys, time, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from storage.database import init_db, insert_paper_trade
from ingestion.market_data import fetch_klines
from evaluation.strategy_eval import evaluate_strategy
from evaluation.regime_gating import RegimeGatedTrend, ALLOWED_TREND_REGIMES
from evaluation.mae_mfe import enrich_trades

# ---- Frozen spec (must match docs/PAPER_FINAL_SPEC.md) ----
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
TF = "1h"
FROZEN = dict(fee=0.0004, slippage=0.0005, risk_pct=0.005, min_rr=1.5)
HORIZON = 20
# Phase 4 TEST window (1h) ended near this open_time; observe strictly-newer bars.
PHASE4_MAX_BAR_TS = 1788401900000

def fetch_fresh(symbol: str, n_bars: int = 900):
    candles = fetch_klines(symbol, TF, limit=n_bars)
    fresh = [c for c in candles if c["open_time"] > PHASE4_MAX_BAR_TS]
    return candles, fresh

def obs_symbol(symbol: str) -> dict:
    candles, fresh = fetch_fresh(symbol)
    result = {"symbol": symbol, "candles_total": len(candles), "fresh_candles": len(fresh)}
    if len(fresh) < 60:
        result["status"] = "INSUFFICIENT_DATA"
        result["note"] = f"only {len(fresh)} post-phase4 candles; need >=60"
        return result
    # Evaluate frozen candidate on the fresh window. evaluate_strategy is causal.
    res = evaluate_strategy(fresh, RegimeGatedTrend(allowed=ALLOWED_TREND_REGIMES),
                            fee=FROZEN["fee"], slippage=FROZEN["slippage"],
                            risk_pct=FROZEN["risk_pct"], min_rr=FROZEN["min_rr"],
                            horizon=HORIZON)
    trades = res.get("trades", [])
    metrics = res.get("metrics", {})
    enriched = enrich_trades(fresh, trades, horizon=HORIZON)

    # Persist paper trades (append-only audit trail), one per paper observation.
    init_db()
    now = int(time.time()*1000)
    persist_warnings = []
    for i, t in enumerate(enriched):
        try:
            insert_paper_trade({
                "decision_id": now + random.randint(1, 9999),
                "symbol": symbol, "side": t.get("side", "LONG"),
                "entry": t.get("entry"), "stop": t.get("stop"), "tp1": t.get("tp"),
                "size": None, "status": "CLOSED",
                "opened_at": fresh[t["bar"]]["open_time"] if t.get("bar") is not None else now,
                "pnl": t.get("pnl"),
            })
        except Exception as e:
            persist_warnings.append(str(e))

    # breakdown by exit reason & side
    exit_reasons = {}
    side_counts = {}
    for t in enriched:
        er = t.get("exit_reason", t.get("hit", "UNKNOWN"))
        exit_reasons[er] = exit_reasons.get(er, 0) + 1
        s = t.get("side", "?")
        side_counts[s] = side_counts.get(s, 0) + 1

    result.update({
        "status": "OBSERVATIONAL" if len(trades) else "INSUFFICIENT_DATA",
        "trade_count": len(trades),
        "metrics": metrics,
        "exit_reasons": exit_reasons,
        "side_counts": side_counts,
        "mae_mfe_sample": enriched[:3],
    })
    if persist_warnings:
        result["persist_warnings"] = persist_warnings
    return result

def run():
    init_db()
    print("=== PHASE 5 FINAL PAPER OBSERVATION ===", flush=True)
    out = {"frozen": {**FROZEN, "horizon": HORIZON}, "symbols": {},
           "generated_at": int(time.time()*1000), "spec": "docs/PAPER_FINAL_SPEC.md"}
    for sym in SYMBOLS:
        print(f"\n--- {sym} ---", flush=True)
        r = obs_symbol(sym)
        out["symbols"][sym] = r
        m = r.get("metrics", {})
        print(f"  fresh={r.get('fresh_candles')} trades={r.get('trade_count')} "
              f"status={r.get('status')}", flush=True)
        print(f"  pnl={m.get('pnl')} pf={m.get('profit_factor')} win={m.get('win_rate')} "
              f"mdd={m.get('max_drawdown')} exp={m.get('expectancy')}", flush=True)
        print("  exits:", r.get("exit_reasons"), " sides:", r.get("side_counts"), flush=True)
    path = Path(__file__).parent.parent / "docs" / "phase5_paper_results.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nwrote {path}", flush=True)
    return out

if __name__ == "__main__":
    r = run()
    for s, v in r["symbols"].items():
        m = v.get("metrics", {})
        print(f"{s}: {v.get('status')} trades={v.get('trade_count')} "
              f"pnl={m.get('pnl')} pf={m.get('profit_factor')} win={m.get('win_rate')}")
