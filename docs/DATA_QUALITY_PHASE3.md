# DATA QUALITY — Phase 3

## BTCUSDT 1h
- count: 1200 valid True reason OK
- gaps: 0 dups: 0 OHLC: validated UTC source: Binance REST public (fetch_history paginated), dedup by open_time, gap>1.5*interval

## ETHUSDT 1h
- count: 1200 valid True reason OK
- gaps: 0 dups: 0 OHLC: validated UTC source: Binance REST public (fetch_history paginated), dedup by open_time, gap>1.5*interval

Expanded from 600 to 1800 bars (fetch_history), evaluated on most recent 1200 for reproducibility; full 1800 stored in DB (datasets).
