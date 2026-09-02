"""Bounded LLM JSON layer — optional. Never invents market data, never overrides risk. Stub if no key."""
from __future__ import annotations
import os, json, httpx
PROMPT_VERSION="0.1.0"
# Forbid invented facts: prompt forces structured JSON only from provided evidence
SYSTEM_PROMPT="""You are a bounded trading analyst. Rules:
- Available evidence is ONLY what the quantitative system supplies in the user message JSON.
- FORBID invented facts: do not invent prices, indicators, news, or market data.
- Distinguish FACT (from supplied data) from INTERPRETATION.
- Output strict JSON only matching the schema: {"assessment":"VALID|WEAK|INVALID","decision":"LONG|SHORT|NO_TRADE","evidence":[],"counter_evidence":[],"uncertainties":[],"risk_flags":[],"invalidations":[]}
- If evidence insufficient, assessment=INVALID and decision=NO_TRADE.
- Never override hard risk limits supplied.
- On any doubt, prefer NO_TRADE.
"""

def llm_review(payload:dict, model:str|None=None, base_url:str|None=None, api_key:str|None=None)->dict|None:
    """Call OpenAI-compatible LLM if configured, else None (degrade safely)."""
    api_key=api_key or os.getenv("OPENAI_API_KEY") or os.getenv("VOICE_TOOLS_OPENAI_KEY")
    if not api_key: return None
    base_url=base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    model=model or os.getenv("LLM_MODEL") or "gpt-4o-mini"
    try:
        r=httpx.post(f"{base_url.rstrip('/')}/chat/completions", headers={"Authorization":f"Bearer {api_key}"}, json={
            "model":model,"temperature":0.2,"response_format":{"type":"json_object"},
            "messages":[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":json.dumps(payload)[:8000]}],
        }, timeout=15)
        r.raise_for_status()
        txt=r.json()["choices"][0]["message"]["content"]
        data=json.loads(txt)
        # schema validate minimal
        if not isinstance(data,dict) or "assessment" not in data or "decision" not in data:
            return None
        # bounded: decision must be in allowed set
        if data.get("decision") not in ("LONG","SHORT","NO_TRADE"): data["decision"]="NO_TRADE"
        return data
    except Exception:
        return None
