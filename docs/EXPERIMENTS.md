# EXPERIMENTS

## Registry
Table `experiments` in `storage/trading.db` (WAL). Created by `storage/experiments.py` `ensure_exp_tables()`.

Fields: id, ts, model_version, strategy_version, feature_version, config (JSON), dataset (JSON), train_start, train_end, val_start, val_end, test_start, test_end, metrics (JSON), conclusion, status.

Statuses: EXPERIMENTAL → VALIDATED → PRODUCTION | REJECTED → DEPRECATED. No silent promotion — use `set_status(id, status)` explicitly.

## Versioning
- feature 0.1.0 (`features/technical.py` — EMA20/50 SMA20 RSI14 ATR14 momentum returns volatility)
- strategy 0.1.0 (`strategies/*` — trend/momentum/breakout/mean_reversion)
- model/ProbModel 0.2.0 (`evaluation/prob_model.py` logistic baseline 7 features, horizon 4, threshold 0.005)
- prompt not yet versioned (AI layer not active — Phase 2 interface only, per Task 18)
- risk config versioned via `config/settings.yaml` snapshot stored in `experiments.config`

Every `quant_results.json` row + every `scripts/run_quant_validation.py` call inserts one `experiments` row per symbol with dataset_id + row_count.

## Creating an experiment
```python
from storage.experiments import create_experiment
create_experiment("quant_BTCUSDT_1725", config={"fee":0.0004,"slippage":0.0005,"limit":600},
                  dataset={"symbol":"BTCUSDT","dataset_id":5,"row_count":600},
                  metrics={"pnl":983,"win_rate":0.61}, conclusion="trend promising, needs OOS", status="EXPERIMENTAL",
                  versions={"model":"0.2.0","strategy":"0.1.0","feature":"0.1.0"})
```

## Listing / promotion
```python
from storage.experiments import list_experiments, set_status
list_experiments()[:5]
set_status("quant_BTCUSDT_1725","REJECTED")  # or VALIDATED / PRODUCTION after human review
```

Dashboard: `GET /api/experiments` returns last 20.

## Current experiments (auto run 2026-09-02)
- `quant_BTCUSDT_*` — 600×1h BTCUSDT, trend PF 2.06 (EXPERIMENTAL) — not promoted due walk-forward degradation.
- `quant_ETHUSDT_*` — 600×1h ETHUSDT, trend PF 1.95 (EXPERIMENTAL).
All remain EXPERIMENTAL. No production promotion — out-of-sample failure blocks it (walk-forward split1/split2 negative).

## Governance (spec §34/48)
EXPERIMENTAL → must pass backtest (fees) + walk-forward (no leakage) + calibration check + paper reconciliation before VALIDATED.
VALIDATED → human approval required before PRODUCTION.
Never let experimental model replace production logic automatically.
History immutable — status updates only append, never delete rows.

## Reproduce
```
python3 scripts/run_quant_validation.py  # inserts new rows
python3 -c "from storage.experiments import list_experiments; print(list_experiments()[:2])"
```
