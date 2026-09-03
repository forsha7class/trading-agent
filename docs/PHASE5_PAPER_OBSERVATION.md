# PHASE 5 — PAPER OBSERVATION REPORT

> Date: 2026-09-03. Phase 5 PRD Task 4/5/6.
> Frozen candidate: RegimeGatedTrend (`docs/PAPER_FINAL_SPEC.md`).

## Observation result
**PAPER STATUS: INSUFFICIENT DATA.**

The Phase-5 paper observer (`scripts/run_phase5_paper.py`) injected the frozen
RegimeGatedTrend on the newest available live 1h candles. Result:

| Symbol | Fresh candles post-Phase-4-TEST | Status |
|---|---|---|
| BTCUSDT | 3 | INSUFFICIENT_DATA |
| ETHUSDT | 3 | INSUFFICIENT_DATA |

**Why:** the Phase-4 validation fetched and evaluated 1h data through the latest
available live candle (2026-09-03 05:00 UTC). The newest live bars are therefore the
**same data** already used as the tail of the Phase-4 TEST segment. Only ~3 candles
exist after the Phase-4 window cutoff — far below the `>=60` needed for a causal
feature/regime warm-up. There is no genuinely forward, non-overlapping paper window
to observe yet.

## Task 5 — Paper metrics
Not computable — zero paper trades observed in a non-overlapping forward window.
No win rate / expectancy / PF / PnL / MDD / streak / holding / MAE / MFE / exit-reason
statistics are claimed. **No statistical validation is asserted from zero sample.**

## Task 6 — Research vs paper comparison
Because the paper window produced no observations, the comparison is recorded as an
explicit **gap**, not a silent pass:

| Field | OBSERVED (paper) | EXPECTED (Phase-4 research OOS) | DIFFERENCE | POSSIBLE CAUSE | UNKNOWN |
|---|---|---|---|---|---|
| trade frequency | 0 (insufficient window) | BTC ~24/6000 bars; ETH ~7 | cannot assess | no forward data yet | yes |
| avg R / expectancy | — | BTC +31.78; ETH +19.55 | cannot assess | — | yes |
| win rate | — | BTC 2.68 PF; ETH 1.85 PF | cannot assess | — | yes |
| drawdown | — | small (few trades) | cannot assess | — | yes |
| holding time | — | within 20-bar horizon | cannot assess | — | yes |
| MAE / MFE | — | enrichment available | cannot assess | — | yes |
| stop/target behavior | — | SL/TP within horizon | cannot assess | — | yes |

**Conclusion:** research vs paper mismatch is UNKNOWN because no forward paper sample
exists. Per PRD, this is reported honestly rather than inflating significance. The
frozen spec stays frozen; continued live data accumulation over days/weeks is the
path to a real paper observation.

## Next forward step (not Phase 6)
Keep the frozen candidate running in paper mode; re-run `scripts/run_phase5_paper.py`
once ≥60 fresh post-Phase-4 candles accumulate (≈2.5 days of 1h data). Until then the
honest status is PAPER: INSUFFICIENT EVIDENCE.
