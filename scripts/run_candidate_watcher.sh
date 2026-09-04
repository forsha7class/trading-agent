#!/bin/bash
# Detached candidate watcher launcher (re-parents to PID 1; survives session end)
set -a
. ~/.hermes/.env
set +a
export TRADING_MODE=DEMO
export TRADING_TG_SEND=1
cd /root/trading-agent
exec /usr/bin/python3.14 -u scripts/demo_candidate_watcher.py --notify >> docs/candidate_watcher.log 2>&1
