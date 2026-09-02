# PAPER TRADING

## Architecture
```
LIVE DATA (Binance klines) → features → regime → strategies → ensemble → prob → risk → DecisionEngine
  → PaperEngine.tick(candles) → decision (LONG/SHORT/NO_TRADE) → paper_orders (CREATED) → PaperPortfolio.open_position → paper_trades (OPEN)
  → PaperPortfolio.update(next_candle) checks SL/TP → paper_trades (CLOSED), equity_curve updated
  → storage (sqlite WAL): decisions (append-only), paper_trades, paper_orders, paper_positions
```

## Components
- `portfolio/paper_portfolio.py` — `PaperPortfolio(equity)`: `open_position(decision)`, `update(candle)` (SL/TP), `metrics()` {trades, win_rate, profit_factor, max_drawdown, pnl}, `equity_curve`. Fees 0.0004 slippage 0.0005 via `evaluation/execution.py`.
- `portfolio/paper_engine.py` — `PaperEngine(equity).tick(candles, symbol, timeframe)` uses live `Coordinator.run` (never bypasses risk), writes decision → order → position chain, returns `{decision, decision_id, order_id, chain:{decision_id,order_id}}`. `update_market(candle)` forwards to portfolio. `status()` exposes equity/open/closed/metrics.
- Tables: `paper_trades(id, decision_id, symbol, side, entry, stop, tp1, size, fees, pnl, status, opened_at, closed_at)`, `paper_orders`, `paper_positions` (created in `ensure_paper_tables()`).

## Usage
```python
from portfolio.paper_engine import PaperEngine
from ingestion.market_data import fetch_klines
candles = fetch_klines("BTCUSDT","1h",limit=120)
pe = PaperEngine(equity=10000)
res = pe.tick(candles, symbol="BTCUSDT", timeframe="1h")  # → chain
# next bar arrives:
pe.update_market({"high": ..., "low": ..., "close": ..., "close_time": ...})
print(pe.status())
```

## Chain & Traceability
```
decision_id (decisions.id) → paper_orders.decision_id → paper_positions.order_id → paper_trades.decision_id
```
Every closed trade reconstructable to: market data timestamp (`open_time`/`close_time`), feature version (0.1.0), strategy version (0.1.0), prob model version (0.2.0), risk config (`config/settings.yaml` — risk_per_trade 0.005, min_rr 1.5), full decision JSON in `decisions` row. Experiment row in `experiments` records dataset_id + versions.

## Execution model
- entry = close at decision bar; eff_entry = entry ± entry*slippage; eff_exit similarly.
- fees = (abs(entry*size)+abs(exit*size))*fee on both legs.
- stop = strategy invalidation or ATR*1.8 fallback; TP = entry ± |entry-stop|*min_rr; evaluated `horizon` bars forward in evaluation; live paper uses next-candle SL/TP hit.

## Safety
- No real execution path exists; no exchange trading permissions; no keys used (Binance public REST only). Dashboard `/api/paper` read-only exposes open/closed counts.

## Reproduce
```
python3 -c "from portfolio.paper_engine import PaperEngine; from ingestion.market_data import fetch_klines; cs=fetch_klines('BTCUSDT','1h',limit=80); print(PaperEngine().tick(cs)['chain'])"
curl http://localhost:8000/api/paper
python3 tests/test_phase2.py  # → paper_engine chain PASS
```
