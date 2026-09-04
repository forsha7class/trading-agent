# DEMO Execution — Adapter + Lifecycle (2026-09, coding slice)

Additive. NO Phase 6. PAPER path byte-for-byte unchanged. Strategy frozen at
RegimeGatedTrend 0.1.0. RiskEngine authoritative. AI review-only.
**Zero external orders were placed building this slice** (all exchange paths
tested against in-memory FakeBroker/FakeFuturesBroker; real brokers never
invoked).

## Files changed (slice)

| file | what |
|---|---|
| `execution/env.py` | TRADING_MODE gate. PAPER/DEMO/LIVE; LIVE → disabled; DEMO requires mode=DEMO + creds + confirmed demo endpoint (mainnet refused). Never silent fallback. **+ DEMO_KIND gate** (SPOT default / FUTURES): futures demo targets OFFICIAL `https://demo-fapi.binance.com` (own creds `BINANCE_FUTURES_DEMO_API_KEY/_SECRET`); legacy futures testnet only under `FUTURES_DEMO_LEGACY=1`; spot/futures creds+endpoints never mix. |
| `execution/adapters.py` | `ExecutionAdapter` base (place/get_status/cancel/get_position/close/reconcile). `PaperExecution` (wraps untouched PaperEngine), `DemoExecution` (spot testnet), `LiveExecution` (interface-only → `LIVE_EXECUTION_DISABLED`, no order impl). |
| `execution/demo_broker.py` | Binance Spot Testnet signed REST (HMAC-SHA256, X-MBX-APIKEY). Base hard-coded testnet; refuses any other base. Secrets from env, never logged/printed/persisted. No mainnet route. |
| `execution/fake_broker.py` | Deterministic in-memory brokers (validate/market_open/market_close/order_status): `FakeBroker` spot-shaped (LONG only), `FakeFuturesBroker` futures-shaped (LONG+SHORT, leverage, one-way positionAmt) — tests only. |
| `execution/futures_broker.py` | Binance USDT-M FUTURES DEMO signed REST (`/fapi/*`, base = official `https://demo-fapi.binance.com`; legacy testnet only via `FUTURES_DEMO_LEGACY=1`). LONG+SHORT market orders, per-symbol leverage (1x, 2x cap), one-way position mode check, positionRisk (entry/mark/liq/margin), LOT_SIZE+MIN_NOTIONAL validate. Own futures-only creds. No spot route, no mainnet route. |
| `execution/demo_engine.py` | `DemoEngine` generalized over broker capability: broker declares `market`/`capabilities` (LONG/SHORT/leverage_max). Spot = LONG-only 1x; futures = LONG+SHORT ≤2x one-way. Environment label DEMO vs DEMO_FUTURES on every row. ROE tracked on close (margin = notional/leverage). |
| `storage/database.py` | + demo schema (migration block, existing tables untouched). **+ futures columns** (additive ALTER): `demo_orders.leverage`, `demo_positions.{leverage,margin,notional,liquidation_price,mark_price,unrealized_pnl}`, `demo_trades.{leverage,roe_pct,mark_price}`. |
| `storage/demo_store.py` | demo_orders/positions/trades/events persistence helpers (+ new fields pass-through, `mark_entry_pnl`). |
| `agents/telegram_notifier.py` | + trader-facing demo events/formatters (additive; old formatters intact). Header: `BINANCE DEMO` (spot) vs `BINANCE FUTURES DEMO`; `Leverage: Nx`; exits show `ROE: +x.xx%` when present. |
| `tests/test_demo_execution.py` | 28 tests, ALL PASS. |
| `tests/test_futures_demo.py` | 23 futures-demo tests (env demo-fapi default + legacy-testnet opt-in gate, broker safety, LONG+SHORT lifecycle, leverage cap, one-way mode, exits, ROE, formats), ALL PASS. |
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

## FUTURES DEMO slice (USDT-M, task §9/§10)

Target changed: **Binance Futures Demo Trading** (USDT-M perpetual, official
demo portal demo.binance.com) — NOT Spot Testnet, NOT the legacy futures
testnet. Spot execution code stays intact and LONG-only; futures is a separate
kind with separate credentials and endpoint.

- `DEMO_KIND` env selects the demo market: `SPOT` (default, unchanged) or
  `FUTURES`. **Futures target = OFFICIAL Demo API base
  `https://demo-fapi.binance.com`** (verified live: `/fapi/v1` ping/time/
  exchangeInfo; HMAC-SHA256 signed account/positionRisk/positionSide work with
  the Futures Demo API key). The legacy futures testnet
  (`https://testnet.binancefuture.com`, decommissioned by Binance) is reachable
  ONLY under explicit `FUTURES_DEMO_LEGACY=1`; mainnet (`https://fapi.binance.com`)
  is refused by gate AND broker; no silent fallback between demo/testnet/mainnet.
- Credentials: dedicated Futures Demo key (`BINANCE_FUTURES_DEMO_API_KEY/_SECRET`
  in the runtime env). Spot testnet creds are never used for futures (§9).
- Broker `FuturesDemoBroker` (futures_broker.py): `/fapi/v1|v2`, HMAC signed.
  LONG -> BUY, SHORT -> SELL; close mirrors the open side (SELL-to-close LONG,
  BUY-to-close SHORT), one-way position mode. `position()` returns
  entry/mark/liquidation/margin/notional/unrealized from `/fapi/v2/positionRisk`
  (fields the exchange exposes; never fabricated).
- Leverage: fixed per-candidate, default 1x, **2x hard maximum** enforced in
  broker capabilities + engine + adapter. Set + read back before any order
  (`/fapi/v1/leverage` then positionRisk). Never dynamically raised.
- `DemoEngine` reads broker-declared capabilities instead of assuming spot:
  spot rejects SHORT (`SHORT_NOT_SUPPORTED`); futures allows LONG/SHORT with
  leverage cap. Rows carry `environment` DEMO (spot) vs DEMO_FUTURES.
- DB: additive columns only (prod migrated, 0 rows touched).
- Telegram: header `BINANCE FUTURES DEMO` + `Leverage: Nx` on filled, `ROE` on
  exits when margin known.
- Live demo check (2026-09-04): demo-fapi account live — USDT 5000 / USDC 5000 /
  BTC 0.01 available, canTrade, one-way mode, leverage set+verified 1x, zero
  positions. Live 1H regime: BTCUSDT LOW_VOL, ETHUSDT/SOLUSDT RANGE — all
  REGIME_BLOCKED → NO_TRADE (frozen gate working; no eligible candidate yet, so
  no order is possible regardless of credentials).

## Revert

Remove `execution/{env,adapters,demo_broker,futures_broker,fake_broker,demo_engine}.py`,
`storage/demo_store.py`, revert `storage/database.py` demo migrations + the
telegram_notifier additive block, delete `tests/test_demo_execution.py` and
`tests/test_futures_demo.py`.

## FUTURES_DEMO_STATUS: READY-FOR-SMOKE (blocked on explicit authorization)

Architecture + tests + live endpoint verification are complete; the real
external smoke order is NOT placed — it awaits explicit operator authorization
(task §30/§32 — never faked, never auto-run, never SMOKE_AUTHORIZED=1 without a
go).
1. Target verified: official Futures Demo API `https://demo-fapi.binance.com`
   (account live, one-way, 1x leverage, zero positions). Legacy futures testnet
   only via `FUTURES_DEMO_LEGACY=1`.
2. No frozen eligible candidate is currently produced (live BTCUSDT LOW_VOL /
   ETH+SOL RANGE — frozen gate correctly rejects; needs a TREND_BULL/TREND_BEAR
   1H candle to fire).

Once both hold: `SMOKE_AUTHORIZED=1 DEMO_KIND=FUTURES TRADING_MODE=DEMO
python scripts/demo_smoke_test.py --symbol BTCUSDT --dry-run` (verify) then the
same without `--dry-run` for ONE minimal 1x order, then stop and report.
