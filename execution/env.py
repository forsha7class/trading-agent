"""Environment / trading-mode gate — fail-closed separation of PAPER, DEMO, LIVE.

Rules (task §3/§5/§6):
  - Valid values: PAPER, DEMO, LIVE.
  - DEMO requires: mode=DEMO AND demo credentials present AND endpoint confirmed
    testnet (never mainnet). Any failure -> environment not demo-clear.
  - LIVE is never operable: active(LIVE) -> False with LIVE_EXECUTION_DISABLED.
  - Missing/invalid TRADING_MODE -> defaults PAPER for the PAPER path, and DEMO
    execution refuses (never silently falls back DEMO->PAPER or DEMO->LIVE).

This module contains no credentials and performs no network I/O.
"""
from __future__ import annotations
import os

MODE_PAPER = "PAPER"
MODE_DEMO = "DEMO"
MODE_LIVE = "LIVE"
VALID_MODES = (MODE_PAPER, MODE_DEMO, MODE_LIVE)

# Binance Spot Testnet REST base (the ONLY demo endpoint this code may use).
TESTNET_BASE = "https://testnet.binance.vision"
MAINNET_BASE = "https://api.binance.com"

# Env var names (values live in the runtime environment; never committed).
ENV_KEY = "BINANCE_DEMO_API_KEY"
ENV_SECRET = "BINANCE_DEMO_API_SECRET"
ENV_MODE = "TRADING_MODE"


def trading_mode() -> str:
    m = (os.getenv(ENV_MODE) or MODE_PAPER).strip().upper()
    return m if m in VALID_MODES else MODE_PAPER


def _demo_creds() -> tuple[str, str]:
    k = (os.getenv(ENV_KEY) or "").strip()
    s = (os.getenv(ENV_SECRET) or "").strip()
    return k, s


def demo_env_status() -> dict:
    """Deterministic gate used before ANY demo order attempt. Fail-closed."""
    mode = trading_mode()
    key, secret = _demo_creds()
    ok = True
    reasons = []
    if mode != MODE_DEMO:
        ok, reasons = False, [f"TRADING_MODE={mode} != DEMO"]
    if not (key and secret):
        ok = False
        reasons.append("missing demo credentials")
    # Hard-coded testnet base only; a mainnet base can never satisfy this gate.
    base = os.getenv("BINANCE_DEMO_BASE", TESTNET_BASE).strip().rstrip("/")
    if base != TESTNET_BASE:
        ok = False
        reasons.append(f"endpoint {base} is not the confirmed testnet base")
    if "api.binance.com" in base and base != TESTNET_BASE:
        ok = False
        reasons.append("mainnet endpoint refused")
    return {
        "mode": mode,
        "demo_ready": ok and mode == MODE_DEMO,
        "endpoint": base,
        "endpoint_is_testnet": base == TESTNET_BASE,
        "creds_present": bool(key and secret),
        "reasons": reasons,
        "locked": not ok,
    }


def execution_mode() -> str:
    """Authoritative mode for the execution layer.

    LIVE is never operable here -> LIVE_EXECUTION_DISABLED is surfaced by the
    adapter layer. DEMO requires a clean environment gate, else the caller must
    refuse (fail-closed); this function only reports the intended mode.
    """
    return trading_mode()


def demo_enabled() -> bool:
    return demo_env_status()["demo_ready"]


def require_demo_env() -> None:
    """Raise RuntimeError unless the demo environment gate is fully green."""
    st = demo_env_status()
    if not st["demo_ready"]:
        raise RuntimeError("DEMO environment not ready: " + "; ".join(st["reasons"] or ["unknown"]))
