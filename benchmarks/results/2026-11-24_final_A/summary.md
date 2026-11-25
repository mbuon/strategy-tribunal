# Benchmark campaign 2026-11-24T20:00

> final campaign part A (final engine code; preset call caps respected)

Cases spec version: 2026-11-24.2. In-run model: claude-agent/haiku (OpenCode restricted agent, all roles, isolation `isolated`). Evaluator: claude-agent/sonnet (blinded A/B, 2 repeats, order randomised).
Runs: 4. Stopped early: no. Declared per-run limits: ≤ 40 calls (never above a preset's own cap), ≤ 400000 measured tokens (enforced before each request; one reply may overshoot), ≤ 1800 s.

## Per-run results
| case | system | rep | state | kind | stop | calls/cap | tokens (measured) | elapsed s | cost | primary | checks |
|---|---|---|---|---|---|---|---|---|---|---|---|
| open_channel_mix | council_quick | 1 | COMPLETE | conditional | budget_tokens | 18/24 | 411071 | 742.0 | unavailable | None | {'completed': True, 'within_campaign_limits': True} |
| open_channel_mix | first_pass | 1 | COMPLETE | firm | budget_tokens | 15/40 | 403168 | 692.2 | unavailable | None | {'completed': True, 'within_campaign_limits': True} |
| false_premise | council_quick | 1 | COMPLETE | conditional | budget_calls | 24/24 | 438623 | 637.8 | unavailable | True | {'kind_acceptable': True, 'premise_flagged': True, 'completed': True, 'within_campaign_limits': True} |
| false_premise | first_pass | 1 | COMPLETE | firm | budget_tokens | 24/40 | 436973 | 628.3 | unavailable | True | {'kind_acceptable': True, 'premise_flagged': True, 'completed': True, 'within_campaign_limits': True} |

## Aggregate per case × system (n, primary-measure pass rate, usage mean [min–max])
| case | system | n | primary pass | calls | tokens | elapsed s | budget-truncated | leader challenge reached | over campaign limits |
|---|---|---|---|---|---|---|---|---|---|
| open_channel_mix | council_quick | 1 | rubric | 18 | 411071 | 742.0 | 1 | 0 | 0 |
| open_channel_mix | first_pass | 1 | rubric | 15 | 403168 | 692.2 | 1 | 0 | 0 |
| false_premise | council_quick | 1 | 1/1 | 24 | 438623 | 637.8 | 1 | 1 | 0 |
| false_premise | first_pass | 1 | 1/1 | 24 | 436973 | 628.3 | 1 | 0 | 0 |

## Blinded rubric evaluations (open cases)
| case | runs rep | pair (order shown) | eval repeat | winner | scores | reason |
|---|---|---|---|---|---|---|
| open_channel_mix | 1 | first_pass vs council_quick | 1 | first_pass | {"council_quick": {"defensibility": 4, "completeness": 5, "actionability": 3}, "first_pass": {"defensibility": 6, "completeness": 7, "actionability": 9}} | Record A gives a concrete staged plan with budgets, a review date, gate and fallback and clear reversal conditions, while Record B's next action is only an internal housekeeping step (merge OPT-6 into OPT-5), it leaves several material objections open, and it is cut off. |
| open_channel_mix | 1 | council_quick vs first_pass | 2 | first_pass | {"council_quick": {"defensibility": 6, "completeness": 6, "actionability": 3}, "first_pass": {"defensibility": 7, "completeness": 8, "actionability": 9}} | B gives a concrete staged plan with a dated review, explicit scale and fallback rules, and reversal conditions, while A's next action is an administrative 'merge OPT-6 into OPT-5' and its record is dominated by unresolved objections. |

Wins/ties/losses (evaluator verdicts): {'first_pass': 2}
- mean rubric council_quick: defensibility 5.0, completeness 5.5, actionability 3.0 (n=2)
- mean rubric first_pass: defensibility 6.5, completeness 7.5, actionability 9.0 (n=2)

## Reference systems status
- llm-council-main (first-pass workflow): compared via the engine's `first_pass` preset (same lenses, no review/challenge); the original Claude Code agents need nested subagent spawning and were not executed
- council-review-main: deferred under budget: prompt-only Claude Code skill requiring ~12 haiku subagent calls per case driven by hand; not executed
- council-master: blocked by credentials: needs OpenAI-compatible API keys (Gemini/xAI) as environment variables; none present
- LLM-Council-Decide-master: blocked by credentials and dependencies: OPENROUTER_API_KEY and Typst not available
- neuralhats-main: blocked by dependencies: Ollama with gemma4 not installed
- llm-as-a-verifier-main: blocked by dependencies: needs a logprob backend (DeepSeek, Vertex or OpenAI-compatible with logprobs); none configured