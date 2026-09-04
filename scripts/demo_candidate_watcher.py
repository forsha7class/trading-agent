"""Frozen DEMO candidate watcher — continuous read-only polling runner.

Polls once per completed 1H candle (every 3600s, aligned to bar close + small
offset). CLOSED bars only. Evaluates the frozen RegimeGatedTrend 0.1.0 path via
execution/candidate_watcher.check_all. Sends ONE Telegram alert only when a
candidate is ELIGIBLE and the candle is new (dedup in demo_events).

Safety:
  - NEVER places an order. Does not touch the demo execution path
    (DemoEngine/broker) at all.
  - No LLM call for discovery (use_llm=False in the candidate path); ordinary
    NO_TRADE -> zero LLM calls.
  - Non-fatal: per-symbol errors are logged and skipped.
  - Mainnet path: none (candidate source is public klines only).
  - To STOP: kill the process (it does not self-restart).

Usage:
  source ~/.hermes/.env && TRADING_MODE=DEMO \
    python3 scripts/demo_candidate_watcher.py            # 3600s interval
  python3 scripts/demo_candidate_watcher.py --once       # single pass, then exit
"""
from __future__ import annotations
import os, sys, time, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.candidate_watcher import run_once, WATCH_SYMBOLS, TIMEFRAME

POLL_INTERVAL_S = 3600          # once per completed 1H bar
ALIGN_OFFSET_S = 45             # evaluate shortly after bar close_time
SLEEP_STEP_S = 30               # responsive stop


def _align_wait(interval_s: int = POLL_INTERVAL_S) -> float:
    """Seconds until the next evaluation aligned to bar boundaries."""
    now = time.time()
    return interval_s - (now % interval_s) + ALIGN_OFFSET_S


def _summarize(results: list[dict]) -> None:
    for r in results:
        sym = r.get("symbol")
        if r.get("eligible"):
            print(f"[{time.strftime('%H:%M:%SZ', time.gmtime())}] {sym} "
                  f"ELIGIBLE notified={r.get('notified')} deduped={r.get('deduped')} "
                  f"bar={r.get('bar_open_time')}", flush=True)
        else:
            print(f"[{time.strftime('%H:%M:%SZ', time.gmtime())}] {sym} "
                  f"{r.get('reason') or 'skip'}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="single pass then exit")
    ap.add_argument("--notify", action="store_true",
                    help="enable Telegram (TRADING_TG_SEND=1 still required)")
    args = ap.parse_args()
    notify = bool(args.notify) and os.getenv("TRADING_TG_SEND") == "1"

    print(f"CANDIDATE WATCHER symbols={WATCH_SYMBOLS} tf={TIMEFRAME} "
          f"interval={POLL_INTERVAL_S}s notify={notify}", flush=True)
    try:
        while True:
            results = run_once(symbols=WATCH_SYMBOLS, notify=notify)  # fetch + closed-bar eval
            _summarize(results)
            if args.once:
                return 0
            time.sleep(SLEEP_STEP_S)
            # re-align to the bar boundary
            left = _align_wait()
            while left > 0:
                time.sleep(min(SLEEP_STEP_S, left))
                left -= SLEEP_STEP_S
    except KeyboardInterrupt:
        print("WATCHER STOPPED", flush=True)
        return 0


if __name__ == "__main__":
    sys.exit(main())
