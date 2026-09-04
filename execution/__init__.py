"""Unified DEMO/Paper execution slice (additive; NO Phase 6).

Files:
  execution/env.py        — TRADING_MODE + environment gate (fail-closed)
  execution/adapters.py   — ExecutionAdapter + PaperExecution/DemoExecution/LiveExecution
  execution/demo_broker.py— Binance Spot Testnet REST client (thin, signed, no secrets logged)
  execution/demo_engine.py— DEMO lifecycle: order -> position -> exit, persistence, Telegram
  portfolio/paper_engine.py  — UNCHANGED (PAPER path)
  agents/telegram_notifier.py — extended with trader-facing lifecycle formats (additive)

Safety invariants (task-mandated):
  - PAPER and DEMO are distinct; DEMO never degrades to PAPER, never routes mainnet.
  - LIVE is interface-only and disabled; any LIVE path returns LIVE_EXECUTION_DISABLED.
  - No real order is placed by importing/running this code; order placement requires an
    explicit smoke-test entrypoint + authorized credentials.
  - Strategy/regime/RiskEngine/AI untouched: frozen RegimeGatedTrend 0.1.0 candidates
    only (execution/eligibility.py), RiskEngine authoritative, AI review-only.
  - Secrets are read from env at runtime only and never printed/logged/persisted.
"""
