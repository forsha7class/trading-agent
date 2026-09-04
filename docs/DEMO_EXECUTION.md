# DEMO Execution — Status & Scope (2026-09)

Task: "Clean Telegram alerts + DEMO execution adapter" (additive, NO Phase 6).

## Delivered (this slice)

DEMO execution is **source-gated and signal-ready, but not order-capable.**
Two additive modules + tests, PAPER path untouched:

- `execution/eligibility.py` — source-of-truth demo eligibility gate (fail-closed).
  Frozen candidate only: `strategy_id=trend_gated`, `strategy_version=0.1.0`,
  regime ∈ {TREND_BULL, TREND_BEAR}, decision LONG/SHORT, RiskEngine APPROVED.
  Legacy 4-strategy ensemble signals (Coordinator path) → always rejected
  (WRONG_STRATEGY), even in a trending regime. AI is never consulted for approval.
  Tests: `tests/test_demo_eligibility.py` (11, ALL PASS).
- `execution/demo_signal.py` — isolated DEMO signal source feeding the frozen
  `RegimeGatedTrend` through the unchanged deterministic pipeline
  (validate → features → regime → gate → DecisionEngine/RiskEngine → bounded AI
  → eligibility). In-memory candidate dict; no orders, no demo DB, no Telegram.
  `LOW_VOL/RANGE/HIGH_VOL/UNCERTAIN` → NEUTRAL at source → never reach risk.
  Tests: `tests/test_demo_signal.py` (9, ALL PASS).

Traceable chain per candidate: `signal_id → strategy/version → regime → decision
→ risk_engine → ai_status → eligibility{eligible, reason}`
(`execution/demo_signal.py::traceable_chain`).

## NOT built (explicit stop)

Full demo lifecycle was **not implemented** and no demo order exists. Decision
taken with the user after inspection:

1. **No Binance DEMO credentials exist in this environment** — checked
   `~/.hermes/.env`, `/etc/9router.env`, process env, and disk: zero Binance
   key/secret/testnet endpoint. The task's §4 ("dedicated DEMO credentials
   already configured") is not true here. Per §5 safety gate (creds present +
   endpoint confirmed demo + not mainnet) execution **must** remain NO ORDER
   until real demo creds are supplied by the user. Nothing was guessed or
   auto-corrected.
2. Real Binance DEMO smoke test (§23) therefore impossible. User chose to stop
   at the gate+signal slice rather than build an internal simulated broker.

Not built: ExecutionAdapter abstraction, DemoExecution/LiveExecution, demo DB
schema (demo_orders/positions/trades), order lifecycle/persistence, TP1/TP2/
SL/TIME_EXIT handling, Telegram redesign (trader-friendly formats, dedup by
decision_id+event_type), docs/TELEGRAM_SIGNAL_FORMAT.md.

## Semantics decisions (user-confirmed)

- TP1/TP2: keep existing frozen deterministic semantics — **TP1 = full exit**,
  TP2 stored but never resolved. No partial scale-out. (Only relevant once a
  demo lifecycle exists.)

## Environment gates (fail-closed, all still enforced)

- `TRADING_MODE` is not read anywhere yet (no execution code exists).
  When execution is added it must be PAPER|DEMO only; LIVE → disabled;
  never silent fallback.
- Telegram remains observability-only: `TRADING_TG_SEND=1` required to send.
- Secrets policy unchanged: no keys in repo/logs/DB/LLM/Telegram.

## Regression (baseline at slice end)

`/usr/bin/python3.14 tests/test_*.py`: test_all, test_leakage, test_risk_scenarios,
test_phase2, test_phase3, test_phase4, test_ai_telegram, test_paper_runtime,
test_demo_eligibility, test_demo_signal — ALL PASS. `/health` = 200.

## Disable / revert

Nothing was added to any live path; removing `execution/` + the two test files
fully reverts this slice. PAPER runtime, dashboard, Telegram, and decision
pipeline are byte-for-byte unchanged.
