# PHASE 5 — FINAL PAPER SPEC (FROZEN)

> Frozen BEFORE any Phase 5 paper observation. Not retuned on observed outcomes.
> Candidate: **RegimeGatedTrend** — the same regime-gated trend candidate frozen and
> OOS-evaluated in Phase 4. See `docs/PHASE4_FROZEN_SPEC.md`.
> Date frozen: 2026-09-03. Git commit of source: `fd29f57`.

## Purpose
Final controlled paper observation of the frozen candidate on available live data,
per Phase 5 PRD Task 2/4. This is a decision-support observation, not a profitability
claim and not a real-money path.

## Frozen Configuration (identical to Phase 4 frozen values)

| Field | Value |
|---|---|
| Strategy | `RegimeGatedTrend` (`evaluation/regime_gating.py`) → delegates `TrendStrategy` |
| Name | `trend_gated` (version 0.1.0) |
| Symbols | BTCUSDT, ETHUSDT |
| Timeframe | `1h` (primary) |
| Regime gate (ALLOW) | `{TREND_BULL, TREND_BEAR}` only |
| Regime gate (REJECT → NEUTRAL) | RANGE, HIGH_VOL, LOW_VOL, UNCERTAIN (+aliases) |
| Trend logic | LONG if `ema20>ema50 and close>ema20`; SHORT if `ema20<ema50 and close<ema20`; else NEUTRAL |
| Strength | `min(1, sep*40)+mom_boost`, sep=`|ema20-ema50|/close`, mom_boost=`clamp(|mom|*8,0,0.3)` aligned else −0.1; RSI 78/22 dampens ×0.7 |
| Trigger threshold | `strength >= 0.35` |
| Min bars | `>= 50` (ema50 availability) |
| Horizon | `20` bars (forward SL/TP window `i+1..i+20`, no overlap) |
| Stop | `entry ∓ ATR14*1.8` (causal ATR14) |
| Target | `entry ± |entry−stop| * min_rr` |
| Min RR | `1.5` |
| Risk per trade | `0.005` (0.5%) |
| Max exposure | `max_positions 3`, `max_leverage 3.0`, `daily_loss_limit 0.02` |
| Fee | `0.0004` (4 bps/leg) |
| Slippage | `0.0005` (5 bps adverse, entry+exit) |
| Execution | realistic: `eff_entry=entry±entry*slippage`, `eff_exit=exit±exit*slippage`, fees applied, pnl=gross−fees. Causal — decision at bar T uses only candles up to T |

Source of truth for these numbers: `scripts/run_phase4_validation.py` FROZEN dict +
`config/settings.yaml`. Feature/strategy/regime/settings versions: `0.1.0`.

## Paper execution assumptions
- No real orders. Decision chain is simulated end-to-end: `live candles → features →
  regime → RegimeGatedTrend → risk → paper decision → paper SL/TP close`.
- MAE/MFE and exit reason recorded per trade.
- Observation is a **single forward window on the newest available live 1h data** that
  follows the Phase 4 TEST segment (i.e. no overlap with the test data used for the
  Phase 4 OOS claim).
- Signal validity window = within-horizon SL/TP resolution; signals not closed within
  `horizon=20` bars are force-closed at bar `i+horizon` (same rule as Phase 4 eval).

## Evaluation horizon & reporting
- Metrics per Task 5 (trade count, win rate, expectancy, avg R, PF, PnL, MDD, losing
  streak, avg holding time, MAE, MFE, exit reason), split LONG/SHORT + TREND_BULL/BEAR
  where sample allows.
- **No statistical validation claimed from a small sample.** If sample insufficient,
  report PAPER: INSUFFICIENT EVIDENCE.

## Freeze rule
These numbers are fixed for the Phase 5 observation. Any change requires a new spec
version and a fresh observation window. No strategy tuning occurs in response to
observed paper outcomes.
