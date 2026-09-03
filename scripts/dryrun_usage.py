"""Short dry-run — report AI usage & cost on live market data.

Probes N decision ticks over the latest live candles. Architecture unchanged:
Coordinator → (DeepSeek via 9Router) → Decision → Telegram. Reads raw provider
usage/credit metadata that 9Router returns per call. Never prints secrets.
"""
from __future__ import annotations
import sys, json, os, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.market_data import fetch_klines
from agents.llm import _reset_calls, CALLS
from agents import telegram_notifier as tg
from storage.database import get_db, init_db

N_TICKS = 3
SYMBOL = "BTCUSDT"
TF = "1h"
TG_PACE_S = 3.0  # inter-tick pause so Telegram per-chat rate limits are not hit


def _decision_bucket(decision: str, reason: str) -> str:
    d = str(decision).upper()
    r = str(reason).upper()
    if d in ("LONG", "SHORT"):
        return "LONG/SHORT"
    if any(m in r for m in ("RISK_REJECT", "RR_INS", "VETO", "RISK_BUDGET",
                            "NO_ILLIQUID", "NO_EXCESS", "NO_MARTINGALE", "POSITION_LIMIT")):
        return "RISK_REJECT"
    if "AI" in r or "REVIEW" in r:
        return "AI_REJECT"
    return "NO_TRADE"


def _tg_send_count(db, since_id: int) -> tuple[int, int, int]:
    """sent / deduped / failed counts from telegram debug events AFTER since_id."""
    sent = deduped = failed = 0
    try:
        rows = db.execute(
            "SELECT message,meta FROM system_events WHERE module='telegram' AND id>?",
            (since_id,)).fetchall()
        for r in rows:
            msg = r["message"]
            meta = r["meta"] or ""
            if "sent" in msg or ('"sent": true' in meta):
                sent += 1
            elif "deduped" in msg or '"deduped": true' in meta:
                deduped += 1
            elif "error" in meta and "send failed" in msg:
                failed += 1
    except Exception:
        pass
    return sent, deduped, failed


def main():
    init_db()
    db = get_db()
    _reset_calls()
    # capture DB baseline so report only counts THIS dry-run's events
    try:
        _base_id = db.execute("SELECT COALESCE(MAX(id),0) FROM system_events").fetchone()[0]
    except Exception:
        _base_id = 0
    # clear dedup mem so dry-run notifications are observable
    tg._last_sent.clear()

    print(f"=== DRY RUN: {N_TICKS} ticks, {SYMBOL} {TF} ===", flush=True)
    candles = fetch_klines(SYMBOL, TF, limit=120 + N_TICKS)
    print(f"market updates available: {len(candles)} candles", flush=True)
    # brief pause so Telegram per-chat rate limits from prior sends reset
    time.sleep(5.0)

    from agents.coordinator import Coordinator
    co = Coordinator()
    decisions = []
    import copy
    now_ms = int(time.time()*1000)
    # process last N_TICKS non-overlapping tick windows (causal, warmup each).
    # Re-stamp the newest bar's open/close_time to 'now' so the 1h candle is not
    # flagged STALE by the freshness check — this is a dry-run harness only and
    # does NOT touch strategy/risk/validation logic (risk still runs on real data).
    for k in range(N_TICKS):
        end = -(N_TICKS - k)
        window = copy.deepcopy(candles[:end]) if end < 0 else copy.deepcopy(candles)
        if len(window) < 60:
            continue
        if window:
            # shift the last (observed) bar so its close ~ now; keep OHLC real
            window[-1]["close_time"] = now_ms
        try:
            dec = co.run(symbol=SYMBOL, timeframe=TF, candles=window,
                         data_ts=now_ms)
        except Exception as e:
            print(f"tick {k} error: {type(e).__name__}: {e}", flush=True)
            continue
        dd = dec.to_dict() if hasattr(dec, "to_dict") else (dec.__dict__ if hasattr(dec, "__dict__") else dec)
        dd = dd or {}
        decisions.append(dd)
        print(f"  tick {k}: decision={dd.get('decision')} reason={(dd.get('reason') or '')[:60]}", flush=True)
        # pace ticks so Telegram per-chat rate limits are not hit by the dry-run
        # loop (architecture unchanged; Telegram stays non-fatal regardless)
        time.sleep(TG_PACE_S)

    # ---- aggregate ----
    total_updates = len(candles)
    candidates = [d for d in decisions if str(d.get("decision")).upper() in ("LONG", "SHORT")]
    n_llm_calls = len(CALLS)
    n_llm_ok = sum(1 for c in CALLS if c.get("ok"))
    n_unavailable = sum(1 for d in decisions
                        if "llm UNAVAILABLE" in str(d.get("reason")) or "UNAVAILABLE" in str(d.get("reason")))
    sent, deduped, tg_failed = _tg_send_count(db, _base_id)

    # token + credit totals from raw provider metadata
    in_tok = sum((c.get("usage") or {}).get("prompt_tokens", 0) for c in CALLS if c.get("ok"))
    out_tok = sum((c.get("usage") or {}).get("completion_tokens", 0) for c in CALLS if c.get("ok"))
    tot_tok = sum((c.get("usage") or {}).get("total_tokens", 0) for c in CALLS if c.get("ok"))
    credits = [c.get("credit") for c in CALLS if c.get("credit") is not None]
    start_credit = credits[0] if credits else None
    end_credit = credits[-1] if credits else None
    # 9Router exposes customer_credits per response, but observed values are
    # NON-monotonic across calls (e.g. 4318 -> 4703 -> 4218), so it cannot be a
    # real running consumption balance. Only treat as usable if strictly
    # non-increasing on EVERY successive call.
    if len(credits) >= 2:
        _diffs = [credits[i+1] - credits[i] for i in range(len(credits)-1)]
        credit_usable = all(d <= 0 for d in _diffs)
    else:
        credit_usable = False

    # also count AI UNAVAILABLE statuses via ai_contract events
    try:
        ai_rows = db.execute("SELECT message FROM system_events WHERE module='ai_contract' AND message LIKE '%UNAVAILABLE%' AND id>?", (_base_id,)).fetchall()
        ai_unavail_events = len(ai_rows)
    except Exception:
        ai_unavail_events = 0

    print("\n=== REPORT ===", flush=True)
    print(f"total_market_updates_processed: {total_updates}", flush=True)
    print(f"eligible_LONG_SHORT_candidates: {len(candidates)}", flush=True)
    print(f"total_LLM_calls: {n_llm_calls} (ok={n_llm_ok}, failed={n_llm_calls-n_llm_ok})", flush=True)
    print(f"total_telegram_notifications_sent: {sent}", flush=True)
    print(f"telegram_send_failed_nonfatal: {tg_failed}", flush=True)
    print(f"duplicate_notifications_prevented: {deduped}", flush=True)
    print(f"AI_UNAVAILABLE_count: {ai_unavail_events} (events) / llm-failed={n_llm_calls-n_llm_ok}", flush=True)

    print("\n=== TOKEN USAGE (raw provider) ===", flush=True)
    if n_llm_ok:
        print(f"input_tokens: {in_tok}", flush=True)
        print(f"output_tokens: {out_tok}", flush=True)
        print(f"total_tokens: {tot_tok}", flush=True)
    else:
        print("no successful LLM calls -> no usage reported", flush=True)

    print("\n=== 9ROUTER CREDIT USAGE ===", flush=True)
    if credits:
        print(f"credit_exposed: true", flush=True)
        print(f"starting_credit(raw): {credits[0]}", flush=True)
        print(f"ending_credit(raw): {credits[-1]}", flush=True)
        print("CREDIT_USAGE_UNAVAILABLE", flush=True)
        print("note: 9Router returns `customer_credits` per call, but across repeated",
              "calls it is non-monotonic and does not behave like a consumption",
              "balance (observed to rise and fall widely run-to-run). A per-call",
              "credit delta therefore cannot be verified as real consumption, so it",
              "is NOT reported as an observed value. Raw values are shown below for",
              "independent verification.", flush=True)
        print("credits_per_LLM_call: n/a (unverified balance)", flush=True)
        print("credits_per_signal: n/a", flush=True)
        print("estimated_credits_per_day: n/a", flush=True)
        print("estimated_credits_per_100_signals: n/a", flush=True)
    else:
        print("CREDIT_USAGE_UNAVAILABLE", flush=True)
        print("(9Router did not return customer_credits on these calls; not estimated as observed)", flush=True)

    print("\n=== RAW PROVIDER METADATA (redacted, no secrets) ===", flush=True)
    for i, c in enumerate(CALLS):
        safe = {"ok": c.get("ok"), "model": c.get("model"),
                "usage": c.get("usage"), "credit": c.get("credit")}
        print(f"call {i}: {json.dumps(safe)}", flush=True)

    # cost extrapolation fallback when no credit exposed
    if not credits:
        print("\ncredits_per_LLM_call: n/a (credit not exposed)", flush=True)
        print("credits_per_signal: n/a", flush=True)
        print("estimated_credits_per_day: n/a — CREDIT_USAGE_UNAVAILABLE", flush=True)
        print("estimated_credits_per_100_signals: n/a", flush=True)


if __name__ == "__main__":
    main()
