# PHASE 5 — GLOBAL PROMOTION GOVERNANCE REVIEW

> Date: 2026-09-03. Phase 5 PRD Task 7/8.
> Purpose: final promotion decision for the regime-gated trend candidate under the
> current PRD scope, applying explicit global blockers. **Conservative by design.**

## Inputs (from Phase 4 OOS results, `docs/phase4_results.json`)
| Evidence | BTCUSDT | ETHUSDT |
|---|---|---|
| OOS (TEST) trades | 24 | 7 |
| OOS expectancy | +31.78 | +19.55 |
| OOS profit factor | 2.68 | 1.85 |
| Walk-forward (4 splits) | UNSTABLE (1/4 pos) | UNSTABLE (1/4 pos) |
| single_window_dependency | **True** | **True** |
| TRAIN evidence | negative | negative |
| Phase-4 gate (12 checks) | 11/12 → script VALIDATED | 9/12 → PROMISING |

## Explicit global blockers (Phase 5, conservative)
A positive OOS metric is **not** sufficient on its own. The following are treated as
blockers that cap the achievable status regardless of other passing checks:

1. **Severe walk-forward instability** — WF UNSTABLE with only 1/4 windows positive.
   → present on BOTH symbols.
2. **Single-window dependency** — aggregate edge carried by one window.
   → `single_window_dependency = True` on BOTH.
3. **Insufficient OOS sample** — BTC 24 trades is weak; ETH 7 is far below a usable
   inference sample.
4. **Calibration / robustness unresolved** — see Phase 3 (probability model research-only,
   not in decision path; not validated as a gate).
5. **Materially conflicting research evidence** — TRAIN segment negative while
   VAL/TEST positive on both symbols ⇒ edge not monotone across regimes/time.

## Per-symbol final status
| Symbol | Phase-4 gate (12) | Phase-5 status (with blockers) | Rationale |
|---|---|---|---|
| BTCUSDT | VALIDATED (11/12) | **PROMISING / HIGH UNCERTAINTY** | Positive OOS, but 24 trades, WF UNSTABLE, single-window dep → cannot be VALIDATED |
| ETHUSDT | PROMISING (9/12) | **INCONCLUSIVE** | 7 trades = insufficient sample, conflicting evidence |

## Global status
**GLOBAL: NOT READY FOR FULL VALIDATION (PROMISING).**

A single symbol with a positive OOS window does **not** promote the entire strategy.
The regime-gated trend is an encouraging research candidate whose edge is real but
unproven across regimes/timeframes/sample sizes. It remains a decision-support
candidate for continued paper observation, not a validated strategy.

## Strategy status interpretation
- `VALIDATED` would require: robust OOS sample (≥ ~50 trades/symbol), stable
  walk-forward, no single-window dependency, consistent regime behavior, and
  reproducible paper consistency. **None of these are satisfied yet.**
- Per PRD Task 8: "A positive OOS result with weak sample size and unstable
  walk-forward must not automatically produce VALIDATED." → applied.

## Consequence for paper trading
Candidate remains in **paper observation only**. No promotion to any autonomous or
higher-assurance status under the current PRD. Paper trading continues to be the
correct operating mode, and this Phase-5 paper window reported INSUFFICIENT DATA
(no post-Phase-4 forward sample yet accumulated).
