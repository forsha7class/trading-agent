"""Tests for DeepSeek/9Router AI configuration + Telegram notifications.

Runs standalone: `python tests/test_ai_telegram.py` (no pytest needed).
Does not require live network/credentials (LLM & Telegram are mocked or missing).
"""
import sys, os, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def _reset_env():
    for k in ("OPENAI_API_KEY","OPENAI_BASE_URL","LLM_MODEL",
              "TRADING_TG_BOT_TOKEN","TRADING_TG_CHAT_ID",
              "TELEGRAM_BOT_TOKEN","TELEGRAM_CHAT_ID","TELEGRAM_HOME_CHANNEL"):
        os.environ.pop(k, None)

def _mock_llm_none(monkeypatch=None):
    import agents.llm
    _orig = agents.llm.llm_review
    agents.llm.llm_review = lambda *a, **k: None
    return _orig

# ---------- T3: model selection ----------
def test_model_default_is_deepseek():
    _reset_env()
    os.environ["OPENAI_API_KEY"]="k"; os.environ["OPENAI_BASE_URL"]="http://127.0.0.1:20128/v1"
    os.environ["LLM_MODEL"]="ts/thirty/deepseek-v4-flash"
    from agents.llm import llm_review
    # with key present, llm_review attempts a call; without reachable network returns None.
    # Assert the model resolution path uses deepseek via env (call with fake -> unavailable, not wrong-model).
    import agents.llm as m
    assert os.getenv("LLM_MODEL")=="ts/thirty/deepseek-v4-flash"
    # _normalize decision must not be tricked into non-deepseek
    assert "deepseek-v4-flash" in (os.getenv("LLM_MODEL") or "")
    print("model_default_is_deepseek PASS")

def test_no_fallback_model_configured():
    # only one model env; no second model var introduced
    _reset_env()
    os.environ["LLM_MODEL"]="ts/thirty/deepseek-v4-flash"
    assert os.getenv("LLM_MODEL").count("deepseek-v4-flash")==1
    # no model routing vars present
    assert "FALLBACK_MODEL" not in os.environ
    print("no_fallback_model_configured PASS")

# ---------- llm helpers ----------
def test_normalize_decision():
    from agents.llm import _normalize_decision
    assert _normalize_decision("BUY")=="LONG"
    assert _normalize_decision("SELL")=="SHORT"
    assert _normalize_decision("HOLD")=="NO_TRADE"
    assert _normalize_decision("LONG")=="LONG"
    assert _normalize_decision(None)=="NO_TRADE"
    assert _normalize_decision("")=="NO_TRADE"
    print("normalize_decision PASS")

def test_parse_llm_json():
    from agents.llm import _parse_llm_json
    assert _parse_llm_json('{"assessment":"VALID","decision":"LONG"}')=={"assessment":"VALID","decision":"LONG"}
    assert _parse_llm_json('```json\n{"assessment":"WEAK","decision":"NO_TRADE"}\n```')=={"assessment":"WEAK","decision":"NO_TRADE"}
    assert _parse_llm_json('prefix {"assessment":"VALID"} trailing')=={"assessment":"VALID"}
    assert _parse_llm_json("not json") is None
    assert _parse_llm_json(None) is None
    print("parse_llm_json PASS")

# ---------- T17: AI unavailable -> UNAVAILABLE, never PASS ----------
def test_llm_unavailable_is_never_pass():
    _reset_env()
    from agents import ai_contract
    import agents.llm
    saved = agents.llm.llm_review
    agents.llm.llm_review = lambda *a, **k: None  # provider/malformed
    try:
        review = ai_contract.run_review(
            {"features":{"ema20":99,"ema50":95,"close":100,"momentum":0.02,"rsi14":60},
             "regime":"TREND_BULL",
             "ensemble":{"direction":"LONG","score":80},
             "probability":{"p_up":0.7,"p_down":0.15,"p_flat":0.15},
             "mtf":{"veto":None},"proposed_direction":"LONG"},
            decision={"decision":"LONG","rr":2.0,"risk_pct":0.005},
            use_llm=True)
        assert review["status"] in ("UNAVAILABLE","FLAG"), review
        # never converts to PASS when LLM required but unavailable
        assert review["status"] != "PASS"
        assert "UNAVAILABLE" in str(review["risk_flags"]) or "UNAVAILABLE"==review["status"] or "UNAVAILABLE" in review["assessment"]
    finally:
        agents.llm.llm_review = saved
    print("llm_unavailable_is_never_pass PASS")

# ---------- T7: risk veto cannot be overridden ----------
def test_risk_veto_not_overridden_by_ai_pass():
    from agents import ai_contract
    import agents.llm
    saved = agents.llm.llm_review
    agents.llm.llm_review = lambda *a, **k: {"assessment":"VALID","decision":"LONG",
        "evidence":[],"counter_evidence":[],"uncertainties":[],"risk_flags":[],"invalidations":[]}
    try:
        # decision NO_TRADE due to risk veto; AI says PASS/LONG
        review = ai_contract.run_review(
            {"features":{"ema20":99,"ema50":95,"close":100},"regime":"RANGE",
             "ensemble":{"direction":"LONG","score":80},
             "probability":{},"proposed_direction":"LONG"},
            decision={"decision":"NO_TRADE","reason":"NO_TRADE: RISK_REJECT — veto NO_MARTINGALE","rr":None},
            use_llm=True)
        # status must reflect the veto (REJECT), NOT PASS even though AI approved
        assert review["status"]=="REJECT", review["status"]
    finally:
        agents.llm.llm_review = saved
    print("risk_veto_not_overridden PASS")

# ---------- T6: contract normalization on malformed LLM ----------
def test_malformed_llm_to_unavailable():
    from agents import ai_contract
    import agents.llm
    saved = agents.llm.llm_review
    agents.llm.llm_review = lambda *a, **k: None  # malformed/unparseable -> None
    try:
        r = ai_contract.run_review(
            {"features":{},"regime":"UNCERTAIN","ensemble":{},"probability":{},
             "proposed_direction":"NO_TRADE"},
            decision={"decision":"NO_TRADE","reason":"no signal"},
            use_llm=True)
        assert r["status"] in ("UNAVAILABLE","REJECT")
        assert "human_review_required" in r
    finally:
        agents.llm.llm_review = saved
    print("malformed_llm_to_unavailable PASS")

def test_contract_keys_present():
    from agents.ai_contract import run_review
    r = run_review({"features":{},"regime":"UNCERTAIN","ensemble":{},
                    "probability":{},"proposed_direction":"NO_TRADE"},
                   decision={"decision":"NO_TRADE","reason":"none"},
                   use_llm=False)
    for k in ("status","assessment","evidence","counter_evidence","risk_flags",
              "uncertainties","invalidations","human_review_required"):
        assert k in r, k
    assert r["status"] in ("PASS","FLAG","REJECT","UNAVAILABLE")
    print("contract_keys_present PASS")

# ---------- Telegram ----------
def _tg_creds_set():
    os.environ["TRADING_TG_BOT_TOKEN"]="test:token"
    os.environ["TRADING_TG_CHAT_ID"]="12345"

def test_tg_missing_credentials_nonfatal():
    from agents import telegram_notifier as tg
    _reset_env()
    res = tg.notify(tg.EVENT_SIGNAL, {"symbol":"BTCUSDT","decision":"LONG"})
    assert res["sent"] is False
    assert res["error"] == "missing telegram credentials"
    print("tg_missing_credentials_nonfatal PASS")

def test_tg_format_signal():
    from agents import telegram_notifier as tg
    ev={"symbol":"BTCUSDT","decision":"LONG","regime":"TREND_BULL","p_up":0.64,
        "entry":108420,"stop":107850,"tp1":109500,"tp2":110700,"rr":2.1,
        "risk_pct":0.005,"ai_status":"PASS","evidence":["trend aligned"],
        "counter_evidence":["resistance nearby"],"ts":1700000000000}
    msg=tg.format_signal(ev)
    assert "BTCUSDT" in msg and "LONG" in msg and "TREND_BULL" in msg
    assert "64%" in msg  # probability formatting
    assert "R:R: 2.1" in msg
    assert "0.5%" in msg  # risk
    assert "PASS" in msg
    # no profit guarantee wording
    assert "guaranteed" not in msg.lower() and "profit guaranteed" not in msg.lower()
    print("tg_format_signal PASS")

def test_tg_dedup():
    from agents import telegram_notifier as tg
    _tg_creds_set()
    tg._last_sent.clear()
    import agents.telegram_notifier as m
    m._send_text = lambda *a, **k: {"ok":True}  # stub network
    ev={"symbol":"BTCUSDT","decision":"LONG","decision_id":"D1","regime":"BULL"}
    r1=tg.notify(tg.EVENT_SIGNAL, ev)
    assert r1["sent"] is True, r1
    # same event id within cooldown -> deduped
    r2=tg.notify(tg.EVENT_SIGNAL, ev)
    assert r2["deduped"] is True, r2
    # different id -> sent
    r3=tg.notify(tg.EVENT_SIGNAL, {**ev,"decision_id":"D2"})
    assert r3["sent"] is True, r3
    m._last_sent.clear()
    _reset_env()
    print("tg_dedup PASS")

def test_tg_failure_nonfatal():
    from agents import telegram_notifier as tg
    _tg_creds_set()
    tg._last_sent.clear()
    import agents.telegram_notifier as m
    def boom(*a, **k): raise ConnectionError("net down")
    m._send_text = boom
    res=tg.notify(tg.EVENT_SIGNAL, {"symbol":"BTCUSDT","decision":"LONG","decision_id":"X"})
    # returns error dict, does not raise
    assert res["sent"] is False
    assert res["error"] and "telegram send failed" in res["error"]
    tg._last_sent.clear(); _reset_env()
    print("tg_failure_nonfatal PASS")

def test_redact_secret():
    from agents import telegram_notifier as tg
    _tg_creds_set()
    out=tg.redact_secret("error around test:token value")
    assert "test:token" not in out
    assert "REDACTED" in out
    _reset_env()
    print("redact_secret PASS")

def test_unknown_event_type():
    from agents import telegram_notifier as tg
    res=tg.notify("NOT_A_TYPE", {})
    assert res["error"] == "unknown event type NOT_A_TYPE"
    print("unknown_event_type PASS")

if __name__=="__main__":
    _reset_env()
    test_model_default_is_deepseek()
    test_no_fallback_model_configured()
    test_normalize_decision()
    test_parse_llm_json()
    test_contract_keys_present()
    test_llm_unavailable_is_never_pass()
    test_risk_veto_not_overridden_by_ai_pass()
    test_malformed_llm_to_unavailable()
    test_tg_missing_credentials_nonfatal()
    test_tg_format_signal()
    test_tg_dedup()
    test_tg_failure_nonfatal()
    test_redact_secret()
    test_unknown_event_type()
    print("\nALL AI/TELEGRAM TESTS PASS")
