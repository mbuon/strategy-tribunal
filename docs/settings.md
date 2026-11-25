# Settings reference

Every key, what it does, its allowed values and three examples. Change them with `/council-settings`, `council settings set key=value`, or the settings page of the interface.


Every key, its meaning, type/range/default, and three examples (each example works with `council settings set …`, `/council-settings set …`, or per run with `--set …`).

#### `routing` — who answers which role

| Key | Description | Type / range / default |
|---|---|---|
| `routing.default_provider` | Provider used by every role that has no explicit routing. `chat` = the model of the current Claude Code conversation (step mode, shared context). `opencode` = the external OpenCode route (isolated sessions; needs `routing.opencode.enabled` or `--opencode`). `fixture` = deterministic replay for tests. | `chat` \| `opencode` \| `fixture`; default `chat` |

```bash
council settings set routing.default_provider=chat
council settings set routing.default_provider=opencode routing.opencode.enabled=true
council run "<q>" --fixture tests/fixtures/main_run.json --set routing.default_provider=fixture   # per run, tests
```

| Key | Description | Type / range / default |
|---|---|---|
| `routing.roles.<role>.provider` | Provider for one role. Roles: `framer`, `policy_setter`, `strategist`, `reviewer`, `verifier`, `judge`, `challenger`. Unknown roles are rejected. | `chat` \| `opencode` \| `fixture`; default: inherits `default_provider` |
| `routing.roles.<role>.model` | Model id for that role on the OpenCode route (`provider/model` as listed by `opencode models`). Ignored on `chat` (the conversation model answers). If the id is not listed, `model_fallbacks` or `default_model` is substituted and recorded. | string; default: `routing.opencode.default_model` |
| `routing.roles.<role>.temperature` / `top_p` | Sampling parameters passed to providers that support them. The chat route cannot apply them (recorded as `sampling_supported = false`). | 0–2 / 0–1; default none |

```bash
council settings set routing.roles.judge.provider=opencode 'routing.roles.judge.model="claude-agent/haiku"'
council settings set routing.roles.reviewer.provider=opencode 'routing.roles.reviewer.model="ollama/gemma4:26b"' routing.roles.reviewer.temperature=0.4
council settings set routing.roles.challenger.provider=opencode 'routing.roles.challenger.model="openai/gpt-6.2-sol"' routing.roles.challenger.top_p=0.9
```

| Key | Description | Type / range / default |
|---|---|---|
| `routing.validation_fallbacks` | Models tried in order, one attempt each through OpenCode, when a role's reply keeps failing validation (schema errors, unknown ids) after `retries.max_attempts` on its own route. The fallback receives the same payload (discussion and documents included) plus the previous error; the switch is recorded as a `route_fallback` event with reason `validation`, and the participant shows the model that finally answered. Project default: `["openai/gpt-6.2-sol", "muse-code/muse-spark-1.3-contributor"]`. | list of `provider/model`; default `[]` |
| `routing.opencode.enabled` | Master switch for the external route. Off = the OpenCode binary is never resolved or spawned. `--opencode` on a run is the per‑run equivalent. | bool; default `false` |
| `routing.opencode.binary` | Name or path of the OpenCode executable. | string; default `opencode` |
| `routing.opencode.agent` | OpenCode agent used for every call; the shipped `council-member` agent denies all tools and carries a deliberation‑only system prompt. | string; default `council-member` |
| `routing.opencode.config_dir` | Folder holding the agent's `opencode.json`; each call runs with this as working directory and `PWD` (OpenCode resolves its project from `PWD`). | path; default `adapters/opencode` |
| `routing.opencode.timeout_seconds` | Wall‑clock limit per OpenCode call before it counts as failed. | 5–3600; default 300 |
| `routing.opencode.retries` | Retries after a failed/timed‑out call before the fallback applies. | 0–5; default 1 |
| `routing.opencode.fallback` | What happens when a call still fails: `chat` re‑routes the request to the conversation model, `fixture` to the fixture provider (tests), `fail` records a failed request (the controller takes the failure transition: lens skipped, judgement missing, …). | `chat` \| `fixture` \| `fail`; default `chat` |
| `routing.opencode.default_model` | Model used by OpenCode‑routed roles that name none. | `provider/model`; default `claude-agent/haiku` (project) |
| `routing.opencode.model_fallbacks` | Map of requested model → substitute when the requested one is not listed by `opencode models`; substitutions are recorded as `route_substitution` events. | object; default `{}` |
| `routing.opencode.verify_version` | Check `opencode --version` is v2.x once per run before the first call. | bool; default `true` |
| `routing.opencode.discover_models` | Run `opencode models` once per run and substitute unlisted ids. | bool; default `true` |
| `routing.opencode.standalone` | Pass `--standalone` so each call uses a private server that sees `config_dir` (required on this machine, see docs §10). | bool; default `true` |

```bash
council settings set routing.opencode.enabled=true 'routing.opencode.default_model="claude-agent/haiku"'
council settings set routing.opencode.timeout_seconds=600 routing.opencode.retries=2 'routing.opencode.fallback="chat"'
council settings set 'routing.opencode.model_fallbacks={"google/gemini-flash-latest":"claude-agent/haiku"}' routing.opencode.discover_models=true
```

#### `judge` — scoring contract and promotion rule

| Key | Description | Type / range / default |
|---|---|---|
| `judge.jury_size` | Judges per option version. With 2+ judges every version is scored by each; disagreement widens the score bounds and is reported as `judge_agreement`. Model diversity only exists on the OpenCode route. | 1–5; default 1 |
| `judge.method` | Scoring method recorded on every judgement. `structured_scores` = per‑criterion integer scores with confidence. `logprob_expectation` is accepted but has no backend on either route (falls back to structured scores). | enum; default `structured_scores` |
| `judge.half_widths.high` / `.medium` / `.low` | Half‑width of the conservative score interval attached to a criterion score at that judge confidence (heuristic, labelled as such). Promotion compares the challenger's lower bound with the incumbent's upper bound. | 0–5 each; defaults 0.5 / 1.0 / 1.5 |
| `judge.half_width_label` | Label recorded with the bounds (documentation only). | string; default `heuristic` |
| `judge.promotion_margin` | Extra margin the challenger's lower bound must clear beyond the incumbent's upper bound to be promoted. | 0–5; default 0 |
| `judge.materiality_threshold` | Minimum meaningful score difference; smaller gaps are ties and count towards stability. | 0–5; default 0.5 |
| `judge.unverified_gate_policy` | Treatment of a gate the judge could not verify: `fail` disqualifies, `penalty` keeps the option but subtracts `unverified_gate_penalty` per unverified gate, `flag` only reports it. | enum; default `penalty` |
| `judge.unverified_gate_penalty` | Points subtracted per unverified gate under `penalty`. | 0–10; default 1 |
| `judge.pairwise_tiebreak` | When incumbent and top challenger are within materiality with overlapping bounds, issue two `compare` requests with swapped candidate order and let both passes decide. | bool; default `true` |
| `judge.screen_above` / `judge.finalists` | Reserved for a bounded top‑k pairwise screening round; accepted and validated but **currently read nowhere** (inert). | 2–50 / 2–10; defaults 6 / 3 |
| `judge.weight_perturbation` | Relative change applied to each criterion weight in the sensitivity analysis (ranking flips are reported). | 0–1; default 0.2 |
| `judge.rescore_scope` | Which versions are re‑judged when the comparison key changes (new evidence, rubric or judge configuration): `all_active` or only `incumbent_and_new`. | enum; default `all_active` |

```bash
council settings set judge.jury_size=2 judge.materiality_threshold=0.75
council settings set judge.promotion_margin=0.25 judge.half_widths.low=2.0 judge.half_widths.medium=1.25
council settings set 'judge.unverified_gate_policy="fail"' judge.pairwise_tiebreak=false 'judge.rescore_scope="incumbent_and_new"'
```

#### `policy` — rubric weights

| Key | Description | Type / range / default |
|---|---|---|
| `policy.weight_overrides` | Relative weights that replace the policy setter's proposal for matching **score** criteria when the evaluation policy is registered. Keys are criterion ids (`crit_cost`) or criterion names (matched case‑insensitively after slugging: `"Cost efficiency"` matches `crit_cost_efficiency`). Weights are normalised afterwards. Applied and unmatched keys are recorded on the policy and as a `policy_weights_overridden` event. Gates never take a weight. | object of `string → number > 0`; default `{}` |

```bash
council settings set 'policy.weight_overrides={"cost efficiency":5,"crit_speed":1}'
council settings set 'policy.weight_overrides={"brand fit":3,"measurability":3,"execution risk":1}'
council settings unset policy.weight_overrides        # back to the policy setter's weights
```

#### `lenses` — reasoning methods for strategy generation

| Key | Description | Type / range / default |
|---|---|---|
| `lenses.selection` | `auto` picks lenses from the brief (stakes, uncertainty, reversibility, likely blind spots); `explicit` uses `lenses.explicit` only. `--lenses a,b` on a run sets both. | enum; default `auto` |
| `lenses.explicit` | Lens ids: `first_principles`, `inversion`, `staging`, `information_option`, `asymmetric_upside`, `outside_view`, `execution`, `second_order`, `expected_value`, `time_horizons`, `regret`, `tempo`, `internal_external`, `multidisciplinary`, `widen_reality_test`, `balanced_ledger`, `hat_facts`, `hat_risks`, `hat_creative` (observer hats produce challenges, not options). | list; default `[]` |
| `lenses.min` / `lenses.max` | Number of lenses per run under `auto` (min ≤ max). Each lens costs one strategist call per round. | 1–12; defaults 3 / 5 |
| `lenses.always_include_staged` | Under `auto`, always include the staged‑commitment lens. | bool; default `true` |
| `lenses.always_include_information_option` | Under `auto`, always include the targeted information‑gathering lens. | bool; default `true` |
| `lenses.always_include_status_quo` | Accepted for symmetry; the status quo is always part of the round‑zero baseline regardless (inert). | bool; default `true` |

```bash
council settings set lenses.min=2 lenses.max=3
council settings set 'lenses.selection="explicit"' 'lenses.explicit=["staging","inversion","outside_view","expected_value"]'
council settings set lenses.always_include_information_option=false lenses.max=4
```

#### `review` — cross‑review

| Key | Description | Type / range / default |
|---|---|---|
| `review.panel_size` | Reviewers per round. 0 disables review (first‑pass style). Each reviewer costs one call per round and may open typed challenges, dissent or a reframe. | 0–6; default 2 |
| `review.challenge_cycles_max` | Reserved cap for challenge/response cycles per round; accepted but currently inert (one response cycle per round). | 0–3; default 1 |

```bash
council settings set review.panel_size=1
council settings set review.panel_size=3 judge.jury_size=2          # deep-style review
council settings set review.panel_size=0                             # no review: baseline + lenses + judging only
```

#### `limits` — rounds and budgets

| Key | Description | Type / range / default |
|---|---|---|
| `limits.min_rounds` | Deliberation rounds that must complete before stability or "no productive follow‑up" can stop the run. | 0–20; default 2 |
| `limits.max_rounds` | Hard cap on deliberation rounds (stop reason `max_rounds`). Must be ≥ `min_rounds`. | 1–20; default 4 |
| `limits.stable_rounds_required` | Consecutive comparable rounds with gains below materiality (and no blocking objection) that count as stable. | 1–10; default 2 |
| `limits.max_model_calls` | Call budget per run, counted per request (rejected and retried submissions count). Must exceed `finalisation_reserve_calls`. | 1–10000; default 60 (quick 24, deep 120) |
| `limits.max_tokens_estimate` | Token budget: measured on OpenCode replies, estimated (chars/4) on chat replies; checked before every request, so one reply may overshoot. | ≥ 1000; default 400000 |
| `limits.max_elapsed_seconds` | Wall‑clock budget since run start. | > 0; default 1800 |
| `limits.max_cost_usd` | Cost budget; enforceable only when a provider reports cost (subscription providers report none → recorded as unavailable). | ≥ 0 or `null`; default `null` |
| `limits.finalisation_reserve_calls` | Calls kept back from deliberation so the leader challenge and final judging can still run. | 0–50; default 3 |
| `limits.max_reframes` | Reframes (new brief version proposed by a reviewer) accepted per run. | 0–5; default 1 |
| `limits.max_reopens` | Times an unresolved leader challenge may reopen deliberation. | 0–5; default 1 |
| `limits.max_verification_calls` | Verifier calls per run for evidence checks. | 0–50; default 3 |
| `limits.max_leader_challenges` | Dedicated sceptical passes against the leader. 0 disables (first‑pass preset). | 0–5; default 1 |

```bash
council settings set limits.min_rounds=1 limits.max_rounds=2 limits.max_model_calls=30
council settings set limits.max_tokens_estimate=800000 limits.max_elapsed_seconds=3600 limits.max_cost_usd=5
council settings set limits.stable_rounds_required=1 limits.max_reopens=2 limits.max_verification_calls=6 limits.finalisation_reserve_calls=4
```

#### `storage` — run folders and web interface

| Key | Description | Type / range / default |
|---|---|---|
| `storage.runs_root` | Folder, relative to the project root, that receives one sub‑folder per run named `YYYY-MM-DD_HH-MM-SS_question-slug`. | path; default `council_outcomes` |
| `storage.legacy_runs_root` | Older runs folder still searched when a run id is not found under `runs_root`. | path; default `.council/runs` |
| `storage.dashboard` | Write `index.html` after every controller step. | bool; default `true` |
| `storage.ui_port` | Port of the local web interface (`council ui`, `/council … --ui`), bound to 127.0.0.1. | 1024–65535; default 8771 |

```bash
council settings set 'storage.runs_root="decisions"'
council settings set storage.ui_port=8900
council settings set storage.dashboard=false            # no index.html; `council dashboard <id>` still renders on demand
```

#### `discussion` — what each role reads of the others

| Key | Description | Type / range / default |
|---|---|---|
| `discussion.include` | `current_round_and_summaries` (full text of this round's contributions, digest and summaries of earlier rounds), `full` (everything in full), `summaries` (short summaries only), `none` (independent calls, as in Run 1). | enum; default `current_round_and_summaries` |
| `discussion.max_chars` | Cap on the discussion excerpt in each request; oldest material is shortened, then dropped. | 1000–2 000 000; default 30000 |
| `discussion.write_transcript` | Write `discussion/` files and `discussion.md`. | bool; default `true` |

```bash
council settings set 'discussion.include="full"' discussion.max_chars=120000
council settings set 'discussion.include="summaries"'
council settings set 'discussion.include="none"'            # independent calls (benchmark the difference)
```

#### `documents` — limits for `--docs`

| Key | Description | Type / range / default |
|---|---|---|
| `documents.max_file_bytes` | Largest single file read. | ≥ 1000; default 200000 |
| `documents.max_total_bytes` | Total bytes read across all files. | ≥ 1000; default 2000000 |
| `documents.max_chars_in_payload` | Cap on document excerpts per request. | ≥ 500; default 40000 |
| `documents.max_chars_per_document` | Cap on one document's excerpt per request. | ≥ 200; default 12000 |
| `documents.extensions` | Extensions read; others are skipped and listed in `inputs/INDEX.md`. | list; default text/code formats |

```bash
council settings set documents.max_file_bytes=1000000 documents.max_total_bytes=10000000
council settings set documents.max_chars_in_payload=80000
council settings set 'documents.extensions=[".md",".txt",".csv"]'
```

#### `defaults` — what a run uses when the command line says nothing

| Key | Description | Type / range / default |
|---|---|---|
| `defaults.preset` | Preset applied when `/council` or the CLI names no `--preset`. | `quick` \| `standard` \| `deep` \| `first_pass` \| `null`; default `null` (project limits) |
| `defaults.chat_model` | Identity recorded as "who answered" for chat‑routed roles when a run does not pass `--chat-model` (the `/council` skill passes its own id). | string or `null`; default `null` |

```bash
council settings set 'defaults.preset="quick"'
council settings set 'defaults.chat_model="claude-sonnet-5-5"'
council settings unset defaults.preset
```

#### `retries`, `report`, `fixture_path`, `seed`

| Key | Description | Type / range / default |
|---|---|---|
| `retries.max_attempts` | Attempts per request before the controller takes the failure transition (invalid JSON, schema rejection, unknown ids are retried with the error shown). | 1–5; default 2 |
| `report.narrative_model_call` | Reserved flag for a model‑written narrative; the report is controller‑computed and this flag is currently inert. | bool; default `false` |
| `fixture_path` | Deterministic fixture file for autonomous test runs (`--fixture` sets it). | path or `null`; default `null` |
| `seed` | Seed for the controller's own randomness (pseudonym shuffles, counterbalanced order). | int; default 7 |

```bash
council settings set retries.max_attempts=3
council settings set seed=42
council run "<q>" --set 'fixture_path="tests/fixtures/first_pass.json"' --preset first_pass --lenses staging,information_option,asymmetric_upside
```

#### Presets as overrides

A preset is a bundle of the keys above, applied between the saved layer and per‑run flags: `quick` = rounds 1–2, 24 calls, 1 reviewer, 1 verification, 2–3 lenses; `deep` = rounds 3–6, 120 calls, 3 reviewers, 6 verifications, 2 reopens, jury 2, 4–6 lenses; `first_pass` = 1 round, no review, no verification, no leader challenge. `council settings presets` prints the exact values.