# Benchmark campaign 2026-11-24T21:03

> SUPERSEDED (history only): ran 17:03–19:04 on 2026-11-24 while the engine changed (gate/budget fixes at 17:14, 17:26, 18:14) -> mixed code versions; token/time limits were not yet enforced per request; call cap override raised the quick preset to 40.

Cases spec version: 2026-11-24.2. In-run model: claude-agent/haiku (OpenCode restricted agent, all roles, isolation `isolated`). Evaluator: claude-agent/sonnet (blinded A/B, 2 repeats, order randomised).
Runs: 12. Stopped early: n/a (rescored). Declared per-run limits: ≤ 40 calls (never above a preset's own cap), ≤ 400000 measured tokens (enforced before each request; one reply may overshoot), ≤ 1800 s.

## Per-run results
| case | system | rep | state | kind | stop | calls/cap | tokens (measured) | elapsed s | cost | primary | checks |
|---|---|---|---|---|---|---|---|---|---|---|---|
| obj_vendor_ev | council_quick | 1 | COMPLETE | no_eligible_option | trivial_question | 7/? | 101224 | 164.1 | unavailable | False | {'recommended_matches': False, 'kind_acceptable': False, 'completed': True, 'within_campaign_limits': True} |
| obj_vendor_ev | first_pass | 1 | COMPLETE | firm | trivial_question | 8/? | 114181 | 183.8 | unavailable | False | {'recommended_matches': False, 'kind_acceptable': True, 'completed': True, 'within_campaign_limits': True} |
| gate_budget_fail | council_quick | 1 | COMPLETE | firm | budget_tokens | 28/? | 532091 | 821.9 | unavailable | False | {'recommended_avoids': True, 'gate_failed_on_planted_option': False, 'completed': True, 'within_campaign_limits': True} |
| gate_budget_fail | first_pass | 1 | COMPLETE | shortlist | max_rounds | 25/? | 395167 | 555.3 | unavailable | False | {'recommended_avoids': True, 'gate_failed_on_planted_option': False, 'completed': True, 'within_campaign_limits': True} |
| open_channel_mix | council_quick | 1 | COMPLETE | conditional | budget_calls | 41/? | 1061715 | 1549.1 | unavailable | None | {'completed': True, 'within_campaign_limits': False} |
| open_channel_mix | first_pass | 1 | COMPLETE | firm | budget_tokens | 36/? | 767146 | 1177.1 | unavailable | None | {'completed': True, 'within_campaign_limits': True} |
| false_premise | council_quick | 1 | COMPLETE | conditional | budget_tokens | 22/? | 400836 | 625.0 | unavailable | True | {'kind_acceptable': True, 'premise_flagged': True, 'completed': True, 'within_campaign_limits': True} |
| false_premise | first_pass | 1 | COMPLETE | firm | budget_tokens | 23/? | 412271 | 592.9 | unavailable | True | {'kind_acceptable': True, 'premise_flagged': True, 'completed': True, 'within_campaign_limits': True} |
| deferral_missing_info | council_quick | 1 | COMPLETE | conditional | budget_tokens | 21/? | 421018 | 706.2 | unavailable | True | {'kind_acceptable': True, 'completed': True, 'within_campaign_limits': True} |
| deferral_missing_info | first_pass | 1 | COMPLETE | firm | budget_tokens | 24/? | 413957 | 617.6 | unavailable | False | {'kind_acceptable': False, 'completed': True, 'within_campaign_limits': True} |
| trivial_overhead | council_quick | 1 | COMPLETE | firm | trivial_question | 6/? | 71048 | 116.3 | unavailable | True | {'stop_reason_acceptable': True, 'within_call_cap': True, 'completed': True, 'within_campaign_limits': True} |
| trivial_overhead | first_pass | 1 | COMPLETE | firm | trivial_question | 6/? | 70554 | 107.3 | unavailable | True | {'stop_reason_acceptable': True, 'within_call_cap': True, 'completed': True, 'within_campaign_limits': True} |

## Aggregate per case × system (n, primary-measure pass rate, usage mean [min–max])
| case | system | n | primary pass | calls | tokens | elapsed s | budget-truncated | leader challenge reached | over campaign limits |
|---|---|---|---|---|---|---|---|---|---|
| obj_vendor_ev | council_quick | 1 | 0/1 | 7 | 101224 | 164.1 | 0 | 0 | 0 |
| obj_vendor_ev | first_pass | 1 | 0/1 | 8 | 114181 | 183.8 | 0 | 0 | 0 |
| gate_budget_fail | council_quick | 1 | 0/1 | 28 | 532091 | 821.9 | 1 | 1 | 0 |
| gate_budget_fail | first_pass | 1 | 0/1 | 25 | 395167 | 555.3 | 0 | 0 | 0 |
| open_channel_mix | council_quick | 1 | rubric | 41 | 1061715 | 1549.1 | 1 | 1 | 1 |
| open_channel_mix | first_pass | 1 | rubric | 36 | 767146 | 1177.1 | 1 | 0 | 0 |
| false_premise | council_quick | 1 | 1/1 | 22 | 400836 | 625.0 | 1 | 0 | 0 |
| false_premise | first_pass | 1 | 1/1 | 23 | 412271 | 592.9 | 1 | 0 | 0 |
| deferral_missing_info | council_quick | 1 | 1/1 | 21 | 421018 | 706.2 | 1 | 0 | 0 |
| deferral_missing_info | first_pass | 1 | 0/1 | 24 | 413957 | 617.6 | 1 | 0 | 0 |
| trivial_overhead | council_quick | 1 | 1/1 | 6 | 71048 | 116.3 | 0 | 0 | 0 |
| trivial_overhead | first_pass | 1 | 1/1 | 6 | 70554 | 107.3 | 0 | 0 | 0 |

## Blinded rubric evaluations (open cases)
| case | runs rep | pair (order shown) | eval repeat | winner | scores | reason |
|---|---|---|---|---|---|---|
| open_channel_mix | 1 | first_pass vs council_quick | 1 | first_pass | {"council_quick": {"defensibility": 7, "completeness": 8, "actionability": 6}, "first_pass": {"defensibility": 7, "completeness": 6, "actionability": 8}} | A gives a concrete, capped 10k pilot with explicit gates, a revert rule and a holdout, while B is more thorough on risks and dissent but its next action is a list of open uncertainties rather than one clear step. |
| open_channel_mix | 1 | council_quick vs first_pass | 2 | council_quick | {"council_quick": {"defensibility": 8, "completeness": 8, "actionability": 6}, "first_pass": {"defensibility": 6, "completeness": 6, "actionability": 8}} | A is better calibrated, with low confidence, open objections and power and incrementality gaps named. B gives a more concrete gated plan but calls its outcome firm and medium confidence while its own gate thresholds are unvalidated, and it lists no dissent or objections despite acknowledging missing data. |

Wins/ties/losses (evaluator verdicts): {'first_pass': 1, 'council_quick': 1}
- mean rubric council_quick: defensibility 7.5, completeness 8.0, actionability 6.0 (n=2)
- mean rubric first_pass: defensibility 6.5, completeness 6.0, actionability 8.0 (n=2)


## Reference systems status
- llm-council-main (first-pass workflow): PROXY comparison only: the engine's own `first_pass` preset (frame, policy, baseline, lenses, judge, report; no review, verification or challenge) stands in for the reference; the original Claude Code agents were not run. They are runnable unattended through `claude -p` at roughly US$ 3 per case (new spend, user's decision)
- council-review-main: not run: a prompt-only Claude Code skill; runnable unattended through `claude -p` at roughly US$ 3-4 per case (new spend, user's decision)
- council-master: blocked by credentials: needs OPENAI_API_KEY-style keys for OpenAI-compatible endpoints (Gemini/xAI) in the environment; none present (the OpenAI access on this machine is a ChatGPT-account OAuth held inside OpenCode, not an API key); Google quota depleted (402)
- LLM-Council-Decide-master: blocked by credentials and dependencies: OPENROUTER_API_KEY and Typst not available
- neuralhats-main: live comparison ATTEMPTED on local Ollama (gemma4) with the engine's typo case; outcome, model match and evaluator result recorded in docs/llm_council.md section 16.5
- llm-as-a-verifier-main: blocked by dependencies (possibly unblockable): needs a log-probability backend (DeepSeek, Vertex or OpenAI-compatible with logprobs); none configured; the local Ollama server may expose logprobs but this was not tested