# DEMO Execution — Adapter + Lifecycle (2026-09, coding slice)

Additive. NO Phase 6. PAPER path byte-for-byte unchanged. Strategy frozen at
RegimeGatedTrend 0.1.0. RiskEngine authoritative. AI review-only.
**Zero external orders were placed building this slice** (all exchange paths
tested against an in-memory FakeBroker; real broker never invoked).

## Files changed (slice)

| file | what |
|---|---|
| `execution/env.py` | TRADING_MODE gate. PAPER/DEMO/LIVE; LIVE → disabled; DEMO requires mode=DEMO + creds + endpoint == `https://testnet.binance.vision` (mainnet refused). Never silent fallback. |
| `execution/adapters.py` | `ExecutionAdapter` base (place/get_status/cancel/get_position/close/reconcile). `PaperExecution` (wraps untouched PaperEngine), `DemoExecution` (spot testnet), `LiveExecution` (interface-only → `LIVE_EXECUTION_DISABLED`, no order impl). |
| `execution/demo_broker.py` | Binance Spot Testnet signed REST (HMAC-SHA256, X-MBX-APIKEY). Base hard-coded testnet; refuses any other base. Secrets from env, never logged/printed/persisted. No mainnet route. |
| `execution/fake_broker.py` | Deterministic in-memory broker (validate/market_buy/market_sell/order_status) — tests only. |
| `execution/demo_engine.py` | DEMO lifecycle orchestrator. |
| `storage/database.py` | + demo schema (migration block, existing tables untouched). |
| `storage/demo_store.py` | demo_orders/positions/trades/events persistence helpers. |
| `agents/telegram_notifier.py` | + trader-facing demo events/formatters (additive; old formatters intact). |
| `tests/test_demo_execution.py` | 28 tests, ALL PASS. |
| `docs/DEMO_EXECUTION.md` | this file + scope report. |

## DB schema (new, prod DB migrated, all rows 0)

```
demo_orders(id PK, decision_id UNIQUE, signal_id, symbol, side, requested_qty,
            executed_qty, requested_price, executed_price, stop, tp1, tp2, status,
            strategy_id, strategy_version, regime, risk_engine, ai_status,
            environment='DEMO', created_at, opened_at, closed_at, reject_reason)
demo_positions(id PK, order_id, decision_id UNIQUE, symbol, side, entry, stop,
               tp1, tp2, size, open_qty, status, opened_at, closed_at, environment)
demo_trades(id PK, position_id, order_id, decision_id UNIQUE, symbol, side, entry,
            exit_price, size, qty, pnl, fees, exit_reason, mae, mfe,
            opened_at, closed_at, environment)
demo_events(id PK AUTOINCREMENT, decision_id, event_type, ts, telegram_sent,
            telegram_error, meta, UNIQUE(decision_id, event_type))
```
UNIQUE(decision_id) on order/position/trade ⇒ one lifecycle chain per decision.
UNIQUE(decision_id,event_type) on events ⇒ one event → one Telegram message.

## Lifecycle behavior

Open gate (before any order): eligibility (frozen source + RiskEngine inside,
AI never consulted for approval) → spot LONG-only (SHORT rejected) → valid
qty/price → duplicate order (decision_id) → duplicate OPEN position per symbol →
capacity (max_positions) → broker symbol/qty validation. Any failure ⇒ REJECTED,
no order persisted (except dup-attempts, which never re-open).

Fill: broker response reconciled — request success ≠ fill. FILLED/
PARTIALLY_FILLED with executed_qty>0 ⇒ position OPEN with ACTUAL qty/avg price;
REJECTED/CANCELED/UNKNOWN ⇒ no position, order row marked, safe state.

Exit (per candle, symbol-filtered, deterministic):
- **SL checked first**; SL wins if the same bar touches SL and TP1 (frozen rule).
- **TP1 = FULL exit** (user-confirmed; TP2 stored, never resolved — matches the
  frozen paper semantics; no partial scale-out).
- **TIME_EXIT** after max_hold_bars (20) 1h bars at bar close.
Close sells back via broker; persists CLOSED position/order + exactly one
demo_trade (pnl/fees/exit_reason) + one demo_events row.

Restart: `reconcile_open()` rebuilds OPEN demo positions from DB (no loss, no dup).

## Telegram (trader-facing, plain text)

Events: DEMO_FILLED (🟦 OPEN — only after confirmed fill; PENDING otherwise),
DEMO_TP1 ✅ / DEMO_TP2 🎯 / DEMO_SL 🛑 / DEMO_TIME ⏱️ / DEMO_REJECT 🛑 NO TRADE.
Number presentation: `_price` 80943.32→`80,943.32`; `_rr_str` → `1:1.50`;
`_pct` 0.005→`0.50%`. Regimes readable (TREND_BULL→Trend Bullish …). AI status
line: PASS 🧠 / FLAG ⚠️ / REJECT 🛑 / UNAVAILABLE ⚪ (never called PASS).
Dedup by decision_id+event_type (DB) AND notifier cooldown (in-memory). Send
requires TRADING_TG_SEND=1; failure logged, never crashes execution.

## DEMO execution readiness

- Full lifecycle + safety logic built and test-covered (28 tests).
- Real order path exists ONLY via `DemoEngine` + `DemoBroker`, which refuses
  unless: `TRADING_MODE=DEMO`, creds present, endpoint == testnet base.
- `TRADING_MODE` is NOT set to DEMO anywhere in the runtime env; no runtime
  wires DEMO execution. Nothing auto-places an order on import/startup.

## Conditions still required before the FIRST real DEMO order (smoke test)

1. Explicit user authorization for the smoke test (separate step).
2. Endpoint re-verified == `https://testnet.binance.vision`.
3. Credentials confirmed demo/testnet (they are: Binance Spot Testnet, verified
   HTTP 200 on `/api/v3/account`, balances present).
4. A frozen RegimeGatedTrend candidate appears with regime ∈ {TREND_BULL,
   TREND_BEAR} (live 1h BTCUSDT — currently LOW_VOL ⇒ NEUTRAL, will not fire),
5. RiskEngine APPROVED and `execution/eligibility` returns ELIGIBLE.
6. Symbol/quantity valid (broker `validate`), order minimal, spot LONG only.
7. No mainnet route exists (verified: env gate + broker refuse).

## Verification (this slice)

`/usr/bin/python3.14 tests/test_*.py` — all 11 suites PASS (incl. new
test_demo_execution 28 tests). `/health` 200. Prod `storage/trading.db`: demo
tables exist, 0 rows; decisions 1299 unchanged. No secrets in repo
(env-only). No real order was placed.

## Revert

Remove `execution/{env,adapters,demo_broker,fake_broker,demo_engine}.py`,
`storage/demo_store.py`, revert `storage/database.py` demo migration + the
telegram_notifier additive block, delete `tests/test_demo_execution.py`.
