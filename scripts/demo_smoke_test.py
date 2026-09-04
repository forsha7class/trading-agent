"""DEMO SMOKE TEST entrypoint — the ONLY place a real Binance Spot Testnet order
may be placed. It never runs automatically: it requires an explicit flag
(SMOKE_AUTHORIZED=1) set by the operator, plus a green demo env gate, plus an
eligible frozen candidate. Importing this module does nothing.

Usage (operator-controlled, after code/tests pass AND a frozen TREND_BULL/BEAR
candidate exists AND RiskEngine/eligibility approve):

  source ~/.hermes/.env
  TRADING_MODE=DEMO SMOKE_AUTHORIZED=1 python3 scripts/demo_smoke_test.py --symbol BTCUSDT

It constructs the candidate from live candles via execution/demo_signal
(RegimeGatedTrend frozen path). If the gate is not green or the candidate is not
eligible, it prints the reason and exits WITHOUT placing an order.
"""
from __future__ import annotations
import os, sys, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--equity", type=float, default=10000.0)
    ap.add_argument("--dry-run", action="store_true",
                    help="verify environment + candidate; do NOT place an order")
    args = ap.parse_args()

    # 0. explicit authorization gate — never auto-place
    if os.getenv("SMOKE_AUTHORIZED") != "1":
        print("REFUSED: SMOKE_AUTHORIZED=1 required (explicit operator authorization).")
        return 2

    # 1. env gate
    from execution import env as exenv
    st = exenv.demo_env_status()
    print(f"mode={st['mode']} demo_ready={st['demo_ready']} endpoint={st['endpoint']}")
    print("gate reasons:", st["reasons"])
    if not st["demo_ready"]:
        print("NO ORDER — demo environment not ready.")
        return 3

    # 2. broker connectivity (read-only)
    from execution.demo_broker import DemoBroker
    broker = DemoBroker()
    print("ping:", broker.ping())
    acct = broker.account_snapshot()
    print("balances:", {k: round(v, 6) for k, v in acct["balances"].items()})

    # 3. build frozen candidate from live data
    from ingestion.market_data import fetch_klines
    from execution.demo_signal import build_demo_candidate, traceable_chain
    candles = fetch_klines(args.symbol, args.timeframe, limit=100)
    cand = build_demo_candidate(candles, symbol=args.symbol, timeframe=args.timeframe,
                                equity=args.equity, use_llm=False)
    chain = traceable_chain(cand)
    print("candidate:", chain)

    # 4. eligibility re-check (authoritative)
    if not cand.get("eligibility", {}).get("eligible"):
        print(f"NO ORDER — candidate not eligible: {chain.get('eligibility_reason')}")
        return 4
    if str(cand.get("decision") or "").upper() != "LONG":
        print(f"NO ORDER — spot supports LONG only (decision={cand.get('decision')})")
        return 4

    if args.dry_run:
        print("DRY-RUN OK — eligible candidate; no order placed.")
        return 0

    # 5. place ONE minimal demo order
    from execution.demo_engine import DemoEngine
    eng = DemoEngine(broker)
    res = eng.open_from_candidate(cand)
    print("order result:", {k: res.get(k) for k in
                            ("order_id", "status", "decision_id", "reason")})
    print("position:", bool(res.get("position")))
    return 0 if res.get("status") == "FILLED" else 1


if __name__ == "__main__":
    sys.exit(main())
