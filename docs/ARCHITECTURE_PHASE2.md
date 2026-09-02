# ARCHITECTURE — Phase 2

## Pipeline (Phase 1 → Phase 2 additive, no rewrites)
```
Binance REST (public) → ingestion/market_data (429 retry) + ingestion/dataset (dedup, gap, validation, metadata)
        ↓
storage/database (sqlite WAL, FK, append-only decisions) — candles, datasets, decisions, paper_trades, experiments
        ↓
features/technical (EMA/SMA/RSI/ATR/momentum/returns/volatility) — causal only, no lookahead (leakage tests)
        ↓
regime/detector (6 regimes) → strategies (trend/momentum/breakout/mean_reversion, common generate interface)
        ↓
trade_signal/ensemble (regime-weighted) → trade_signal/probability (heuristic + prob_model) → trade_signal/mtf (weighted alignment + veto)
        ↓
risk/risk_engine (9 hard vetoes) + risk/position_sizing + risk/limits → decision/engine (16 NO_TRADE reasons) → decision/state_machine
        ↓
agents/coordinator (never bypasses risk) → agents/* bounded LLM (JSON, degrades without keys)
        ↓
portfolio/paper_portfolio + portfolio/paper_engine (paper_orders, paper_positions) → storage (chain: decision→order→position→trade)
        ↓
evaluation/* → scripts/run_quant_validation → docs/quant_results.json → dashboard/api/* → storage/experiments
```

## Module Invariants
- `signal/` stays `trade_signal/` (stdlib `signal` shadowing breaks anyio/uvicorn). Do not rename.
- `risk/` is fail-closed; coordinator cannot override. 9 vetoes tested in `test_all` + `test_risk_scenarios`.
- `ingestion/validation` + `features/technical` are causal — `test_leakage.py` asserts no future access, no normalization leakage.
- `storage/database` decisions remain append-only (trigger). Candle dedup by `open_time`.

## New in Phase 2 (additive)
- `ingestion/dataset.py` — `fetch_history` (paginated), `store_dataset` (dedup→validate→insert→datasets row), `load_dataset`, `dataset_metadata`.
- `evaluation/labels.py` — `make_labels(candles, horizon, threshold)` → {ret, label: up/down/flat, __future omitted}, horizon-configurable.
- `evaluation/strategy_eval.py` — per-strategy realistic execution (fee 0.0004, slippage 0.0005, ATR stop, RR 1.5, horizon), by_regime stats.
- `evaluation/execution.py` — `ExecutionConfig`, `apply_slippage`, `fees` (realistic vs ideal switch).
- `evaluation/prob_model.py` — interpretable logistic baseline `ProbModel` (7 features, 3-class via 3 binary logics, bounded 0.05–0.85), `train_prob_model`, `build_feature_matrix`.
- `evaluation/calibration_ext.py` — `brier`, `log_loss`, `bucket_report` (6 buckets), reliability.
- `evaluation/baseline_compare.py` — `compare(candles)` → buy_hold/simple/naive with return/mdd/trades.
- `evaluation/regime_analysis.py` — `regime_report`.
- `evaluation/notrade_analysis.py` — historical-mode (avoids stale veto on old windows), traded vs rejected EV.
- `storage/experiments.py` — `experiments`, `model_versions2` tables; `create_experiment`, `list_experiments`, `set_status` (EXPERIMENTAL/VALIDATED/PRODUCTION/REJECTED/DEPRECATED).
- `portfolio/paper_engine.py` — `PaperEngine.tick/update_market/status` with chain {decision_id, order_id}.
- `dashboard/app.py` — preserves `/health` 200; adds `/api/quant`, `/api/regime-performance`, `/api/calibration`, `/api/notrade`, `/api/paper`, `/api/experiments`, `/api/risk`.
- `scripts/run_quant_validation.py` — reproducible orchestration: fetch 600 1h BTC+ETH → evaluate_all → compare → train prob → calibration → walk_forward(3) → notrade → regime → realistic backtest → quant_results.json + experiments.

## Data Flow & Versioning
- Versions: `config/settings.yaml` 0.1.0; `trade_signal/probability` 0.1.0; `prob_model` 0.2.0. Every `quant_results.json` entry records dataset_id + versions via `experiments` rows. Future promotion requires explicit `set_status`.

## Failure Modes (fail-closed)
- Binance 429 → backoff retry. Empty/invalid candles → VALIDATION FAIL → NO_TRADE.
- Stale data in live ticks → risk veto. Historical windows use `data_ts=now` in `notrade_analysis` to avoid false stale on old candles (documented divergence; live path still vets staleness).
- Leakage → `test_leakage.py` fails gate. Walk-forward contamination → caller error (explicit i+1 loop).
- Dashboard `/health` per-module ONLINE derived from import+DB probe; degraded modules surface without crashing `/health`.

## Config Centralization
Single source `config/settings.yaml` (+ env overrides in `config/settings.py`): symbols, timeframes, timeframe_weights, risk_per_trade 0.005, daily_loss_limit 0.02, max_positions 3, max_leverage 3, min_rr 1.5, fee/slippage, binance_base, stale_multiplier, min_bars.

## What Was Not Changed
- No new runtime deps (numpy, httpx, fastapi only). No pandas. No autonomous execution. No trading permissions. No secret hardcoding.
- Existing 10-group `test_all` untouched except for additive new tests; original assertions still PASS.
