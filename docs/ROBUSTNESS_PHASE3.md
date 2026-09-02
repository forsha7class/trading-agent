# ROBUSTNESS — Phase 3

> Reproducible via `scripts/run_phase3_validation.py` → `docs/phase3_results.json`. Dataset: BTCUSDT+ETHUSDT 1h, most recent 1200 of 1800 fetched bars (fetch_history paginated), fees 0.0004 slippage 0.0005.

## 1. Dataset
- Expanded from 600×1h (Phase 2) to 1800×1h per symbol (fetch_history start_ms→end_ms paginated, Binance REST public), stored via ingestion/dataset store_dataset (dedup by open_time, gaps >1.5*interval flagged). Evaluation window 1200 most recent for speed/reproducibility (64305→76832 BTC, 1881→2415 ETH). Full 1800 in DB datasets table.
- `docs/DATA_QUALITY_PHASE3.md` validates: BTC 1200 valid OK gaps 0 dups 0, ETH 1200 valid OK, OHLC checked, UTC, no stale.

## 2. Data Quality
See DATA_QUALITY_PHASE3.md. validate_candles PASS; duplicate detection 0; expected vs actual gap 0; volume anomalies not flagged as failure; timezone consistent.

## 3. Strategy Results (realistic execution, by_regime)
| Symbol | Trend | Momentum | Breakout | MeanRev |
|---|---|---|---|---|
| BTC 1200 | 53t PF1.21 wr47% exp5.83 mdd6.1% pnl+309 | 435t PF0.50 exp-13.5 mdd62% pnl-5880 | 211t PF0.59 exp-12.5 mdd35% | 18t PF0.15 exp-38 |
| ETH 1200 | 60t PF0.66 wr? exp-11.3 mdd13.6% pnl-679 | 185t PF0.86 | 104t PF0.78 | 24t PF0.48 |
- Trend BTC still best but PF dropped from 2.06 (600 bars bull window) to 1.21 (1200 mixed) — bull-window effect confirmed.
- By regime: Trend BUY edge only in TREND_BULL (BTC 24t 66.7% exp30.3 pnl728; ETH similar), LOW_VOL negative (BTC 27t exp-16.2). Breakout same pattern. MeanRev negative in every regime. Momentum negative everywhere on BTC.

## 4. Regime Results
- TREND_BULL: trend+brea kout win; RANGE n=2 insufficient; LOW_VOL: all strategies lose except gated trend. UNCERTAIN/HIGH_VOL not populated in this dataset.

## 5. Regime Gating (ALLOWED={TREND_BULL,TREND_BEAR}, train/val vs test not tuned on test)
| Symbol | Base trades | Gated trades | Base PF | Gated PF | Verdict |
|---|---|---|---|---|
| BTC | 53 | 24 | 1.21 | 2.67 | Gating halves trades, more than doubles PF — but on same data (selection not yet OOS). Deletion test shows removing weak strategies improves robustness; gating must be validated OOS before promotion. |
| ETH | 60 | 7 | 0.66 | 1.85 | Same: fewer trades, higher PF but n=7 too small. |
- Gating evaluation uses RegimeGatedTrend(allowed) wrapper; NO test-set optimization — allowed set fixed a priori per spec. Still, result is in-sample; report as encouraging, not proven.

## 6. Calibration (isotonic PAVA, numpy-only)
- Train 70% / test 30%, horizon 4 threshold 0.005, label up/down/flat.
- BTC raw brier 0.1964 logloss 0.6299 → isotonic cal 0.2068 / 1.9095 improves=False. Buckets 0.50–0.80 all count 0 (BTC) or n=1 (ETH) — still too sparse. Calibrated bucket 0.80–1.0 n=1 avg 1.0 freq 0 gap 1.0 miscalibrated.
- ETH raw 0.2343 → cal 0.2439 improves False.
- Threshold analysis (0.5–0.75): BTC 0 trades at every threshold (model never exceeds 0.5 with confidence), ETH 1–2 trades precision 0–1 meaningless.
- Conclusion: isotonic pipeline works (tests PASS) but does NOT improve Brier and does not create usable thresholds. Model remains under-confident and uncalibrated. DO NOT USE as production gate. Needs larger history or different feature set.

## 7. Probability Thresholds
As above — no threshold yields sufficient trades with positive expectancy. Prob model not tradable yet.

## 8. Walk-Forward (rolling 4 splits, no leakage, i+1 windows)
- BTC 1200: split0 -2574 | split1 -3891 | split2 +3210 | split3 -1444 (metrics pnl). One winning window does not persist.
- ETH 1200: -1373 | -2080 | +3476 | -1546.
- Phase 2 3×150 showed +4444→-272→-871; Phase 3 4× shows same instability with different windows — degradation persists, parameter instability confirmed, not resolved by more data alone.
- All 4-window reports kept separate per spec; aggregation hidden.

## 9. Parameter Stability (Trend: horizon/min_rr)
- BTC: (18,1.5) pf0.99 exp-0.35 | (20,1.5) pf1.21 exp5.83 | (20,1.3) pf1.29 exp7.47 — variance moderate, not cliff, but ETH shows fragility: (18,1.5) pf0.55 exp-15.6 | (20,1.5) pf0.66 exp-11.3 | (20,1.3) pf0.80 exp-5.9 — small change does not collapse but also does not rescue edge.
- No giant grid search per spec; conclusion stable-ish on BTC, fragile on ETH.

## 10. Cost Sensitivity (Trend)
- BTC: fee0.02/slip0.0 pf1.29 pnl420 → 0.04/0.05 pf1.21 pnl309 → 0.06/0.10 pf1.13 pnl199 — edge survives worse costs but narrows.
- ETH: 0.02/0 pf0.71 pnl-561 → 0.04/0.05 pf0.66 pnl-679 → 0.06/0.10 pf0.60 pnl-795 — never profitable; costs worsen already negative.
- Robust only where base PF>1.

## 11. Drawdown (Trend, realistic)
- BTC max 6.14% duration 21 bars, worst streak 12; ETH 13.63% duration 58.
- Worst 5/10-trade sequences not separately computed — approximated via equity curve.

## 12. Monte Carlo (trade-sequence resampling, 300 iter, seed 42)
- BTC trend: terminal p5 9549 p50 10212 p95 11049, mdd p50 3.5% p95 8.2%, worst streak p95 10.
- ETH trend: p5 8732 p50 9324 p95 10119, mdd p50 8.4% p95 13.9%, streak 14.
- Not proof of future — robustness only.

## 13. NO_TRADE Analysis (historical-mode, stale-neutralized)
- BTC rejection 44% traded_wr 21% rejected_would_win 42% ev_traded -0.08 ev_rejected 0.50 filter_adds False.
- ETH similar 44% rejection, no EV advantage. NO_TRADE remains safety, not alpha filter — do not optimize for performance.

## 14. Paper Trading (PaperEngine + MAE/MFE + exit reasons)
- PaperEngine tick → decision→order→position chain; PaperPortfolio update returns hit SL/TP1; MAE/MFE via evaluation/mae_mfe compute_mae_mfe.
- Sample BTC trend trades: mae 5–30, mfe 15–40, exit reasons STOP_LOSS/TAKE_PROFIT/TIME_EXIT. Recording improved to include entry/stop/tp1/size/realized pnl/mae/mfe/holding/exit_reason in docs/phase3_results.json mae_mfe_sample and walk-forward. No real execution path.

## 15. Promotion Decisions (gate: 12 checks — history≥2000, leakage, costs, OOS exp>0, mdd<30%, trades 20–500, param stable, cost ok, regime understood, no WF degrade, paper ok, reproducible)
- VALIDATED requires ≥10/12 per code — but manual override: no strategy reaches VALIDATED for research scope because WF degraded and history <2000.
- **Trend BTC PROMISING** (pf 1.21, but WF unstable, gating doubles PF in-sample only). **Trend ETH INCONCLUSIVE** (pf 0.66 negative).
- **Momentum REJECTED** (BTC PF0.50, ETH PF0.86 inconclusive but high mdd, overtrades) — liability per deletion test.
- **Breakout INCONCLUSIVE** (PF0.59/0.78, only bull wins).
- **MeanReversion REJECTED** (PF0.15–0.48, negative every regime).
- No promotion to PRODUCTION. Deletion test: full ensemble not better than trend alone; removing momentum/breakout improves robustness.

## 16. Limitations (OBSERVED vs INFERRED vs UNKNOWN)
- OBSERVED: PF drops with more data; walk-forward unstable; isotonic does not help; thresholds empty; costs survive only where PF>1; NO_TRADE no EV gain.
- INFERRED: edge is regime-dependent (bull), not general; gating helps in-sample but needs OOS proof.
- UNKNOWN: whether longer history (>6 months) or different timeframe (4h/1d) would stabilize; whether regime detector itself is accurate; true live slippage distribution; MAE/MFE optimal stop distance without overfit.

## 17. Deletion Test
- Trend only PF1.21 vs momentum PF0.50 vs breakout PF0.59 vs mean PF0.15 — ensemble would be dragged down by weak legs. Document momentum/mean as liabilities for MVP exclusion.

## 18. Reproduce
```
python3 scripts/run_phase3_validation.py   # uses DB 1800 bars, evaluates 1200 window, writes phase3_results.json
python3 -c "import json,pathlib; print(json.loads(pathlib.Path('docs/phase3_results.json').read_text())['BTCUSDT']['gating'])"
python3 tests/test_phase3.py  # 10 checks
```

## 19. Classification Summary
- REJECTED: MeanReversion (both), Momentum BTC.
- INCONCLUSIVE: Breakout (both), Momentum ETH, Trend ETH.
- PROMISING: Trend BTC (only with regime gate, provisional).
- VALIDATED: none.
