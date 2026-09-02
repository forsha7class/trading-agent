# BASELINE — Phase 1 Verified State (2026-09-02)

## Status
WORKING TRADING SOFTWARE — all Phase 1 pipeline modules built and verified.
Not yet quantitatively validated. No claim of edge.

## Test Command
```
cd /root/trading-agent && python3 tests/test_all.py   # → ALL TESTS PASS (10 groups)
```
Current: `ALL TESTS PASS` — validation, features, regime, strategies, ensemble+prob, risk 9 vetoes (11 checks), decision, state_machine, backtest+portfolio, db append-only.

## Health Check
```
python3 -c "from fastapi.testclient import TestClient; from dashboard.app import app; c=TestClient(app); print(c.get('/health').json())"
# → {"status":"ok","modules":{"data_feed":"ONLINE","feature_engine":"ONLINE","regime_engine":"ONLINE","strategy_engine":"ONLINE","risk_engine":"ONLINE","ai_layer":"ONLINE","database":"ONLINE"}}
```
Dashboard: `uvicorn dashboard.app:app --host 0.0.0.0 --port 8000` — `/`, `/api/signals`, `/api/decisions`, `/api/performance` 200.

## Data Source
Binance REST public (no keys): `ingestion/market_data.py` → `fetch_klines(symbol, interval, limit)` with 429 retry.
Verified: `fetch_klines('BTCUSDT','1h',limit=5)` → last close ≈ 76780, `validate_candles` PASS.
Symbols: BTCUSDT, ETHUSDT, SOLUSDT (configurable via `config/settings.yaml`).
Timeframes validated: 1h live; architecture supports 5m/15m/1h/4h/1d (gap detection via TF_MS).

## Known Limitations (must not be hidden)
- Backtest walk-forward degrades: split0 +34% pf 4.9 → split2 -9% pf 0.41 — overfit warning.
- Aggregate 600-candle backtest: -4.01% vs buy-hold +17.91% on recent regime — not profitable baseline.
- `trade_signal/` renamed from `signal/` to avoid shadowing stdlib `signal` (broke anyio/uvicorn). Interface identical.
- Features: EMA20/50, SMA20, RSI14, ATR14, momentum, vol, volume_anomaly — causal but not leakage-audited.
- Probability: heuristic logistic `score→prob` (PROB_VERSION 0.1.0), not statistically calibrated.
- Risk: 9 vetoes unit-tested, scenario stress not yet quantified; position sizing single-position default.
- No persistent historical dataset; live fetch is source of truth — reproducibility limited to in-memory candles.
- Paper portfolio single-position; multi-position concurrency not paper-traded.
- No experiment registry; versions hardcoded 0.1.0.

## Current Architecture
```
market_data(Binance) → validation(validate_candles) → features(technical.build_features, causal) → regime(detector)
→ strategies(trend/momentum/breakout/mean_reversion) → trade_signal(ensemble+probability+mtf) → risk(risk_engine 9 vetoes)
→ decision(engine+state_machine) → agents(coordinator bounded LLM) → paper_portfolio → storage(sqlite WAL, decisions append-only)
→ evaluation(backtest/walk_forward/metrics/calibration) → dashboard(FastAPI)
```
Modules: `config`, `ingestion`, `features`, `regime`, `strategies`, `trade_signal`, `risk`, `decision`, `portfolio`, `evaluation`, `storage`, `dashboard`, `agents`, `main.py`.

## Modules That Must Not Be Casually Modified
- `risk/risk_engine.py`, `risk/limits.py`, `risk/position_sizing.py` — 9 vetoes are safety-critical.
- `ingestion/validation.py`, `ingestion/market_data.py` — data integrity gates.
- `trade_signal/` — renaming already fixed shadowing; do not rename again without stdlib test.
- `storage/database.py` — WAL + append-only trigger on `decisions`.
- `tests/test_all.py` — regression gate; any new subsystem must keep it green (Task 22).
- `dashboard/app.py` `/health` contract — must remain 200.

## Baseline Commit/State Reference
No git repo (standalone dir). Snapshot: 2026-09-02, all files under `/root/trading-agent`, DB `storage/trading.db` with 12 decisions. Verified by running `tests/test_all.py`, `/health`, and `fetch_klines`.
