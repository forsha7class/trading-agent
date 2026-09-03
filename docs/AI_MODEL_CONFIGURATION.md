# AI MODEL CONFIGURATION — DeepSeek V4 Flash via 9Router

> Scope: this task connects the **existing** bounded AI review agents to 9Router using
> DeepSeek V4 Flash. No new agents were created. No new provider abstraction was added.
> No Phase 6.

## Model
- **Model:** `ts/thirty/deepseek-v4-flash` (DeepSeek V4 Flash) — the ONLY model used.
- **Provider:** 9Router (OpenAI-compatible endpoint).
- **No fallback / routing / second-opinion / voting / multi-model ensemble.** Single,
  simple path: `Existing Agent → 9Router → DeepSeek V4 Flash → AI Contract → Coordinator`.
- Low-token / low-cost priority. DeepSeek V4 Flash is chosen accordingly.

## Existing agents used (NOT created, NOT duplicated, NOT rewritten)
| Role | File | Notes |
|---|---|---|
| Analyst | `agents/analyst.py` | deterministic; provides facts/interpretation |
| Signal Reviewer | `agents/signal_reviewer.py` | deterministic coherence check |
| Risk Reviewer | `agents/risk_reviewer.py` | uses RiskEngine — **never LLM, never overrides** |
| Researcher | `agents/researcher.py` | external-context stub (unchanged) |
| LLM layer | `agents/llm.py` | OpenAI-compatible client → 9Router → DeepSeek |
| Contract | `agents/ai_contract.py` | folds reviews into Phase 5 schema |

## How the agents use DeepSeek (bounded)
`agents/ai_contract.run_review(..., use_llm=True)` invokes `agents.llm.llm_review()`
(a single DeepSeek call per decision) which reviews the quant signal coherence and
returns the bounded schema. The deterministic analyst/signal reviewers still run to
structure evidence. The Risk Reviewer is RiskEngine-based only and is untouched.

Bounding (invariants held):
- AI never changes the final quantitative decision (`DecisionEngine` is authority).
- AI never overrides a hard RiskEngine veto (REJECT stays REJECT).
- AI cannot increase position size, leverage, or risk limits.
- AI cannot create a trade not supported by supplied evidence.
- Provider/LLM unavailable or malformed → AI status **UNAVAILABLE**, never PASS.
- AI output is REVIEW ONLY; execution remains paper/human.

## Configuration variables (referenced at runtime from environment — never committed)
| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | 9Router credential (shared env, ~/.hermes/.env) |
| `OPENAI_BASE_URL` | `http://127.0.0.1:20128/v1` (9Router, local) |
| `LLM_MODEL` | `ts/thirty/deepseek-v4-flash` |

If these are unset, `llm_review` returns `None` → review status `UNAVAILABLE` and the
system continues safely (deterministic, NO_TRADE-safe). This is intentional.

## Token-efficiency approach
- Compact payloads only: symbol, timeframe, regime, direction, ensemble score, p_up/p_down,
  rr, risk_pct, short evidence/counter lists. **No** full candle history, DB rows, logs,
  or whole conversations.
- Truncated prompt (`payload[:6000]`). `temperature=0.2`. `timeout=20`.
- No verbose reasoning requirements in the system prompt.

## 9Router integration notes
- Reused the project's existing HTTP client (`httpx`) and env-var credential mechanism.
- 9Router appends a streaming `data: [DONE]` sentinel after a complete JSON response
  body; `agents/llm.py` parses the body text and ignores the sentinel instead of using
  `response.json()`.
- LLM reply is parsed leniently (code fences / trailing text) and decision tokens are
  normalized (`BUY→LONG`, `SELL→SHORT`, else `NO_TRADE`).

## Security
- Secrets come only from the environment. Never source code, git, logs, or docs.
- Errors are redacted (`agents/telegram_notifier.redact_secret`) before logging.
- No credential is ever printed.
