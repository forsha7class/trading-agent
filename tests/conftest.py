"""Shared test isolation — import FIRST in every test module (pytest loads it
automatically; standalone `python tests/test_x.py` runs must `import conftest`
before importing any project module).

Guarantees (must run before storage/config/telegram are imported):
  1. TRADING_TG_SEND defaults to "0" -> telegram_notifier refuses to send.
     Real sends require an explicit opt-in (TRADING_TG_SEND=1), never unit/CI.
  2. DB_PATH points at a per-process temp sqlite file -> tests can never touch
     the production storage/trading.db. DB_PATH is honored by config.settings
     (env_map) and by storage.database via get_settings().
"""
import os, sys, tempfile
from pathlib import Path

os.environ.setdefault("TRADING_TG_SEND", "0")

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_TMP = os.environ.get("TESTS_DB_PATH") or os.path.join(
    tempfile.gettempdir(), f"trading_agent_tests_{os.getpid()}.db")
os.environ["TESTS_DB_PATH"] = _TMP
os.environ["DB_PATH"] = _TMP

# Tests must never hit external services: stub the LLM review path so any
# coordinator/engine tick that produces an eligible LONG/SHORT candidate does
# not make a real 9Router/DeepSeek call. Individual tests may re-stub or
# restore (test_ai_telegram does) — the default is hermetic.
try:
    import agents.llm as _llm
    _llm.llm_review = lambda *a, **k: None
except Exception:
    pass
