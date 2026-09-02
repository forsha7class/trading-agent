# Smart Crypto Trading Agent — Architecture Review

## A. Existing Environment Review

| Area | Finding | Reuse / Decision |
|---|---|---|
| **OS** | Ubuntu 7.0.0-27-generic, 7.8GB RAM, 143GB disk, 1 CPU | adequate for MVP |
| **Python** | 3.14.4, PEP 668 enforced, `python` missing alias | use `python3` + venv at /root/trading-agent/.venv |
| **Installed libs** | numpy 2.5.2, fastapi 0.141, uvicorn 0.52, httpx 0.28, websockets 17.1, sqlite3 stdlib 3.46 | reuse; avoid pandas/ccxt heavy deps; compute indicators with numpy+stdlib |
| **DB** | sqlite3 binary missing but Python sqlite3 works; Hermes uses sqlite (kanban.db/state.db WAL) | use sqlite3 via stdlib, WAL, single file `storage/trading.db` |
| **Network** | `api.binance.com/api/v3/ping` returns `{}` | Binance REST chosen for MVP (no auth, OHLCV+24hr ticker, orderbook) |
| **Hermes infra** | gateway, cron, skills, memories, .env secrets | reuse `config.yaml` pattern (env vars), keep trading-agent isolated (not inside .hermes), cron for scheduler |
| **Existing agent abstractions** | skills (autonomous-ai-agents, email, etc), no trading code | trading-agent standalone; no coupling to Hermes skills |
| **Logging** | Hermes has structured logs; trading-agent needs own | stdlib `logging` + JSON formatter, file + stdout |
| **Dashboard** | Hermes TUI, but trading dashboard should be FastAPI+static HTML | FastAPI serves `/api/*` + static dashboard (no React build step) |
| **Testing** | no pytest installed | stdlib `unittest` or minimal pytest add only when needed |

**What can be reused:** httpx, fastapi, uvicorn, numpy, sqlite3, logging, dotenv via .env  
**What should be modified:** nothing to modify — greenfield project  
**What should remain isolated:** trading-agent must NOT write to Hermes DBs; secrets via env only; own venv

---

## B. Proposed System Architecture

```
                 +-------------------+     +-------------------+
  Binance REST -->| ingestion         |---->| storage (sqlite)  |
  (OHLCV, 24h,   |  market_data.py   |     |  candles, features|
   orderbook)     |  validation.py    |     +-------------------+
                 +---------+---------+                |
                           |                        v
                +----------v----------+   +-------------------+
                | features (numpy)    |-->| regime.detector   |
                | technical, vol      |   | TREND_BULL/BEAR/  |
                +----------+----------+   | RANGE/HIGH_VOL/   |
                           |              | LOW_VOL/UNCERTAIN |
                +----------v----------+   +---------+---------+
                | strategies/*        |             |
                | trend,momentum,     |<------------+
                | breakout,mean_rev   |
                +----------+----------+
                           |
                +----------v----------+
                | signal (ensemble +  |
                |  scorer + probability|
                |  + multi-TF)        |
                +----------+----------+
                           |
                +----------v----------+
                | risk_engine         |<-- config/settings.yaml (single source)
                | hard vetoes, sizing |
                +----------+----------+
                           |
                +----------v----------+
                | decision.engine     |
                | state_machine       |
                +----------+----------+
                           |
                +----------v----------+
                | agents (LLM bounded)|
                | analyst,reviewers,  |
                | decision_maker, coord|
                +----------+----------+
                           |
                +----------v----------+
                | portfolio (paper)   |--> storage (decisions, paper_trades)
                | backtest, walk_fwd  |    evaluation.metrics
                +---------------------+

  Dashboard (FastAPI) reads storage + exposes /health, /signals, /decisions
```

**Deviations from spec template:** merge `signal/` + `probability` into one package (avoid premature split); `ingestion/derivatives.py` stubbed (Binance funding/OI optional tier 2); `agents/` calls OpenAI-compatible LLM via httpx only when configured, else no-op (risk engine never bypassed).

**Interface contract (each module pure function / dataclass, no hidden IO):**
- `ingestion.validation.validate(candles) -> ValidationResult`
- `features.build(candles) -> Features`
- `regime.detect(features, context) -> RegimeResult`
- `strategies.*.generate(market_state) -> StrategySignal`
- `signal.ensemble.aggregate(signals, regime) -> CombinedSignal`
- `signal.probability.estimate(...) -> ProbDist {up,down,flat}`
- `risk.check(decision_ctx) -> RiskResult {approved, reason, position_size}`
- `decision.engine.decide(...) -> Decision {LONG,SHORT,NO_TRADE}`

---

## C. Data Model (SQLite)

```sql
candles(symbol TEXT, timeframe TEXT, open REAL, high REAL, low REAL, close REAL,
        volume REAL, open_time INT, close_time INT, PRIMARY KEY(symbol,timeframe,open_time))

features(symbol, timeframe, ts INT, ema20 REAL, ema50 REAL, rsi14 REAL, atr14 REAL,
         sma20 REAL, momentum REAL, vol REAL, ... , feature_version TEXT)

regimes(symbol, timeframe, ts INT, regime TEXT, confidence REAL, evidence JSON, version TEXT)

strategy_signals(id PK, symbol TEXT, ts INT, strategy TEXT, direction TEXT,
                 strength REAL, entry REAL, invalidation REAL, evidence JSON, version TEXT)

decisions(id PK, ts INT, symbol TEXT, timeframe TEXT, regime TEXT, signal TEXT,
          probability JSON, entry REAL, stop REAL, tp1 REAL, tp2 REAL,
          position_size REAL, risk_pct REAL, rr REAL, evidence JSON, counter_evidence JSON,
          reason TEXT, decision TEXT, versions JSON, data_ts INT)

paper_trades(id PK, decision_id FK, symbol TEXT, side TEXT, entry REAL, stop REAL, tp1 REAL,
             size REAL, status TEXT, pnl REAL, fees REAL, opened_at INT, closed_at INT)

system_events(ts INT, module TEXT, level TEXT, message TEXT, meta JSON)

model_versions(version TEXT PRIMARY KEY, component TEXT, created_at INT, meta JSON)
```

All timestamps INT (ms epoch). JSON columns TEXT storing JSON. WAL mode, foreign_keys ON. Audit logs append-only (no UPDATE on decisions).

---

## D. Agent Workflow (Coordinator)

```
1. fetch OHLCV (multi-TF) -> validate -> on fail => NO_TRADE {DATA_STALE}
2. build features (causal, no look-ahead)
3. detect regime
4. run strategy ensemble (4 strategies)
5. signal ensemble -> score, supporting/contradicting
6. probability model (calibrated heuristic -> versioned; ML later)
7. multi-TF confirmation (weighted alignment + hard veto)
8. risk_engine.check -> if reject => NO_TRADE {risk reason}
9. LLM review (if enabled; bounded JSON; failure => degrade, still NO_TRADE-safe)
10. decision.engine -> LONG/SHORT/NO_TRADE + reason
11. persist decision + paper_trade (if signal)
12. evaluation metrics update
```

Coordinator enforces order; no module bypasses risk. LLM output validated against schema; hallucinated fields discarded.

---

## E. Implementation Roadmap (verifiable milestones)

| Phase | Deliverable | Verify |
|---|---|---|
| P1 | config/settings.yaml, logging, storage/database.py, models | `python -m storage.database` creates tables; test inserts |
| P2 | ingestion/market_data (Binance REST), validation | fetch BTC 1h -> validate -> store; test stale/duplicate/OHLC invalid |
| P3 | features/technical (EMA,SMA,RSI,ATR,momentum,vol) | unit tests vs known values; no look-ahead check |
| P4 | regime/detector | unit tests for each regime label |
| P5 | strategies/base + 4 strategies | each returns StrategySignal; disagreement test |
| P6 | signal/ensemble + scorer | aggregation + regime weighting test |
| P7 | signal/probability + calibration | Brier/logloss calc; versioned |
| P8 | risk/risk_engine + position_sizing + limits | hard veto tests (risk>limit, RR, leverage, concentration, stale, illiquid) |
| P9 | decision/engine + state_machine | LONG/SHORT/NO_TRADE with reason; transition tests |
| P10 | portfolio/paper_portfolio | simulate entry/SL/TP/fees/slippage |
| P11 | evaluation/backtest, walk_forward, metrics | backtest with fees; Sharpe/Sortino/pf/winrate; walk-forward splits |
| P12 | agents/* (bounded LLM JSON) | prompts forbid invention; fallback to NO_TRADE on failure |
| P13 | dashboard (FastAPI) | /api/health, /signals, /decisions, /performance; static HTML |
| P14 | hardening: error handling, health, tests | all veto tests pass; system failure => NO_TRADE |

Each phase: code -> test -> verify -> doc before next.

---

## F. Risk & Failure Analysis

| Failure Mode | Impact | Mitigation |
|---|---|---|
| Binance API down / 429 | stale data -> false signal | validation => NO_TRADE, retry with backoff, cache last valid |
| WS disconnect / gap | missing candles | gap detection => NO_TRADE, backfill via REST |
| Duplicate/out-of-order candles | indicator corruption | dedupe + sort + strict OHLC check (high>=low etc) |
| Feature NaN / insufficient history | regime misclassify | require min bars (e.g. 50 for EMA50); else UNCERTAIN => NO_TRADE |
| Strategy overfit / degradation | false edge | ensemble bounded weights, walk-forward, baseline compare |
| Probability miscalibration | overconfidence | Brier/calibration tracking, versioned, never trust LLM confidence |
| Risk engine bug / bypass | capital loss | hard veto tests, coordinator never skips risk, fail-closed (NO_TRADE) |
| LLM hallucination | invented data | bounded JSON schema, evidence must come from quant layer, cannot override risk |
| DB corruption | loss of audit | WAL, append-only decisions, periodic backup |
| Clock skew | feature timestamp wrong | NTP check, reject if data_ts > now+60s |
| Leverage/exposure miscalc | liquidation | configurable caps (max 3x, 1-3 positions, 0.25-0.75% risk), tested |
| Slippage/fees ignored | inflated backtest | include 0.04% taker + 0.05% slippage in paper/backtest |

First-class NO_TRADE reasons enumerated in decision engine (stale, illiquid, high_vol, RR, budget exhausted, etc.).

---

## G. MVP Definition

**In MVP:**
- Binance REST only (one exchange), BTC/ETH/SOL (+1 configurable)
- OHLCV + 24h ticker for liquidity; orderbook optional stub
- Tier1 features (EMA,SMA,RSI,ATR,momentum,vol); Tier2/3 stubs
- 4 strategies, regime-aware ensemble, heuristic probability (calibrated)
- Multi-TF weighted alignment (configurable)
- Risk engine with hard vetoes, position sizing, RR>=1.5
- Decision engine LONG/SHORT/NO_TRADE + reason
- Paper trading + backtest + walk-forward + metrics + baselines
- Bounded LLM review (optional, never overrides risk)
- SQLite audit log, FastAPI dashboard (health, signals, history, performance)

**NOT in MVP (deferred):**
- Autonomous execution / order placement (read-only)
- Unlimited symbols / exchanges
- Full orderbook microstructure, funding/OI live (architecture ready, stub)
- News/sentiment/on-chain live feeds (stub + manual inject)
- ML retraining pipeline auto-promotion (manual approval gate)
- Advanced auth/secret manager beyond env vars
- Complex frontend framework (plain HTML+JS)

MVP complete when all 24 acceptance criteria (§49) pass + veto tests green + `NO_TRADE` default on any critical failure.
