"""Telegram notification adapter — OBSERVABILITY ONLY.

Sends compact, deduplicated notifications for notable trading decision-support
events. It is NOT part of the decision-control path: it never modifies a decision,
never touches the risk engine, and never alters analysis. A Telegram failure is
logged and swallowed (non-fatal) so the quant pipeline is never affected.

Credentials are read at runtime from the environment only (never hardcoded):
  TRADING_TG_BOT_TOKEN / TRADING_TG_CHAT_ID   (dedicated trading bot)
  fallback: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / TELEGRAM_HOME_CHANNEL
Secrets are never printed, logged, or committed.
"""
from __future__ import annotations
import os, time, threading, json
import httpx

EVENT_SIGNAL = "SIGNAL"
EVENT_AI_FLAG = "AI_FLAG"
EVENT_AI_REJECT = "AI_REJECT"
EVENT_RISK_REJECT = "RISK_REJECT"
EVENT_SYSTEM_ALERT = "SYSTEM_ALERT"
EVENT_PAPER_RESULT = "PAPER_RESULT"
# DEMO lifecycle events (task §19/§14) — trader-facing, one per (decision,event)
EVENT_DEMO_SIGNAL = "DEMO_SIGNAL"
EVENT_DEMO_FILLED = "DEMO_FILLED"
EVENT_DEMO_TP1 = "DEMO_TP1"
EVENT_DEMO_TP2 = "DEMO_TP2"
EVENT_DEMO_SL = "DEMO_SL"
EVENT_DEMO_TIME = "DEMO_TIME"
EVENT_DEMO_REJECT = "DEMO_REJECT"

_EVENT_TYPES = (EVENT_SIGNAL, EVENT_AI_FLAG, EVENT_AI_REJECT,
                EVENT_RISK_REJECT, EVENT_SYSTEM_ALERT, EVENT_PAPER_RESULT,
                EVENT_DEMO_SIGNAL, EVENT_DEMO_FILLED, EVENT_DEMO_TP1, EVENT_DEMO_TP2,
                EVENT_DEMO_SL, EVENT_DEMO_TIME, EVENT_DEMO_REJECT)

# in-memory dedup: key -> last-sent monotonic timestamp (bounded)
_lock = threading.Lock()
_last_sent: dict[str, float] = {}
DEFAULT_COOLDOWN_S = 30.0
MAX_MEM = 5000

_API = "https://api.telegram.org/bot"


def _creds():
    """Resolve token+chat from env. Prefer dedicated trading vars, then Hermes generic.

    Sending is DISABLED unless TRADING_TG_SEND=1 (safety default: tests and any
    process without an explicit opt-in can never send a real Telegram message).
    Returns (token, chat) only when sending is enabled AND credentials exist.
    """
    if os.getenv("TRADING_TG_SEND") != "1":
        return None, None
    token = (os.getenv("TRADING_TG_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.getenv("TRADING_TG_CHAT_ID")
            or os.getenv("TELEGRAM_CHAT_ID")
            or os.getenv("TELEGRAM_HOME_CHANNEL") or "").strip()
    return token, chat


def _disabled_result() -> dict:
    return {"sent": False, "deduped": False, "reason": "telegram_send_disabled", "error": None}


def configured() -> bool:
    t, c = _creds()
    return bool(t and c)


def _dedup_key(event_type: str, stable_id: str) -> str:
    return f"{event_type}:{stable_id or ''}"


def _allow_send(event_type: str, stable_id: str, cooldown_s: float) -> bool:
    """Return True if this event may be sent (dedup + cooldown)."""
    if not configured():
        return False
    key = _dedup_key(event_type, stable_id)
    now = time.monotonic()
    with _lock:
        if len(_last_sent) > MAX_MEM:
            _last_sent.clear()
        last = _last_sent.get(key)
        if last is not None and (now - last) < cooldown_s:
            return False
        _last_sent[key] = now
        return True


def _send_text(text: str, token: str, chat_id: str) -> dict:
    """POST to Telegram (plain text, no HTML parse_mode — reasons may contain
    <, >, & which Telegram's HTML parser rejects with HTTP 400); raises on
    failure so caller can log+swallow. Never logs token."""
    if len(text) > 4000:
        text = text[:3990] + "\n…(truncated)"
    r = httpx.post(f"{_API}{token}/sendMessage",
                   json={"chat_id": chat_id, "text": text},
                   timeout=10)
    r.raise_for_status()
    return r.json()


# ---- compact formatters (no profit claims) ----

def _fmt_probability(p_up):
    try:
        return f"{float(p_up)*100:.0f}%"
    except Exception:
        return "n/a"


# ---- trader-facing number/format helpers (presentation only, task §15-§18) --

def _price(x, nd: int = 2) -> str:
    """80943.321234 -> '80,943.32' (thousands separator, 2dp)."""
    try:
        f = float(x)
        s = f"{f:,.{nd}f}"
        return s
    except Exception:
        return "n/a"


def _pct(x, nd: int = 0) -> str:
    """0.70 -> '70%' ; 0.005 -> '0.5%'."""
    try:
        return f"{float(x) * 100:.{nd}f}%"
    except Exception:
        return "n/a"


def _rr_str(rr) -> str:
    """1.500000000000008 -> '1:1.50'."""
    try:
        return f"1:{float(rr):.2f}"
    except Exception:
        return "n/a"


def _signed(v, nd: int = 2) -> str:
    try:
        return f"{float(v):+,.{nd}f}"
    except Exception:
        return "n/a"


def _regime_readable(regime: str | None) -> str:
    m = {"TREND_BULL": "Trend Bullish", "TREND_BEAR": "Trend Bearish",
         "LOW_VOL": "Low Volatility", "HIGH_VOL": "High Volatility",
         "HIGH_VOLATILITY": "High Volatility", "RANGE": "Range",
         "UNCERTAIN": "Uncertain"}
    return m.get((regime or "").upper(), str(regime or "?"))


def _ai_line(status: str | None) -> str:
    s = (status or "UNAVAILABLE").upper()
    m = {"PASS": "\U0001F9E0 AI PASS", "FLAG": "\u26A0\uFE0F AI FLAG",
         "REJECT": "\U0001F6D1 AI REJECT", "UNAVAILABLE": "\u26AA AI UNAVAILABLE"}
    return m.get(s, f"AI {status}")


def _demo_exit_title(ev: dict) -> tuple[str, str]:
    hit = str(ev.get("exit_reason") or "").upper()
    sym = (ev.get("symbol") or "?").upper()
    if hit == "TAKE_PROFIT_1":
        return "\u2705", f"{sym} — TP1 HIT"
    if hit == "TAKE_PROFIT_2":
        return "\U0001F3AF", f"{sym} — TP2 HIT"
    if hit == "STOP_LOSS":
        return "\U0001F6D1", f"{sym} — STOP LOSS"
    if hit == "TIME_EXIT":
        return "\u23F1\uFE0F", f"{sym} — TIME EXIT"
    return "\U0001F4C8", f"{sym} — EXIT"


# ---- trader-facing DEMO formatters ----------------------------------------
def format_demo_filled(ev: dict) -> str:
    sym = (ev.get("symbol") or "?").upper()
    side = str(ev.get("side") or ev.get("decision") or "?").upper()
    tf = ev.get("timeframe") or "1H"
    regime = _regime_readable(ev.get("regime"))
    entry = _price(ev.get("entry"))
    stop = _price(ev.get("stop"))
    tp1 = _price(ev.get("tp1"))
    tp2 = _price(ev.get("tp2"))
    qty = ev.get("quantity")
    qty_s = f"{float(qty):.6f}".rstrip("0").rstrip(".") if qty is not None else "n/a"
    ai = _ai_line(ev.get("ai_status"))
    return (f"\U0001F7E6 {sym} — DEMO {side}\n"
            f"\U0001F4CA {tf} · {regime}\n"
            f"\U0001F4B0 Entry   {entry}\n"
            f"\U0001F6D1 SL      {stop}\n"
            f"\U0001F3AF TP1     {tp1}\n"
            f"\U0001F3AF TP2     {tp2}\n"
            f"{ai}\n"
            f"Order:\n{ev.get('order_id') or '?'}\n"
            f"Status:\nOPEN\n"
            f"Size: {qty_s}\n"
            f"BINANCE DEMO")


def format_demo_exit(ev: dict) -> str:
    icon, title = _demo_exit_title(ev)
    side = str(ev.get("side") or "?").upper()
    entry = _price(ev.get("entry"))
    exit_px = _price(ev.get("exit"))
    pnl = ev.get("pnl")
    rr = ev.get("rr")
    lines = [f"{icon} {title}", side, "", f"Entry: {entry}", f"Exit: {exit_px}"]
    if rr is not None:
        try:
            lines += ["", f"Result:", f"{_signed(float(rr))}R"]
        except Exception:
            pass
    if pnl is not None:
        lines += ["", "PnL:", _signed(pnl)]
    if str(ev.get("exit_reason") or "").upper() == "TIME_EXIT":
        lines += ["", f"Holding:", f"{ev.get('holding_bars')} bars"]
    lines += ["", "Exit:", str(ev.get("exit_reason") or "?"), "", "BINANCE DEMO"]
    return "\n".join(lines)


def format_demo_reject(ev: dict) -> str:
    sym = (ev.get("symbol") or "?").upper()
    reason = ev.get("reason") or ev.get("invalidations") or ""
    if isinstance(reason, list):
        reason = " • ".join(str(x) for x in reason)
    regime = _regime_readable(ev.get("regime"))
    ai = _ai_line(ev.get("ai_status") or "SKIPPED")
    return (f"\U0001F6D1 {sym} — NO TRADE\n"
            f"Reason:\n{reason}\n"
            f"Regime:\n{regime}\n"
            f"{ai}\n"
            f"Status:\nNo order placed.")


def format_signal(ev: dict) -> str:
    s = (ev.get("symbol") or "?").upper()
    d = (ev.get("decision") or ev.get("direction") or "?").upper()
    regime = ev.get("regime") or "?"
    p = _fmt_probability(ev.get("p_up") if d == "LONG" else ev.get("p_down"))
    entry = ev.get("entry"); stop = ev.get("stop"); tp1 = ev.get("tp1"); tp2 = ev.get("tp2")
    rr = ev.get("rr"); risk = ev.get("risk_pct")
    ai = ev.get("ai_status") or "?"
    evid = ev.get("evidence") or []
    cnt = ev.get("counter_evidence") or []
    evid_s = " • ".join(str(x) for x in evid[:4]) or "none"
    cnt_s = " • ".join(str(x) for x in cnt[:2]) or "none"
    risk_s = f"{float(risk)*100:.1f}%" if isinstance(risk, (int, float)) else ("n/a" if risk is None else risk)
    return (f"\U0001F6A8 {s} — {d}\n"
            f"Mode: PAPER / RESEARCH\n"
            f"Regime: {regime}\n"
            f"Probability: {p}\n"
            f"Entry: {entry}\nStop: {stop}\nTP: {tp1} / {tp2}\n"
            f"R:R: {rr}\nRisk: {risk_s}\n"
            f"AI: {ai}\n"
            f"Evidence: {evid_s}\nCounter: {cnt_s}\n"
            f"Decision: MANUAL REVIEW REQUIRED\n"
            f"Signal: {ev.get('signal_id') or ev.get('decision_id') or ''}\n"
            f"Timestamp: {ev.get('ts') or ''}")


def format_flag(ev: dict) -> str:
    s = (ev.get("symbol") or "?").upper()
    d = (ev.get("decision") or ev.get("direction") or "?").upper()
    reason = " • ".join(str(x) for x in (ev.get("reasons") or ev.get("risk_flags") or ["uncertainty"]))
    risk = ev.get("risk_pct")
    risk_s = f"{float(risk)*100:.1f}%" if isinstance(risk, (int, float)) else "n/a"
    return (f"\u26A0\uFE0F {s} — AI REVIEW FLAG\n"
            f"Signal: {d}\nReason: {reason}\nRisk: {risk_s}\n"
            f"Action: MANUAL REVIEW REQUIRED\n"
            f"Signal ID: {ev.get('signal_id') or ev.get('decision_id') or ''}")


def format_reject(ev: dict, kind: str) -> str:
    icon = "\U0001F6D1" if kind == EVENT_RISK_REJECT else "\u274C"
    title = "RISK REJECTED" if kind == EVENT_RISK_REJECT else "AI REJECTED"
    s = (ev.get("symbol") or "?").upper()
    d = (ev.get("decision") or ev.get("direction") or "?").upper()
    reason = ev.get("reason") or ev.get("invalidations") or ""
    if isinstance(reason, list):
        reason = " • ".join(str(x) for x in reason)
    ai = ev.get("ai_status") or "UNAVAILABLE"
    return (f"{icon} {s} — {title}\n"
            f"Signal: {d}\nReason: {reason}\n"
            f"Risk Engine: {ev.get('risk_engine') or ('REJECT' if kind == EVENT_RISK_REJECT else 'n/a')}\n"
            f"AI: {ai}\nFinal: NO TRADE")


def format_system(ev: dict) -> str:
    return (f"\U0001F6A8 SYSTEM ALERT\n"
            f"Source: {ev.get('source') or '?'}\n"
            f"Message: {ev.get('message') or '?'}\n"
            f"Symbol: {ev.get('symbol') or 'n/a'}\n"
            f"Timestamp: {ev.get('ts') or ''}")


def format_paper(ev: dict) -> str:
    s = (ev.get("symbol") or "?").upper()
    d = (ev.get("side") or ev.get("decision") or "?").upper()
    pnl = ev.get("pnl")
    pnl_s = f"{pnl:+.2f}" if isinstance(pnl, (int, float)) else "n/a"
    return (f"\U0001F4C8 {s} — PAPER TRADE RESULT\n"
            f"Side: {d}\nPnL: {pnl_s}\n"
            f"Exit: {ev.get('exit_reason') or '?'}\n"
            f"Signal ID: {ev.get('signal_id') or ev.get('decision_id') or ''}\n"
            f"Timestamp: {ev.get('ts') or ''}")


def _format(event_type: str, ev: dict) -> str:
    if event_type == EVENT_SIGNAL:
        return format_signal(ev)
    if event_type == EVENT_AI_FLAG:
        return format_flag(ev)
    if event_type in (EVENT_AI_REJECT, EVENT_RISK_REJECT):
        return format_reject(ev, event_type)
    if event_type == EVENT_SYSTEM_ALERT:
        return format_system(ev)
    if event_type == EVENT_PAPER_RESULT:
        return format_paper(ev)
    if event_type == EVENT_DEMO_FILLED:
        return format_demo_filled(ev)
    if event_type in (EVENT_DEMO_TP1, EVENT_DEMO_TP2, EVENT_DEMO_SL, EVENT_DEMO_TIME):
        return format_demo_exit(ev)
    if event_type == EVENT_DEMO_REJECT:
        return format_demo_reject(ev)
    if event_type == EVENT_DEMO_SIGNAL:
        return format_signal(ev)
    return "unknown event"


def notify(event_type: str, ev: dict, cooldown_s: float = DEFAULT_COOLDOWN_S) -> dict:
    """Send a notification if allowed. Returns status dict; never raises to caller.

    Result: {"sent": bool, "deduped": bool, "error": str|None}
    """
    if event_type not in _EVENT_TYPES:
        return {"sent": False, "deduped": False, "error": f"unknown event type {event_type}"}
    if not configured():
        return _disabled_result() if os.getenv("TRADING_TG_SEND") != "1" else {
            "sent": False, "deduped": False, "error": "missing telegram credentials"}
    token, chat = _creds()
    stable_id = str(ev.get("decision_id") or ev.get("signal_id") or ev.get("id") or "")
    if not _allow_send(event_type, stable_id, cooldown_s):
        return {"sent": False, "deduped": True, "error": None}
    try:
        text = _format(event_type, ev)
        _send_text(text, token, chat)
        return {"sent": True, "deduped": False, "error": None}
    except Exception as e:
        # never crash the pipeline; never expose the token in the error
        return {"sent": False, "deduped": False,
                "error": f"telegram send failed: {type(e).__name__}"}


def redact_secret(s: str) -> str:
    """Remove any configured secrets from a string before it is logged/shown."""
    token, chat = _creds()
    out = s
    if token:
        out = out.replace(token, "[REDACTED]")
    return out


def alert(source: str, message: str, symbol: str | None = None, **kw) -> dict:
    """Convenience for SYSTEM_ALERT events."""
    return notify(EVENT_SYSTEM_ALERT, {
        "source": source, "message": message, "symbol": symbol,
        "ts": int(time.time()*1000), **kw})
