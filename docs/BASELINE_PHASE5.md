# PHASE 5 — BASELINE LOCK

> Date: 2026-09-03 (UTC)
> Git commit: `fd29f57` (phase4 frozen validation)
> Verified before any Phase 5 change.

## Verdict
**BASELINE HEALTHY — ALL PASS.** No healthy baseline module modified for Phase 5.

## 1. Full test suite (`tests/test_all.py`)
```
validation PASS · features PASS · regime PASS · strategies PASS
ensemble+prob PASS · risk vetoes PASS (11 checks) · decision PASS
state_machine PASS · backtest PASS · mtf PASS · db PASS
ALL TESTS PASS
```

## 2. Per-phase suites
| Suite | Result |
|---|---|
| `test_phase2.py` | ALL PHASE2 TESTS PASS |
| `test_phase3.py` | ALL PHASE3 TESTS PASS |
| `test_phase4.py` | ALL PHASE4 TESTS PASS |
| `test_leakage.py` | ALL LEAKAGE TESTS PASS |
| `test_risk_scenarios.py` | ALL RISK SCENARIO TESTS PASS |

## 3. Health (`main.py health`)
```
decisions: 1152 rows ONLINE
candles: 23036 rows ONLINE
paper_trades: 1 rows ONLINE
system_events: 1122 rows ONLINE
FEATURE ENGINE ONLINE
REGIME ENGINE ONLINE
```

## 4. Binance live fetch
`fetch_klines('BTCUSDT','1h',5)` → 5 candles OK, latest close 77243.99, ts 1788411600000. Live data path operational.

## 5. Repository state
- Branch `main` @ `fd29f57`, clean (no staged/unstaged changes at lock time).
- Phase 4 artifacts preserved: `docs/PHASE4_FROZEN_SPEC.md`, `docs/phase4_results.json`, `scripts/run_phase4_validation.py`, `tests/test_phase4.py`.

## 6. Non-negotiable constraints reaffirmed
- Risk vetoes (9) present and enforced (RiskEngine, fail-closed → NO_TRADE).
- No real order execution path (decision → paper only).
- LLM layer (`agents/llm.py`) bounded: never overrides hard risk, degrades to None (UNAVAILABLE) without key.
- No API keys hardcoded in repo (secrets via env only).

## Phase 4 interpretation carried forward (conservative)
Phase 4 script reported `VALIDATED` for BTCUSDT but this is **not** treated as strong validation:
- BTC OOS 24 trades, ETH OOS 7 trades — small samples.
- Walk-forward UNSTABLE, 3/4 windows negative, `single_window_dependency=True`.
- TRAIN evidence negative.
Edge concentrated in limited windows/regimes. Phase 5 proceeds conservatively.

Phase 5 scope: final paper validation (frozen config), limited AI review, governance, PRD closure. **No Phase 6.**
