---
name: council-settings
description: Configure the LLM Council decision engine (providers and models per role, OpenCode route, jury, lenses, rubric thresholds, round/call/token/time/cost limits). Use when the user types /council-settings or asks to change how /council runs.
argument-hint: [show | set key=value ... | unset key | wizard | routes | presets | reset]
allowed-tools: Bash(.venv/bin/council *), Bash(cd *), Read
---

# /council-settings — saved settings for the council engine

Settings live in `.council/settings.json` (the **saved** layer). Precedence, lowest to highest:
built-in defaults < `council.config.json` (project) < saved settings < `--preset` < per-run flags.
Every write is validated against the full typed contract; an invalid value is refused and nothing is written.

Run every command from the project root (the folder Claude Code was started in; `.venv/bin/council` is relative to it).

## Procedure

1. Show the current state first and summarise it for the user in a few lines (what comes from which layer,
   whether the OpenCode route is enabled, how each limit is enforced):
   ```bash
   .venv/bin/council settings show
   .venv/bin/council settings routes
   ```
2. If the user gave explicit changes (`set key=value …`), apply them exactly as given:
   ```bash
   .venv/bin/council settings set limits.max_rounds=3 routing.roles.judge.provider=opencode routing.opencode.enabled=true
   ```
   Values are JSON (`true`, `3`, `0.5`, `"claude-agent/haiku"`, `null`).
3. If the user wants guidance, print the wizard and let them answer; then apply the answers:
   ```bash
   .venv/bin/council settings wizard
   .venv/bin/council settings wizard --answer judge.jury_size=2 --answer limits.max_model_calls=80
   ```
4. Report the controller's output verbatim: saved keys, the resulting effective values, enabled external routes.
   If the controller printed `error: … nothing written`, explain the validation error and ask for a corrected value.
5. `.venv/bin/council settings unset <key>` removes a saved key; `.venv/bin/council settings reset --yes` deletes the file
   (confirm with the user before running reset).
6. If the user prefers a form, `.venv/bin/council ui` serves a settings page at http://127.0.0.1:8771/settings with every key,
   its layer and explanation; changes go through the same validation.

## Keys worth knowing

- `routing.default_provider` (chat|opencode|fixture), `routing.roles.<role>.provider|model|temperature|top_p`
  for roles framer, policy_setter, strategist, reviewer, verifier, judge, challenger.
- `routing.opencode.enabled|default_model|fallback|timeout_seconds|retries|model_fallbacks`.
- `judge.jury_size|materiality_threshold|promotion_margin|unverified_gate_policy|half_widths.*|weight_perturbation`.
- `policy.weight_overrides` — rubric weights: a JSON object `{"criterion name or crit_id": weight}` that replaces the
  policy setter's relative weight for matching score criteria (e.g. `policy.weight_overrides={"cost":5,"crit_speed":1}`);
  applied keys and unmatched keys are recorded on the policy and as a `policy_weights_overridden` event.
- `lenses.selection|explicit|min|max`, `review.panel_size`.
- `limits.min_rounds|max_rounds|stable_rounds_required|max_model_calls|max_tokens_estimate|max_elapsed_seconds|max_cost_usd|finalisation_reserve_calls|max_verification_calls|max_reopens|max_leader_challenges`.

Enforcement: calls and rounds are counted; elapsed time is measured; tokens are measured on OpenCode replies and
estimated on chat replies; cost is enforceable only when a provider reports it (the chat route and subscription
providers report none).
