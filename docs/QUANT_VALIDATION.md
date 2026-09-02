# QUANT VALIDATION — Phase 2 (2026-09-02, reproducible run)

> Purpose: determine whether the system has a measurable, reproducible edge — not to maximize backtest PnL.
> This report is generated from `scripts/run_quant_validation.py` → `docs/quant_results.json`. Do not edit numbers by hand.

Run: `python3 scripts/run_quant_validation.py` (fetch 600×1h BTCUSDT+ETHUSDT live, fee 0.0004 slippage 0.0005).

## Data
- Source: Binance REST public `/api/v3/klines` via `ingestion/market_data.fetch_klines` with 429 backoff; stored via `ingestion/dataset.store_dataset` (dedup by `open_time`, gap>1.5*interval → MISSING_CANDLE, validation via `ingestion/validation`).
- Symbols: BTCUSDT (65129→76820, 600 candles, dataset 5), ETHUSDT (1924→2386, 600 candles, dataset 6). Configured universe supports 5m/15m/1h/4h/1d, `config/settings.yaml` symbols=[BTCUSDT,ETHUSDT,SOLUSDT].
- Period: most recent 600×1h (~25 days) per symbol; timestamps preserved; duplicates rejected; metadata in `datasets` table (id, symbol, timeframe, start_ts, end_ts, row_count, source, validation, downloaded_at).
- Quality: `validate_candles` PASS on fetched sets; no missing OHLC; order intact. One known limitation: Binance base without `timeZone` param — times UTC.

## Strategies (per-symbol realistic execution — fee/slippage/ATR stop RR1.5 horizon20)
Source: `evaluation/strategy_eval.evaluate_all` (causal features, no leakage — `tests/test_leakage.py` PASS).

| Symbol | Strategy | Trades | Win% | PF | Expect | MDD | PnL (on $10k) | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---|
| BTCUSDT | Trend | 41 | 61.0 | 2.06 | 23.98 | 5.1% | +983 | **promising** in this window only |
| BTCUSDT | Momentum | 184 | 31.0 | 0.49 | -15.73 | 32.2% | -2894 | **weak** — overtrades, negative EV |
| BTCUSDT | Breakout | 98 | 45.9 | 0.93 | -2.23 | 11.7% | -219 | **inconclusive** — near breakeven |
| BTCUSDT | MeanReversion | 17 | 5.9 | 0.08 | -43.75 | 7.6% | -744 | **rejected** |
| ETHUSDT | Trend | 30 | 60.0 | 1.95 | 21.44 | — | +643 | **promising** (same caveat) |
| ETHUSDT | Momentum | 197 | 45.7 | 1.05 | 1.33 | — | +262 | **inconclusive** (bare breakeven, regime dep) |
| ETHUSDT | Breakout | 90 | 43.3 | 0.90 | -3.11 | — | -280 | **inconclusive** |
| ETHUSDT | MeanReversion | 21 | 19.0 | 0.30 | -28.01 | — | -588 | **rejected** |

## Regimes (by_regime from same eval; detector 6 labels)
- Trend's edge concentrates in TREND_BULL: BTC trend 24 trades 66.7% win exp 32.34 pnl 776; LOW_VOL 15 trades 53.3% exp 12.5. RANGE n=2 insufficient.
- Breakout also only wins in TREND_BULL (BTC 17 trades 76.5% exp 37.4) but loses in LOW_VOL (-12.0 exp).
- Momentum loses everywhere on BTC; on ETH it wins only in TREND_BULL (32 trades 78.1% exp 39.09) but loses in RANGE/LOW_VOL — regime filtering could help but not yet implemented as gate.
- MeanReversion negative in every regime — no qualifying regime.
- Takeaway: regime filtering (restrict to TREND_BULL) would improve hit rate but sample sizes for non-bull regimes are small; needs larger multi-month dataset before hardening.

## Probability (prob_model 0.2.0 — logistic baseline 7 features, horizon 4, threshold 0.005)
Training: 70% train / 30% test split per symbol inside `run_quant_validation.py`. Prob outputs are `p_up/p_down/p_flat` bounded 0.05–0.85, not heuristic score.

- BTC brier_up 0.1241, ETH 0.1659 (lower is better; 0 = perfect, 0.25 = naive).
- Bucket report (target=up): predictions are concentrated in low-confidence band; high buckets empty, so calibration cannot be assessed. BTC buckets 0.50–0.80 all count 0; ETH only two low buckets with 1 each and gap 0.52–0.55 (predicted 0.526 but freq 0). High-prob events (≥0.65) = 0 in this regime — model is under-confident and not discriminating.
- Conclusion: **uncalibrated / inconclusive** — statistical test exists (`evaluation/calibration_ext.bucket_report`, `brier`, `log_loss`, `tests/test_phase2.py` PASS) but data show the logistic baseline has no measurable edge over chance on this window. Do not use prob as trade trigger without larger labeled dataset and isotonic/platt calibration.

## Risk
- Hard vetoes: 9 rules (`risk/risk_engine`) — martingale/averaging/revenge/stale/illiquid/leverage/risk_override/invalid_RR/concentration — all passing in `tests/test_all.py` + `tests/test_risk_scenarios.py` (10 scenarios: normal/extreme vol, wide/narrow stop, RR, liquidity, daily limit, multi-position, conflict). Position sizing exact: `size = allowed_risk / stop_distance` verified numerically (50/2→25).
- Backtest portfolio drawdown: trend BTC 5.1% vs momentum 32.2%; aggregate realistic backtest `run_backtest` (60-bar synthetic ensemble, RR1.5) → BTC pnl -400, ETH -571 on this 600-bar window (not the same as per-strategy eval — reflects ensemble+risk filtering).
- No risk violations observed; unrealistic fills are not assumed — `evaluation/execution.py` applies slippage+fees; `realistic_backtest` is production report path.

## Baselines (evaluation/baseline_compare)
- BTC buy_hold return +17.86% (1 trade, mdd 5.1%); ETH +23.91% (mdd 6.4%) — strong up regime biases results. Agent ensemble underperforms buy_hold on this window.
- Simple baseline (SMA20/50 crossover proxy) and naive coinflip via `compare()` — returns/mdd fields present in `quant_results.json` baselines; on this micro-window simple tech is not the bottleneck — strategy selection is.
- Requirement honored: never claim edge from gross PnL; all reported pnl is fee+slippage inclusive.

## Walk-Forward (3 splits, 150/150, no future leakage — i+1 window, `evaluation/backtest.walk_forward`)
- BTC: split0 train150/test150 pnl +4444 return +44.45% pf 6.03 wr 83.5% → split1 -272 -2.73% pf 0.81 → split2 -871 -8.72% pf 0.42. ETH similar: +2301 → -563 → -510.
- Interpretation: **severe degradation** — first split (early lower-price regime) highly overfit; OOS collapses. Parameter stability FAIL. This matches the baseline note that split0 +34%→split2 -9% existed in Phase 1; Phase 2 confirms with realistic fees and larger window. System must NOT be promoted without regime-robust tuning and longer history.

## NO_TRADE (evaluation/notrade_analysis — historical mode, stale veto neutralized for old windows)
- Rejection rate: BTC 44.7%, ETH 48.0% (traded  ~55% / 52%).
- traded_win_rate: 0 in this window under tight 0.005 threshold eval (future ret proxy); rejected_would_win_rate: 0.46–0.48 not meaningful because rejected set includes flat moves counted as wins in proxy. EVs: ev_traded BTC 0.0039 vs ev_rejected 0.24; ETH 0.10 vs 0.27. `filter_adds_value = false` on both.
- Conclusion: on this labeling (horizon 4, 0.005), the decision filter does **not** add value — it rejects at ~45% without improving EV. NO_TRADE is functioning as a safety valve (risk/consistency), but not yet as an alpha filter. Needs threshold tuning and longer horizon study before claiming filtering edge.

## Conclusion (per-strategy classification — marketing language forbidden)
- **Trend Following — promising (provisional):** Positive PF and expectancy in both symbols, concentrated in TREND_BULL. But walk-forward shows it does not survive regime shift; sample small. Keep as candidate, gate by regime and require OOS replication on ≥6 months multi-symbol before even paper promotion.
- **Momentum — weak (BTC) / inconclusive (ETH):** BTC strictly negative; ETH marginal +1.33 exp but only in TREND_BULL. High trade count (184–197) amplifies fees. Reject for general use; revisit only with regime gate + lower frequency variant.
- **Breakout — inconclusive:** Near-breakeven; wins in TREND_BULL, loses in LOW_VOL. Needs execution refinement (spread/slippage model) and RANGE vs bull discrimination.
- **Mean Reversion — rejected:** PF 0.08–0.30, expectancy -28 to -43 in every regime. No evidence of edge on hourly crypto in this period. Do not promote; archive as counterexample.
- **Probability model — inconclusive/uncalibrated:** Exists and is tested, but buckets empty and brier alone not sufficient. Needs isotonic calibration + more data.
- **Overall system — measurable, not profitable OOS:** Phase 2 succeeded in *measurement* (leakage-cleared, fee-realistic, auditable). It did **not** demonstrate a durable edge. Do not claim profitability. Next phase must expand history, fix walk-forward overfit, and validate before any AI layer tries to act on these signals.

## Reproduce
```
cd /root/trading-agent && python3 scripts/run_quant_validation.py
# → docs/quant_results.json + experiments rows
# Tests: python3 tests/test_all.py && python3 tests/test_leakage.py && python3 tests/test_risk_scenarios.py && python3 tests/test_phase2.py
```
