# PHASE 5 — LIMITED AI REVIEW LAYER

> Date: 2026-09-03. Phase 5 PRD Task 9-16.
> Status: **REVIEW-ONLY** (AI_STATUS). AI is decision-support; never authority.

## What was implemented (adapter, not a refactor)
New file `agents/ai_contract.py` — a bounded adapter that runs the existing review
agents (analyst, signal reviewer, risk reviewer) and optionally the LLM reviewer, then
folds their output into the Phase-5 contract schema. Wired into `agents/coordinator.py`
**after** the authoritative quantitative decision; the review record is appended to the
audit trail via `system_events`. No passing module was rewritten; the decision engine
and risk engine are untouched.

## AI roles (from PRD, all bounded)
| Role | File | Bounded to |
|---|---|---|
| Analyst | `agents/analyst.py` | separates FACT from INTERPRETATION; no invented data |
| Signal Reviewer | `agents/signal_reviewer.py` | internal coherence → PASS/FLAG/REJECT |
| Risk Reviewer | `agents/risk_reviewer.py` | advisory on sizing/RR; cannot raise limits |
| Researcher | `agents/researcher.py` | external context as evidence (stub, no feed) |
| Coordinator | `agents/ai_contract.py` | folds reviews; never changes quant decision |
| LLM | `agents/llm.py` | optional; absent key → UNAVAILABLE |

## Output contract (PRD Task 16) — produced by `run_review`
```json
{
  "status": "PASS|FLAG|REJECT|UNAVAILABLE",
  "assessment": "...",
  "evidence": [],
  "counter_evidence": [],
  "risk_flags": [],
  "uncertainties": [],
  "invalidations": [],
  "human_review_required": true,
  "contract_version": "0.1.0",
  "role": "ai_contract"
}
```

## Bounding guarantees (verified)
1. **Never changes the final decision.** `dec` comes from `DecisionEngine`; review is
   advisory and logged only.
2. **Risk veto always authoritative.** If the quantitative decision is NO_TRADE (e.g.
   a risk veto), the review reports REJECT — it cannot convert a veto into approval.
3. **AI cannot raise** risk/trade, leverage, max exposure, or daily loss limit.
4. **Missing AI / LLM is not approval.** No key or call failure → status
   `UNAVAILABLE`, `human_review_required=true`; it never silently passes.
5. **No real order execution.** Review output is a record; execution remains paper.

## Evidence it is wired and working
A live coordinator run produced `NO_TRADE: RR_INSUFFICIENT`, and the audit trail logged
`AI review status=REJECT` (correctly reflecting that the quant decision was no-trade).
All test suites (`test_all`, phase 2/3/4, leakage, risk) still PASS after wiring.

## AI_STATUS for PRD closure
**AI: REVIEW_ONLY** — the AI layer is present, bounded, audited, and advisory. It does
not generate primary signals, does not hold risk or execution authority, and cannot
self-modify the strategy.
