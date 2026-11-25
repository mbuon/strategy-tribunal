# Benchmark campaign 2026-11-24T21:03

> SUPERSEDED (history only): partial rerun 18:15–18:34 on the final engine code but with the call cap override raising the quick preset to 40; consolidated final campaign is 2026-11-24_final.

Cases spec version: 2026-11-24.2. In-run model: claude-agent/haiku (OpenCode restricted agent, all roles, isolation `isolated`). Evaluator: claude-agent/sonnet (blinded A/B, 2 repeats, order randomised).
Runs: 2. Stopped early: n/a (rescored). Declared per-run limits: ≤ 40 calls (never above a preset's own cap), ≤ 400000 measured tokens (enforced before each request; one reply may overshoot), ≤ 1800 s.

## Per-run results
| case | system | rep | state | kind | stop | calls/cap | tokens (measured) | elapsed s | cost | primary | checks |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gate_budget_fail | council_quick | 1 | COMPLETE | conditional | budget_tokens | 22/? | 421213 | 650.2 | unavailable | True | {'recommended_avoids': True, 'gate_failed_on_planted_option': True, 'completed': True, 'within_campaign_limits': True} |
| gate_budget_fail | first_pass | 1 | COMPLETE | shortlist | stable | 24/? | 374375 | 511.3 | unavailable | True | {'recommended_avoids': True, 'gate_failed_on_planted_option': True, 'completed': True, 'within_campaign_limits': True} |

## Aggregate per case × system (n, primary-measure pass rate, usage mean [min–max])
| case | system | n | primary pass | calls | tokens | elapsed s | budget-truncated | leader challenge reached | over campaign limits |
|---|---|---|---|---|---|---|---|---|---|
| gate_budget_fail | council_quick | 1 | 1/1 | 22 | 421213 | 650.2 | 1 | 0 | 0 |
| gate_budget_fail | first_pass | 1 | 1/1 | 24 | 374375 | 511.3 | 0 | 0 | 0 |


## Reference systems status
- llm-council-main (first-pass workflow): PROXY comparison only: the engine's own `first_pass` preset (frame, policy, baseline, lenses, judge, report; no review, verification or challenge) stands in for the reference; the original Claude Code agents were not run. They are runnable unattended through `claude -p` at roughly US$ 3 per case (new spend, user's decision)
- council-review-main: not run: a prompt-only Claude Code skill; runnable unattended through `claude -p` at roughly US$ 3-4 per case (new spend, user's decision)
- council-master: blocked by credentials: needs OPENAI_API_KEY-style keys for OpenAI-compatible endpoints (Gemini/xAI) in the environment; none present (the OpenAI access on this machine is a ChatGPT-account OAuth held inside OpenCode, not an API key); Google quota depleted (402)
- LLM-Council-Decide-master: blocked by credentials and dependencies: OPENROUTER_API_KEY and Typst not available
- neuralhats-main: live comparison ATTEMPTED on local Ollama (gemma4) with the engine's typo case; outcome, model match and evaluator result recorded in docs/llm_council.md section 16.5
- llm-as-a-verifier-main: blocked by dependencies (possibly unblockable): needs a log-probability backend (DeepSeek, Vertex or OpenAI-compatible with logprobs); none configured; the local Ollama server may expose logprobs but this was not tested