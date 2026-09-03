# PHASE 4 — FROZEN SPECIFICATION

> Locked before any FINAL TEST evaluation. Any change requires new spec version and re-run from TRAIN.

## Strategy: Trend (Phase 3 frozen, unchanged)

- **Name:** `TrendStrategy` (`strategies/trend.py`, version 0.1.0)
- **Logic:** LONG if `ema20 > ema50 AND close > ema20`, SHORT if `ema20 < ema50 AND close < ema20`, else NEUTRAL
- **Strength:** `min(1, sep*40) + mom_boost` where `sep=|ema20-ema50|/close`, `mom_boost = clamp(|mom|*8,0,0.3)` aligned else -0.1; RSI 78/22 dampens 0.7. Threshold `strength >= 0.35` to trigger.
- **Features (causal, no future):** `features/technical.build_features` on `candles[:i+1]` only. Requires `n>=50` (ema50). All indicators SMA/EMA/RSI/ATR with Wilder smoothing, causal.
- **Timeframe (primary):** `1h` — robustness checks on `15m` and `4h` use same params.
- **Horizon:** `20` bars (SL/TP lookup `i+1 .. i+20`, no overlap).
- **Stop:** `entry ± ATR14*1.8` (or `sig.invalidation` if provided, else ATR fallback). `ATR14` from `features.technical.atr14` on `candles[:i+1]`.
- **Target:** `entry ± |entry-stop| * min_rr`
- **RR (min):** `1.5`
- **Position sizing:** `size = (equity * risk_per_trade) / |entry-stop|`
- **Fees:** `0.0004` (4 bps) per leg
- **Slippage:** `0.0005` (5 bps) adverse on entry/exit
- **Execution:** realistic — `eff_entry = entry ± entry*slippage`, `eff_exit = exit ± exit*slippage` (adverse), `fees = (|entry*size|+|exit*size|)*fee`, `pnl = gross - fees`. No future high/low used beyond forward window; decision at T uses only `candles[:T]`.

## Regime Gate (LOCKED)

- **Detector:** `regime/detector.detect_regime(features, candles[:i+1])` — pure function, no IO, causal window.
- **Regimes (detector):** `TREND_BULL`, `TREND_BEAR`, `RANGE`, `HIGH_VOL`, `LOW_VOL`, `UNCERTAIN`
  - Spec aliases: `HIGH_VOL == HIGH_VOLATILITY`, `LOW_VOL == LOW_VOLATILITY` (treated as identical).
- **ALLOW:** `{"TREND_BULL", "TREND_BEAR"}`
- **REJECT:** `{"RANGE", "HIGH_VOL", "HIGH_VOLATILITY", "LOW_VOL", "LOW_VOLATILITY", "UNCERTAIN"}`
- **Wrapper:** `evaluation/regime_gating.RegimeGatedTrend(allowed=ALLOWED)` — returns NEUTRAL if regime not in ALLOW, else delegates to `TrendStrategy.generate`.
- **Freezing rule:** Allowed set fixed a priori (Phase 3). Do NOT tune on FINAL TEST. Do NOT add categories without demonstrated technical failure.

## Risk (unchanged, never bypassed)

- `config/settings.yaml`: `risk_per_trade 0.005` (stress 0.0025/0.0075), `daily_loss_limit 0.02`, `max_positions 3`, `max_leverage 3.0`, `min_rr 1.5`, `stale_multiplier 2.0`.
- 9 hard vetoes `risk/risk_engine` — fail-closed to NO_TRADE.
- `decision/engine` + `decision/state_machine` produce explicit NO_TRADE reasons. NO_TRADE thresholds NOT optimized in Phase 4.

## Data

- Source: `Binance REST /api/v3/klines` via `ingestion/market_data.fetch_klines` / `ingestion/dataset.fetch_history` (429 backoff, dedup by open_time, gap>1.5*interval flagged, validate via `ingestion/validation.validate_candles`).
- DB: `storage/trading.db` (WAL), tables `candles`, `datasets`, `decisions` (append-only), `paper_trades`.
- Timezone: UTC (Binance without timeZone param).
- Target coverage: ≥12 months per symbol on 1h where available. Chrono split TRAIN 60% / VAL 20% / TEST 20% (FINAL TEST untouched until gate frozen).

## Costs (baseline for OOS)

- `fee = 0.0004`, `slippage = 0.0005` (realistic). Stress: fee {0.0002,0.0004,0.0006} × slippage {0,0.0005,0.001}.

## Probability

- `evaluation/prob_model` (logistic, version 0.2.0) + `evaluation/isotonic` — RESEARCH ONLY, not in decision path. Evaluated raw vs isotonic but not used as gate.

## Paper Trading

- `portfolio/paper_engine.PaperEngine` chain `decision_id → order_id → position → trade`, SL/TP next-candle hit, MAE/MFE via `evaluation/mae_mfe`. No real execution path.

## Versions

- `feature_version 0.1.0`, `strategy_version 0.1.0`, `prob_model 0.2.0`, `regime 0.1.0`, `settings 0.1.0`.

## Leakage Guarantees

- Decision at T uses `candles[:T+1]` window only; `build_features`, `detect_regime`, `TrendStrategy.generate` are pure of that window; ATR/stop/target derived from same window; forward window `T+1..T+20` only reads `high/low` to resolve hit, never to compute signal. See audit in `scripts/run_phase4_validation.py:leakage_audit()`.
