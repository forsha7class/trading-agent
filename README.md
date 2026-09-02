# Smart Crypto Trading Agent — MVP

Risk-first, decision-support system. Output: LONG / SHORT / NO_TRADE. Never executes real trades.

## Quickstart
```
cd /root/trading-agent
python3 -m pip install -q -r requirements.txt   # httpx, fastapi, uvicorn, numpy, pydantic, pyyaml
python3 main.py health                          # system health
python3 main.py run --symbols BTCUSDT ETHUSDT --timeframe 1h
python3 main.py backtest --symbol BTCUSDT --timeframe 1h --limit 600 --walk
python3 tests/test_all.py                       # 10 test groups, all MUST pass
python3 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8000  # dashboard at http://localhost:8000
```

## Architecture deviation
- `trade_signal/` instead of `signal/` — avoids shadowing stdlib `signal` (broke `anyio`/`uvicorn` otherwise). Interfaces identical.
- Derivatives/orderbook Tier2 stubbed (Binance REST `fetch_orderbook` ready, not required for MVP).
- LLM layer bounded JSON, optional (no key ⇒ graceful degrade to NO_TRADE-safe).

## Pipeline (enforced order)
market_data → validation → features → regime → 4 strategies → ensemble → probability → MTF → risk(9 vetoes) → AI review(bounded) → decision → paper_portfolio → DB → evaluation

No module bypasses risk. Fail-closed → NO_TRADE.

## Risk vetoes (9, tested)
NO_MARTINGALE, NO_AVERAGING, NO_REVENGE, NO_STALE_DATA, NO_ILLIQUID, NO_EXCESS_LEVERAGE, NO_RISK_OVERRIDE, NO_INVALID_RR, NO_CRITICAL_FAILURE

Defaults: risk/trade 0.5% (0.25-0.75% bounds), daily loss 2%, max positions 3, leverage ≤3x, min RR 1.5. All via `config/settings.yaml` + env.

## NO_TRADE reasons (explicit)
DATA_INVALID, DATA_STALE, INSUFFICIENT_DATA, REGIME_UNCERTAIN, WEAK_SIGNAL, CONTRADICTORY_TF, RR_INSUFFICIENT, etc.

## Evaluation
- Backtest includes fees 0.04% + slippage 0.05%, causal features only, SL/TP simulation.
- Walk-forward shows regime degradation (phase 0: +34% pf 4.9, phase 2: -9% pf 0.41) — overfit warning, not hidden.
- Baselines: compare vs buy-hold in `main.py backtest` output.

## Files
See ARCHITECTURE_REVIEW.md for full review. DB at `storage/trading.db` (WAL, append-only decisions).
