# BASELINE — Phase 3 Lock (2026-09-02)

Reference: `docs/BASELINE.md` (Phase 1) + `docs/ARCHITECTURE_PHASE2.md` + `docs/QUANT_VALIDATION.md`.

## Verified baseline (pre-Phase 3)
```
python3 tests/test_all.py         → ALL PASS (10 groups, 9 vetoes 11 checks)
python3 tests/test_leakage.py     → ALL PASS
python3 tests/test_risk_scenarios.py → ALL PASS
python3 tests/test_phase2.py      → ALL PASS
/fastapi TestClient /health       → 200 ok (7 modules ONLINE)
/api/quant|calibration|notrade|risk|paper|experiments → 200
Binance fetch_klines BTCUSDT 1h 3  → 76742 live OK
git: no repo (standalone dir /root/trading-agent), DB storage/trading.db WAL
```

## Phase 2 artifacts preserved
- `docs/quant_results.json` — 600×1h BTC(65129→76820,d5) ETH(1924→2386,d6) realistic eval, WF 3×150, calibration
- `storage/trading.db` datasets 5,6; experiments rows quant_BTC/ETH
- Modules: ingestion/dataset, evaluation/labels|strategy_eval|execution|prob_model|calibration_ext|baseline_compare|regime_analysis|notrade_analysis, storage/experiments, portfolio/paper_engine — all additive, no rewrite of Phase 1 risk/validation/trade_signal

## Non-negotiables for Phase 3
- No autonomous execution, no trading permissions, no key hardcoding, no risk limit increase.
- `tests/test_all.py` must stay ALL PASS; any regression stops new work.
- `signal/` remains `trade_signal/` (stdlib shadowing fix).
- New work is additive; do not optimize test set; do not hide bad windows.

## Phase 3 target deltas (additive only)
- Expand history 6–12m, quality report; regime-gated trend experiment (train/val vs test); isotonic calibration; rolling walk-forward ≥4 windows; param/cost stability; drawdown + Monte Carlo; MAE/MFE + exit reasons; promotion gate; robustness dashboard + `scripts/run_phase3_validation.py` → `docs/phase3_results.json` + `docs/ROBUSTNESS_PHASE3.md`.

State snapshot: 2026-09-02, trading.db 516K, quant_results present, dashboard 6 APIs 200.
