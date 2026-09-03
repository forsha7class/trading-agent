"""Bounded LLM JSON layer — optional. Never invents market data, never overrides risk. Stub if no key."""
from __future__ import annotations
import os, json, httpx
PROMPT_VERSION="0.1.0"
# Forbid invented facts: prompt forces structured JSON only from provided evidence
SYSTEM_PROMPT="""You are a bounded trading analyst+signal reviewer for a decision-support system. Rules:
- Available evidence is ONLY what the quantitative system supplies in the user message JSON.
- FORBID inventing prices, indicators, news, or market data not in the supplied evidence.
- Output STRICT JSON ONLY matching EXACTLY this schema (no prose, no markdown):
{"assessment":"VALID|WEAK|INVALID","decision":"LONG|SHORT|NO_TRADE","evidence":[],"counter_evidence":[],"uncertainties":[],"risk_flags":[],"invalidations":[]}
- decision must be one of: LONG, SHORT, NO_TRADE. NEVER invent a signal not supported by supplied evidence.
- If evidence is insufficient or ambiguous, use assessment=WEAK, decision=NO_TRADE.
- Never override or comment on hard risk limits supplied. Risk is decided elsewhere; you only review signal coherence.
- Reply with the JSON object only."""

def _normalize_decision(d: str | None) -> str:
    """Map LLM decision tokens to the bounded LONG/SHORT/NO_TRADE set."""
    if not d:
        return "NO_TRADE"
    m = str(d).strip().upper()
    if m in ("LONG", "BUY", "GO_LONG", "BULLISH", "L"):
        return "LONG"
    if m in ("SHORT", "SELL", "GO_SHORT", "BEARISH", "S"):
        return "SHORT"
    return "NO_TRADE"

def _parse_llm_json(txt: str) -> dict | None:
    """Lenient JSON extraction from an LLM reply (handles fences/trailing)."""
    if not txt:
        return None
    s = txt.strip()
    # strip markdown fences if present
    if s.startswith("```"):
        s = s.split("```", 2)[1] if "```" in s[s.find("```")+3:] else s
        # keep content after first fence
        parts = s.split("\n", 1)
        s = parts[1] if len(parts) > 1 else parts[0]
    # locate first { ... last }
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b != -1 and b > a:
        s = s[a:b+1]
    try:
        data = json.loads(s)
        return data if isinstance(data, dict) else None
    except Exception:
        return None

def llm_review(payload:dict, model:str|None=None, base_url:str|None=None, api_key:str|None=None)->dict|None:
    """Call OpenAI-compatible LLM if configured, else None (degrade safely)."""
    api_key=api_key or os.getenv("OPENAI_API_KEY") or os.getenv("VOICE_TOOLS_OPENAI_KEY")
    if not api_key: return None
    base_url=base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    model=model or os.getenv("LLM_MODEL") or "gpt-4o-mini"
    try:
        r=httpx.post(f"{base_url.rstrip('/')}/chat/completions", headers={"Authorization":f"Bearer {api_key}"}, json={
            "model":model,"temperature":0.2,
            "messages":[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":json.dumps(payload)[:6000]}],
        }, timeout=20)
        r.raise_for_status()
        # 9Router appends a streaming `data: [DONE]` sentinel to an otherwise
        # complete JSON body; parse the text directly and ignore the sentinel
        # instead of relying on response.json() (which would raise Extra data).
        _body = r.text or ""
        _m = _body.find("data:")
        if _m != -1:
            _body = _body[:_m]
        try:
            _resp = json.loads(_body)
        except Exception:
            return None
        _choices = (_resp or {}).get("choices") or []
        if not _choices:
            return None
        txt = (_choices[0].get("message") or {}).get("content") or ""
        data=_parse_llm_json(txt)
        # schema validate minimal
        if not isinstance(data,dict) or "assessment" not in data or "decision" not in data:
            return None
        # bounded: decision must be in allowed set; never allow AI to force a signal
        data["decision"]=_normalize_decision(data.get("decision"))
        for key in ("evidence","counter_evidence","uncertainties","risk_flags","invalidations"):
            if not isinstance(data.get(key),list):
                data[key]=[]
        # assessment must be one of VALID/WEAK/INVALID (default WEAK-safe)
        if str(data.get("assessment","")).upper() not in ("VALID","WEAK","INVALID"):
            data["assessment"]="WEAK"
        return data
    except Exception:
        return None
