# TELEGRAM NOTIFICATIONS

> Observability channel only. Telegram is **never** part of the decision-control path.
> Adapter: `agents/telegram_notifier.py` (new file). Wire: `agents/coordinator.py`.

## Role
Notifies a human about notable trading decision-support events. It:
- does NOT modify any decision,
- does NOT touch the risk engine or strategy/AI modules,
- does NOT gate or block trading,
- never crashes the quant pipeline (all failures are caught and logged).

Architecture:
```
Existing Coordinator → Decision / AI Review event → Telegram Adapter → Telegram Bot
```

## Configuration (environment, never committed)
| Variable | Purpose |
|---|---|
| `TRADING_TG_BOT_TOKEN` | dedicated trading bot token (preferred) |
| `TRADING_TG_CHAT_ID` | target chat id (preferred) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / `TELEGRAM_HOME_CHANNEL` | fallbacks |

The adapter prefers the dedicated `TRADING_TG_*` vars, then falls back to the generic
Telegram vars. All resolved at runtime via `os.getenv`; nothing is hardcoded, logged, or
committed.

## Events sent (only useful events — no spam on market-data updates)
| Event | Trigger | Icon |
|---|---|---|
| `SIGNAL` | quant decision LONG/SHORT | 🚨 |
| `AI_FLAG` | AI review status FLAG | ⚠️ |
| `AI_REJECT` | AI review status REJECT (non-risk) | ❌ |
| `RISK_REJECT` | quant NO_TRADE due to a risk veto | 🛑 |
| `SYSTEM_ALERT` | operational alert | 🚨 |
| `PAPER_RESULT` | paper trade closed | 📈 |

Routine NO_TRADE (no signal) and internal steps are NOT sent.

## Message formats
Compact single messages with: symbol, decision, regime, probability, entry/stop/TP,
R:R, risk %, AI status, evidence/counter, signal id, timestamp. No guaranteed-profit
wording. Risk-engine vetoes are surfaced as final NO TRADE. Full templates live in
`agents/telegram_notifier.py` (`format_signal`, `format_flag`, `format_reject`,
`format_system`, `format_paper`).

## Deduplication
In-memory map keyed by `{event_type}:{stable_id}` where `stable_id` is the decision_id /
signal_id. Same event within the cooldown window (default 30 s, configurable) is skipped.
A notification that failed is not marked as sent, so a retry on a later decision id can
occur; identical consecutive decisions are suppressed.

## Failure behavior (non-critical)
- Missing credentials → `{"sent": false, "error": "missing telegram credentials"}` — no raise.
- Network / API failure → error returned, logged, swallowed. The decision pipeline is
  unaffected.
- Notification errors never expose the token (`redact_secret`).
- Bounded retry: one attempt per event; cooldown prevents retry storms.

## Security rules
- Token/chat id only from env. Never in code, git, logs, docs, or Telegram content.
- `redact_secret()` scrubs any configured secret from a logged string.

## Tests
`tests/test_ai_telegram.py` covers: missing credentials (non-fatal), message format,
dedup, send failure (non-fatal), secret redaction, unknown event type. All pass without
network or real credentials.
