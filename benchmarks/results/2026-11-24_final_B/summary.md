# Benchmark campaign 2026-11-24T19:56

> final campaign part B (final engine code; preset call caps respected)

Cases spec version: 2026-11-24.2. In-run model: claude-agent/haiku (OpenCode restricted agent, all roles, isolation `isolated`). Evaluator: claude-agent/sonnet (blinded A/B, 2 repeats, order randomised).
Runs: 4. Stopped early: no. Declared per-run limits: ≤ 40 calls (never above a preset's own cap), ≤ 400000 measured tokens (enforced before each request; one reply may overshoot), ≤ 1800 s.

## Per-run results
| case | system | rep | state | kind | stop | calls/cap | tokens (measured) | elapsed s | cost | primary | checks |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gate_budget_fail | council_quick | 1 | COMPLETE | conditional | budget_tokens | 21/24 | 407148 | 628.9 | unavailable | True | {'recommended_avoids': True, 'gate_failed_on_planted_option': True, 'completed': True, 'within_campaign_limits': True} |
| gate_budget_fail | first_pass | 1 | COMPLETE | firm | budget_tokens | 22/40 | 401827 | 567.2 | unavailable | True | {'recommended_avoids': True, 'gate_failed_on_planted_option': True, 'completed': True, 'within_campaign_limits': True} |
| deferral_missing_info | council_quick | 1 | COMPLETE | conditional | budget_tokens | 20/24 | 442271 | 785.1 | unavailable | True | {'kind_acceptable': True, 'completed': True, 'within_campaign_limits': True} |
| deferral_missing_info | first_pass | 1 | COMPLETE | shortlist | stable | 21/40 | 370861 | 533.0 | unavailable | True | {'kind_acceptable': True, 'completed': True, 'within_campaign_limits': True} |

## Aggregate per case × system (n, primary-measure pass rate, usage mean [min–max])
| case | system | n | primary pass | calls | tokens | elapsed s | budget-truncated | leader challenge reached | over campaign limits |
|---|---|---|---|---|---|---|---|---|---|
| gate_budget_fail | council_quick | 1 | 1/1 | 21 | 407148 | 628.9 | 1 | 0 | 0 |
| gate_budget_fail | first_pass | 1 | 1/1 | 22 | 401827 | 567.2 | 1 | 0 | 0 |
| deferral_missing_info | council_quick | 1 | 1/1 | 20 | 442271 | 785.1 | 1 | 0 | 0 |
| deferral_missing_info | first_pass | 1 | 1/1 | 21 | 370861 | 533.0 | 0 | 0 | 0 |


## Reference systems status
- llm-council-main (first-pass workflow): compared via the engine's `first_pass` preset (same lenses, no review/challenge); the original Claude Code agents need nested subagent spawning and were not executed
- council-review-main: deferred under budget: prompt-only Claude Code skill requiring ~12 haiku subagent calls per case driven by hand; not executed
- council-master: blocked by credentials: needs OpenAI-compatible API keys (Gemini/xAI) as environment variables; none present
- LLM-Council-Decide-master: blocked by credentials and dependencies: OPENROUTER_API_KEY and Typst not available
- neuralhats-main: blocked by dependencies: Ollama with gemma4 not installed
- llm-as-a-verifier-main: blocked by dependencies: needs a logprob backend (DeepSeek, Vertex or OpenAI-compatible with logprobs); none configured