# Test Isolation & Safety

## Incident (2026-09-03 23:44 UTC)

A fake **BTCUSDT LONG** alert was delivered to Telegram: entry `52640.50501659338`,
stop `52262.42`, "Signal: 6", timestamp `1788479061865` — while real BTC was
trading ~81,000. The alert was **not a real signal**. It was emitted by the test
suite, which ran `PaperEngine` end-to-end on synthetic candles (~50,800 rising
+10/bar) and notified Telegram through the coordinator.

### Root cause

1. **No Telegram send guard.** `telegram_notifier` read credentials from env and
   sent whenever a token was present. Tests that drive `Coordinator` /
   `PaperEngine` therefore delivered real messages to the production chat
   (6 sends in 4 s, logged in `/tmp/paper_runtime_test.db` system_events).
2. **No DB isolation for most test files.** Only `test_paper_runtime.py` set
   `DB_PATH` to a temp file. `test_all.py`, `test_leakage.py`, `test_phase2.py`,
   `test_phase3.py`, `test_phase4.py` called `init_db()` / `store_dataset()` /
   `PaperEngine` against the **production** `storage/trading.db`, inserting
   `TEST`/`TSTP3`/`PH2` symbols and `NO_TRADE STALE` rows (decisions 1286, 1289,
   1290, 1291) into live data.

### Affected tests (fixed)

- `tests/test_all.py` — inserted `TEST` decision rows into prod DB
- `tests/test_leakage.py` — `store_dataset(TEST)` into prod DB
- `tests/test_phase2.py` — `store_dataset(PH2)` + `PaperEngine.tick` (notify path)
- `tests/test_phase3.py` — `store_dataset(TSTP3)` + `PaperEngine`-adjacent evals
- `tests/test_phase4.py` — `PaperEngine.tick` (notify path)
- `tests/test_paper_runtime.py` — already DB-isolated; coordinator path could still notify
- `tests/test_risk_scenarios.py` — no DB writes (risk engine only)

### Fix 1 — Telegram send guard (`agents/telegram_notifier.py`)

`notify()` now refuses to send unless `TRADING_TG_SEND=1`:

- `TRADING_TG_SEND != "1"` → returns
  `{"sent": false, "deduped": false, "reason": "telegram_send_disabled", "error": null}`
  and never touches the network, regardless of credentials present.
- `TRADING_TG_SEND=1` + credentials → production behavior unchanged.
- Formatting/dedup/cooldown semantics untouched; no secrets logged.
- Production launchers (`run_detached.sh`, gateway env) are unaffected only if
  they export `TRADING_TG_SEND=1` — **verify before restarting the runtime.**

### Fix 2 — DB isolation (`tests/conftest.py`)

Every test module now imports `conftest` before any project module (pytest loads
it automatically; standalone runs import it explicitly). `conftest`:

1. sets `TRADING_TG_SEND=0` by default;
2. sets `DB_PATH` / `TESTS_DB_PATH` to a per-process temp sqlite file
   (`/tmp/trading_agent_tests_<pid>.db`) so all writes land outside production;
3. stubs `agents.llm.llm_review` so eligible LONG/SHORT ticks never call the
   real 9Router/DeepSeek endpoint (hermetic default).

`storage/trading.db` is never opened by tests unless an integration run
explicitly overrides `DB_PATH`.

### Intentional integration runs (opt-in only)

Real Telegram sending or production DB access requires explicit opt-in — never
the default:

```sh
TRADING_TG_SEND=1 python tests/test_ai_telegram.py   # send path (mock httpx for safety)
DB_PATH=storage/trading.db python ...                # only with a stated reason
```

There is intentionally **no** CI/unit path that sends real messages or writes
the production DB.

### Safety defaults

| Concern          | Default              | Opt-in                      |
|------------------|----------------------|-----------------------------|
| Telegram sends   | disabled (`reason=telegram_send_disabled`) | `TRADING_TG_SEND=1` |
| Database         | temp per-process sqlite | override `DB_PATH`    |
| LLM/9Router      | stubbed (`llm_review=None`) | re-stub per test     |
| Binance          | read-only, untouched  | n/a                         |

### Verification

- All test modules pass with no prod-DB writes and no Telegram sends
  (`decisions` count in `storage/trading.db` unchanged by a full test run).
- Production paper runtime (`scripts/paper_runtime.py`) untouched by this patch.

Contaminated rows (TEST/TSTP3/PH2 and the STALE BTC rows from the incident) were
left in `storage/trading.db` per instruction — do not delete without an explicit
request; they are confined to the `decisions`/`candles` tables and identifiable
by symbol `TEST`, `TSTP3`, `PH2` and the 2026-09-03 23:43–23:44 window.
