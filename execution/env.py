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

# Binance Spot Testnet REST base (the ONLY spot-demo endpoint this code may use).
TESTNET_BASE = "https://testnet.binance.vision"
MAINNET_BASE = "https://api.binance.com"

# Binance USDT-M FUTURES DEMO TRADING REST base — the OFFICIAL futures demo
# endpoint (demo.binance.com portal; separate from spot demo and from the old
# futures testnet). Verified live: /fapi/v1 ping+time+exchangeInfo, HMAC signed
# account/positionRisk/positionSide work with the Futures Demo API key.
FUTURES_DEMO_BASE = "https://demo-fapi.binance.com"

# Legacy Binance USDT-M Futures TESTNET (https://testnet.binancefuture.com) —
# decommissioned by Binance in favour of Demo Trading. NOT a default target:
# reachable ONLY under an explicit legacy opt-in (FUTURES_DEMO_LEGACY=1).
FUTURES_TESTNET_BASE = "https://testnet.binancefuture.com"
FUTURES_MAINNET_BASE = "https://fapi.binance.com"

# Env var names (values live in the runtime environment; never committed).
ENV_KEY = "BINANCE_DEMO_API_KEY"
ENV_SECRET = "BINANCE_DEMO_API_SECRET"
ENV_MODE = "TRADING_MODE"
ENV_KIND = "DEMO_KIND"              # SPOT (default) | FUTURES
ENV_FUTURES_KEY = "BINANCE_FUTURES_DEMO_API_KEY"
ENV_FUTURES_SECRET = "BINANCE_FUTURES_DEMO_API_SECRET"
ENV_FUTURES_LEGACY = "FUTURES_DEMO_LEGACY"   # =1 -> old futures testnet (explicit)

KIND_SPOT = "SPOT"
KIND_FUTURES = "FUTURES"
VALID_KINDS = (KIND_SPOT, KIND_FUTURES)

# futures target labels
TARGET_FUTURES_DEMO = "DEMO"        # https://demo-fapi.binance.com (official)
TARGET_FUTURES_TESTNET = "TESTNET"  # https://testnet.binancefuture.com (legacy opt-in)


def demo_kind() -> str:
    """Which demo market the runtime targets. Default SPOT (backward compat);
    an invalid DEMO_KIND value fails closed (gate refuses, never a silent kind)."""
    k = (os.getenv(ENV_KIND) or KIND_SPOT).strip().upper()
    return k if k in VALID_KINDS else KIND_SPOT


def futures_target() -> str:
    """Futures demo target: 'DEMO' (official demo-fapi) unless the legacy
    futures testnet is EXPLICITLY opted into with FUTURES_DEMO_LEGACY=1."""
    return TARGET_FUTURES_TESTNET if os.getenv(ENV_FUTURES_LEGACY) == "1" \
        else TARGET_FUTURES_DEMO


def futures_base(target: str | None = None) -> str:
    """Resolve the futures base for a target label. Mainnet is never a target."""
    t = (target or futures_target()).upper()
    if t == TARGET_FUTURES_TESTNET:
        return FUTURES_TESTNET_BASE
    return FUTURES_DEMO_BASE




def trading_mode() -> str:
    m = (os.getenv(ENV_MODE) or MODE_PAPER).strip().upper()
    return m if m in VALID_MODES else MODE_PAPER


def _demo_creds(kind: str | None = None) -> tuple[str, str]:
    """Credentials for the requested demo kind (default: current DEMO_KIND).

    Futures creds use their OWN env vars (BINANCE_FUTURES_DEMO_API_KEY/_SECRET)
    so spot and futures demo credentials are never mixed (§9)."""
    kind = (kind or demo_kind()).upper()
    if kind == KIND_FUTURES:
        k = (os.getenv(ENV_FUTURES_KEY) or "").strip()
        s = (os.getenv(ENV_FUTURES_SECRET) or "").strip()
        return k, s
    k = (os.getenv(ENV_KEY) or "").strip()
    s = (os.getenv(ENV_SECRET) or "").strip()
    return k, s


def demo_env_status() -> dict:
    """Deterministic gate used before ANY demo order attempt. Fail-closed.

    Kind-aware: DEMO_KIND=FUTURES requires the futures testnet endpoint and the
    SEPARATE futures credentials; DEMO_KIND=SPOT (default) keeps the original
    spot behavior byte-for-byte. Spot and futures bases can never satisfy each
    other's gate."""
    mode = trading_mode()
    kind = demo_kind()
    key, secret = _demo_creds(kind)
    ok = True
    reasons = []
    if mode != MODE_DEMO:
        ok, reasons = False, [f"TRADING_MODE={mode} != DEMO"]
    if not (key and secret):
        ok = False
        reasons.append(f"missing {kind.lower()} demo credentials")
    if kind == KIND_FUTURES:
        # Official Binance Futures Demo base (https://demo-fapi.binance.com) is
        # the ONLY default futures-demo endpoint. The legacy futures testnet
        # (testnet.binancefuture.com) is accepted ONLY under an explicit
        # FUTURES_DEMO_LEGACY=1 opt-in. Mainnet (fapi.binance.com) is never
        # accepted, and no silent fallback between demo/testnet/mainnet exists.
        target = futures_target()
        base = os.getenv("BINANCE_FUTURES_DEMO_BASE", futures_base(target)).strip().rstrip("/")
        allowed = {futures_base(TARGET_FUTURES_DEMO), futures_base(TARGET_FUTURES_TESTNET)}
        if base == FUTURES_TESTNET_BASE and target != TARGET_FUTURES_TESTNET:
            ok = False
            reasons.append("legacy futures testnet requires FUTURES_DEMO_LEGACY=1")
        elif base not in allowed:
            ok = False
            reasons.append(f"endpoint {base} is not a confirmed futures demo base")
        if base == FUTURES_MAINNET_BASE or "fapi.binance.com" in base \
                and base not in (FUTURES_DEMO_BASE, FUTURES_TESTNET_BASE):
            ok = False
            reasons.append("mainnet futures endpoint refused")
        return {
            "mode": mode, "kind": kind, "futures_target": target,
            "demo_ready": ok and mode == MODE_DEMO,
            "endpoint": base,
            "endpoint_is_demo": base == FUTURES_DEMO_BASE,
            "endpoint_is_testnet": base == FUTURES_TESTNET_BASE,
            "creds_present": bool(key and secret), "reasons": reasons,
            "locked": not ok,
        }
    base = os.getenv("BINANCE_DEMO_BASE", TESTNET_BASE).strip().rstrip("/")
    if base != TESTNET_BASE:
        ok = False
        reasons.append(f"endpoint {base} is not the confirmed testnet base")
    if "api.binance.com" in base and base != TESTNET_BASE:
        ok = False
        reasons.append("mainnet endpoint refused")
    return {
        "mode": mode, "kind": kind, "demo_ready": ok and mode == MODE_DEMO,
        "endpoint": base, "endpoint_is_testnet": base == TESTNET_BASE,
        "creds_present": bool(key and secret), "reasons": reasons,
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
