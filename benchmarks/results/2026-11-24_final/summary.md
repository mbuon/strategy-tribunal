# Benchmark campaign 2026-11-24T21:03

> FINAL consolidated campaign, 2026-11-24 19:15-20:20 CET, 20 runs on the final engine code; all decision records rebuilt afterwards with council rereport (no model calls) after the report.py next-action ordering fix; parts A/B/C ran in parallel; preset call caps respected; the declared 400k token cap was overshot by one reply in 7 of the 8 non-trivial runs (402k-442k measured) and is listed per run; evaluation pass 3 is order-balanced and shows the verdict follows presentation order (inconclusive winner).

Cases spec version: 2026-11-24.2. In-run model: claude-agent/haiku (OpenCode restricted agent, all roles, isolation `isolated`). Evaluator: claude-agent/sonnet (blinded A/B, 2 repeats, order randomised).
Runs: 20. Stopped early: n/a (rescored). Declared per-run limits: ≤ 40 calls (never above a preset's own cap), ≤ 400000 measured tokens (enforced before each request; one reply may overshoot), ≤ 1800 s.

## Per-run results
| case | system | rep | state | kind | stop | calls/cap | tokens (measured) | elapsed s | cost | primary | checks |
|---|---|---|---|---|---|---|---|---|---|---|---|
| open_channel_mix | council_quick | 1 | COMPLETE | conditional | budget_tokens | 18/24 | 411071 | 742.0 | unavailable | None | {'completed': True, 'within_campaign_limits': True} |
| open_channel_mix | first_pass | 1 | COMPLETE | firm | budget_tokens | 15/40 | 403168 | 692.2 | unavailable | None | {'completed': True, 'within_campaign_limits': True} |
| false_premise | council_quick | 1 | COMPLETE | conditional | budget_calls | 24/24 | 438623 | 637.8 | unavailable | True | {'kind_acceptable': True, 'premise_flagged': True, 'completed': True, 'within_campaign_limits': True} |
| false_premise | first_pass | 1 | COMPLETE | firm | budget_tokens | 24/40 | 436973 | 628.3 | unavailable | True | {'kind_acceptable': True, 'premise_flagged': True, 'completed': True, 'within_campaign_limits': True} |
| gate_budget_fail | council_quick | 1 | COMPLETE | conditional | budget_tokens | 21/24 | 407148 | 628.9 | unavailable | True | {'recommended_avoids': True, 'gate_failed_on_planted_option': True, 'completed': True, 'within_campaign_limits': True} |
| gate_budget_fail | first_pass | 1 | COMPLETE | firm | budget_tokens | 22/40 | 401827 | 567.2 | unavailable | True | {'recommended_avoids': True, 'gate_failed_on_planted_option': True, 'completed': True, 'within_campaign_limits': True} |
| deferral_missing_info | council_quick | 1 | COMPLETE | conditional | budget_tokens | 20/24 | 442271 | 785.1 | unavailable | True | {'kind_acceptable': True, 'completed': True, 'within_campaign_limits': True} |
| deferral_missing_info | first_pass | 1 | COMPLETE | shortlist | stable | 21/40 | 370861 | 533.0 | unavailable | True | {'kind_acceptable': True, 'completed': True, 'within_campaign_limits': True} |
| obj_vendor_ev | council_quick | 1 | COMPLETE | shortlist | trivial_question | 7/24 | 107702 | 206.8 | unavailable | True | {'recommended_matches': True, 'kind_acceptable': True, 'completed': True, 'within_campaign_limits': True} |
| obj_vendor_ev | first_pass | 1 | COMPLETE | shortlist | trivial_question | 7/40 | 111046 | 220.8 | unavailable | True | {'recommended_matches': True, 'kind_acceptable': True, 'completed': True, 'within_campaign_limits': True} |
| trivial_overhead | council_quick | 1 | COMPLETE | shortlist | trivial_question | 8/24 | 92948 | 144.1 | unavailable | True | {'stop_reason_acceptable': True, 'within_call_cap': True, 'completed': True, 'within_campaign_limits': True} |
| trivial_overhead | first_pass | 1 | COMPLETE | firm | trivial_question | 6/40 | 73314 | 119.9 | unavailable | True | {'stop_reason_acceptable': True, 'within_call_cap': True, 'completed': True, 'within_campaign_limits': True} |
| obj_vendor_ev | council_quick | 2 | COMPLETE | shortlist | trivial_question | 7/24 | 106778 | 188.6 | unavailable | True | {'recommended_matches': True, 'kind_acceptable': True, 'completed': True, 'within_campaign_limits': True} |
| obj_vendor_ev | first_pass | 2 | COMPLETE | shortlist | trivial_question | 7/40 | 108478 | 202.6 | unavailable | True | {'recommended_matches': True, 'kind_acceptable': True, 'completed': True, 'within_campaign_limits': True} |
| trivial_overhead | council_quick | 2 | COMPLETE | firm | trivial_question | 6/24 | 72623 | 116.1 | unavailable | True | {'stop_reason_acceptable': True, 'within_call_cap': True, 'completed': True, 'within_campaign_limits': True} |
| trivial_overhead | first_pass | 2 | COMPLETE | firm | trivial_question | 7/40 | 86675 | 140.8 | unavailable | True | {'stop_reason_acceptable': True, 'within_call_cap': True, 'completed': True, 'within_campaign_limits': True} |
| obj_vendor_ev | council_quick | 3 | COMPLETE | shortlist | trivial_question | 7/24 | 109949 | 188.0 | unavailable | True | {'recommended_matches': True, 'kind_acceptable': True, 'completed': True, 'within_campaign_limits': True} |
| obj_vendor_ev | first_pass | 3 | COMPLETE | shortlist | stable | 20/40 | 372404 | 525.9 | unavailable | True | {'recommended_matches': True, 'kind_acceptable': True, 'completed': True, 'within_campaign_limits': True} |
| trivial_overhead | council_quick | 3 | COMPLETE | firm | trivial_question | 6/24 | 72180 | 106.8 | unavailable | True | {'stop_reason_acceptable': True, 'within_call_cap': True, 'completed': True, 'within_campaign_limits': True} |
| trivial_overhead | first_pass | 3 | COMPLETE | firm | trivial_question | 6/40 | 77630 | 131.0 | unavailable | True | {'stop_reason_acceptable': True, 'within_call_cap': True, 'completed': True, 'within_campaign_limits': True} |

## Aggregate per case × system (n, primary-measure pass rate, usage mean [min–max])
| case | system | n | primary pass | calls | tokens | elapsed s | budget-truncated | leader challenge reached | over campaign limits |
|---|---|---|---|---|---|---|---|---|---|
| obj_vendor_ev | council_quick | 3 | 3/3 | 7.0 [7–7] | 108143.0 [106778–109949] | 194.5 [188.0–206.8] | 0 | 0 | 0 |
| obj_vendor_ev | first_pass | 3 | 3/3 | 11.3 [7–20] | 197309.3 [108478–372404] | 316.4 [202.6–525.9] | 0 | 0 | 0 |
| gate_budget_fail | council_quick | 1 | 1/1 | 21 | 407148 | 628.9 | 1 | 0 | 0 |
| gate_budget_fail | first_pass | 1 | 1/1 | 22 | 401827 | 567.2 | 1 | 0 | 0 |
| open_channel_mix | council_quick | 1 | rubric | 18 | 411071 | 742.0 | 1 | 0 | 0 |
| open_channel_mix | first_pass | 1 | rubric | 15 | 403168 | 692.2 | 1 | 0 | 0 |
| false_premise | council_quick | 1 | 1/1 | 24 | 438623 | 637.8 | 1 | 1 | 0 |
| false_premise | first_pass | 1 | 1/1 | 24 | 436973 | 628.3 | 1 | 0 | 0 |
| deferral_missing_info | council_quick | 1 | 1/1 | 20 | 442271 | 785.1 | 1 | 0 | 0 |
| deferral_missing_info | first_pass | 1 | 1/1 | 21 | 370861 | 533.0 | 0 | 0 | 0 |
| trivial_overhead | council_quick | 3 | 3/3 | 6.7 [6–8] | 79250.3 [72180–92948] | 122.3 [106.8–144.1] | 0 | 0 | 0 |
| trivial_overhead | first_pass | 3 | 3/3 | 6.3 [6–7] | 79206.3 [73314–86675] | 130.6 [119.9–140.8] | 0 | 0 | 0 |

## Blinded rubric evaluations (open cases) — pass 1
| case | runs rep | pair (order shown) | eval repeat | winner | scores | reason |
|---|---|---|---|---|---|---|
| open_channel_mix | 1 | first_pass vs council_quick | 1 | first_pass | {"council_quick": {"defensibility": 4, "completeness": 5, "actionability": 3}, "first_pass": {"defensibility": 6, "completeness": 7, "actionability": 9}} | Record A gives a concrete staged plan with budgets, a review date, gate and fallback and clear reversal conditions, while Record B's next action is only an internal housekeeping step (merge OPT-6 into OPT-5), it leaves several material objections open, and it is cut off. |
| open_channel_mix | 1 | council_quick vs first_pass | 2 | first_pass | {"council_quick": {"defensibility": 6, "completeness": 6, "actionability": 3}, "first_pass": {"defensibility": 7, "completeness": 8, "actionability": 9}} | B gives a concrete staged plan with a dated review, explicit scale and fallback rules, and reversal conditions, while A's next action is an administrative 'merge OPT-6 into OPT-5' and its record is dominated by unresolved objections. |

Wins/ties/losses (evaluator verdicts): {'first_pass': 2}
- mean rubric council_quick: defensibility 5.0, completeness 5.5, actionability 3.0 (n=2)
- mean rubric first_pass: defensibility 6.5, completeness 7.5, actionability 9.0 (n=2)

## Blinded rubric evaluations (open cases) — pass 2
> Pass 2 after two in-scope corrections found from pass 1: (a) report.py now orders open objections by relevance to the recommended option before picking the next action (pass 1 surfaced a minor duplicate-merge objection on a third option as the next action); (b) the evaluator input no longer hard-cuts at 6000 characters (the council record was cut mid-sentence and penalised as 'cut off'); both open-case runs were rebuilt with `council rereport` (no model calls) and re-evaluated with 3 repeats.
| case | runs rep | pair (order shown) | eval repeat | winner | scores | reason |
|---|---|---|---|---|---|---|
| open_channel_mix | 1 | first_pass vs council_quick | 1 | first_pass | {"council_quick": {"defensibility": 6, "completeness": 8, "actionability": 4}, "first_pass": {"defensibility": 6, "completeness": 6, "actionability": 8}} | A gives a concrete staged budget split with gates and reversal conditions, whereas B's thorough objection coverage ends in an unclear next action (moving a gate date) and an unresolved recommendation. |
| open_channel_mix | 1 | council_quick vs first_pass | 2 | council_quick | {"council_quick": {"defensibility": 8, "completeness": 8, "actionability": 6}, "first_pass": {"defensibility": 6, "completeness": 5, "actionability": 8}} | A is better because it states its low confidence, lists its open objections and says what would reverse it, while B reports a 'firm' outcome and no dissent even though its own gates are unverified and its confidence is low. |
| open_channel_mix | 1 | council_quick vs first_pass | 3 | council_quick | {"council_quick": {"defensibility": 8, "completeness": 8, "actionability": 6}, "first_pass": {"defensibility": 6, "completeness": 5, "actionability": 8}} | A is better because it is honest about low confidence and about open objections (marginal Meta CAC, kill line above target, attribution and incrementality). B's 'firm' outcome with no dissent conflicts with its low confidence and three unverified gates, though B's concrete staged plan is clearer to act on. |

Wins/ties/losses (evaluator verdicts): {'first_pass': 1, 'council_quick': 2}
- mean rubric council_quick: defensibility 7.3, completeness 8.0, actionability 5.3 (n=3)
- mean rubric first_pass: defensibility 6.0, completeness 5.3, actionability 8.0 (n=3)

## Blinded rubric evaluations (open cases) — pass 3
> Pass 3, order-balanced: 3 repeats with council_quick shown first (A) and 3 with first_pass shown first; same rebuilt records as pass 2. Added because every pass-2 verdict went to whichever record was shown first.
| case | runs rep | pair (order shown) | eval repeat | winner | scores | reason |
|---|---|---|---|---|---|---|
| open_channel_mix | 1 | first_pass vs council_quick | 1 | first_pass | {"council_quick": {"defensibility": 6, "completeness": 8, "actionability": 4}, "first_pass": {"defensibility": 6, "completeness": 6, "actionability": 8}} | A gives a concrete staged budget plan with a gate, a review date and a fallback, while B names a 10% test cell but its next action is only to fix a gate date, even though B is more thorough about unknowns and objections. |
| open_channel_mix | 1 | council_quick vs first_pass | 1 | council_quick | {"council_quick": {"defensibility": 7, "completeness": 8, "actionability": 6}, "first_pass": {"defensibility": 6, "completeness": 6, "actionability": 8}} | A is the more honest and complete record: it states low confidence, surfaces the open objections (attribution overlap, margin and LTV, seasonality, kill line above target) and names what would reverse the decision, though its next action is a bit muddled. B gives a cleaner, more concrete staged plan, but it labels the outcome 'firm' with no dissent while its own gates are unverified and its confidence is low. |
| open_channel_mix | 1 | first_pass vs council_quick | 2 | first_pass | {"council_quick": {"defensibility": 6, "completeness": 8, "actionability": 4}, "first_pass": {"defensibility": 6, "completeness": 6, "actionability": 8}} | A gives a concrete, capped, gated plan with budgets, a review date and fallback, while B has richer risk coverage but its next action is an obscure gate-date fix that doesn't tell the user what to do with the budget. |
| open_channel_mix | 1 | council_quick vs first_pass | 2 | council_quick | {"council_quick": {"defensibility": 7, "completeness": 8, "actionability": 6}, "first_pass": {"defensibility": 6, "completeness": 6, "actionability": 8}} | A is more candid about uncertainty, open objections and what would reverse the decision, though its next action is less crisp, while B gives a clearer staged plan but labels itself 'firm' with no dissent and leaves three gates unverified. |
| open_channel_mix | 1 | first_pass vs council_quick | 3 | first_pass | {"council_quick": {"defensibility": 6, "completeness": 8, "actionability": 4}, "first_pass": {"defensibility": 6, "completeness": 6, "actionability": 8}} | A gives a concrete budget split, review timing, and pass/fail gates that can be executed immediately, while B has deeper risk coverage but its next action is an obscure fix to a gate date rather than a clear step for the decision. |
| open_channel_mix | 1 | council_quick vs first_pass | 3 | council_quick | {"council_quick": {"defensibility": 8, "completeness": 8, "actionability": 6}, "first_pass": {"defensibility": 6, "completeness": 5, "actionability": 8}} | A is better because it states its low confidence, lists the open objections and what would reverse the decision, and recommends a smaller 10% test, while B calls its outcome 'firm' and reports no dissent even though three gates are unverified and its own confidence is low, although B's next action is the more concrete. |

Wins/ties/losses (evaluator verdicts): {'first_pass': 3, 'council_quick': 3}
- mean rubric council_quick: defensibility 6.7, completeness 8.0, actionability 5.0 (n=6)
- mean rubric first_pass: defensibility 6.0, completeness 5.8, actionability 8.0 (n=6)


## Reference systems status
- llm-council-main (first-pass workflow): PROXY comparison only: the engine's own `first_pass` preset (frame, policy, baseline, lenses, judge, report; no review, verification or challenge) stands in for the reference; the original Claude Code agents were not run. They are runnable unattended through `claude -p` at roughly US$ 3 per case (new spend, user's decision)
- council-review-main: not run: a prompt-only Claude Code skill; runnable unattended through `claude -p` at roughly US$ 3-4 per case (new spend, user's decision)
- council-master: blocked by credentials: needs OPENAI_API_KEY-style keys for OpenAI-compatible endpoints (Gemini/xAI) in the environment; none present (the OpenAI access on this machine is a ChatGPT-account OAuth held inside OpenCode, not an API key); Google quota depleted (402)
- LLM-Council-Decide-master: blocked by credentials and dependencies: OPENROUTER_API_KEY and Typst not available
- neuralhats-main: live comparison ATTEMPTED on local Ollama (gemma4) with the engine's typo case; outcome, model match and evaluator result recorded in docs/llm_council.md section 16.5
- llm-as-a-verifier-main: blocked by dependencies (possibly unblockable): needs a log-probability backend (DeepSeek, Vertex or OpenAI-compatible with logprobs); none configured; the local Ollama server may expose logprobs but this was not tested