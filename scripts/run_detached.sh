#!/bin/bash
# Detached paper runtime launcher (survives Hermes session restart)
set -a
. /root/.hermes/.env
set +a
export TRADING_STOP_UTC=1788559200000
# Notifier send guard: production runtime explicitly opts in to Telegram sends.
# Tests and ad-hoc processes stay disabled unless they set this themselves.
export TRADING_TG_SEND=1
cd /root/trading-agent
exec /usr/local/lib/hermes-agent/venv/bin/python3 -u scripts/paper_runtime.py >> docs/paper_runtime_detached.log 2>&1
