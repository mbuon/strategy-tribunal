# Strategy Tribunal — autonomous 360° decision engine

Design and delivery record for the engine specified in `docs/spec.md`. Sections 1–13 were written before implementation and then updated to the delivered system; section 14 is the Run 1 handoff (kept as history); section 16 is the Run 2 delivery record (settings interface, live verification, benchmarks).

Status: **Run 1 complete (§14, 2026‑11‑24) · Run 2 complete (§16, 2026‑11‑24) — 102 deterministic tests pass; live `/council` runs, OpenCode route and benchmark campaign recorded in §16.**

---

## 1. Scope and resolved decisions

| Decision | Resolution | Reversible? |
|---|---|---|
| Target project root | `/Users/massimo/Projects_Massimo/strategy-tribunal/` (repository `github.com/mbuon/strategy-tribunal`; `docs/spec.md` and `original/` live under it) | Yes (move folder; paths are relative) |
| Chat surface | Claude Code (CLI 2.1.331 installed) running in the current conversation. The model in default mode is the chat model of the session. | Yes |
| Chat entry point | Project skill `council/.claude/skills/council/SKILL.md`, invoked as `/council <question> [flags]`. **Run 2 finding:** skills are discovered when Claude Code is started in `council/` (confirmed from a fresh headless session, §16.3); they are **not** discovered as directory‑scoped skills when the session starts in the parent folder (the Run 1 assumption `council:council` did not hold: a session started in the parent listed neither `council` nor `council-settings`). Start Claude Code in `council/`. | Yes (same engine can be wired to a `.claude/commands/*.md` command) |
| Engine language and runtime | Python ≥ 3.12 package `llm_council` under `council/src/`, `pydantic` v2 for the validated protocol. Installed with plain `pip` into `.venv` (`python3 -m venv .venv && pip install -e ".[dev]"`); commands are `council …` and `python -m pytest`. (Run 1 used `uv` for the same environment; the switch to pip‑only happened post‑delivery at the user's request, §17.) | Yes |
| Controller/model split | The Python engine is the **controller**: it owns state, validation, judging arithmetic, budgets and stopping. Models (chat model, fixture, OpenCode participants) are **responders** that answer one validated `PhaseRequest` at a time. Only the controller commits state. | Core decision |
| Default mode | One model, shared context, controller‑managed phase calls ("step mode"): the engine writes a request, the chat model answers it, the engine validates and advances. Recorded as `context_isolation = shared`. No pseudonyms in shared mode (they would not withhold anything). | Yes |
| OpenCode | Off by default. Enabled via config (`routing.opencode.enabled`) or prompt override (`--opencode`). Installed version verified: `opencode v2.3.2`; interface `run --format json`; restricted agent via project `opencode.json`; **standalone mode + `PWD`** required (see §10). | Yes |
| Persistence | Append‑only `events.jsonl` + `state.json` snapshot per run in its own folder `council/council_outcomes/<YYYY-MM-DD_HH-MM-SS_question-slug>/` (`storage.runs_root`; Run 1/2 runs under `.council/runs/` remain readable, §17). Resume from snapshot; retries safe through dedup keys; one response is applied as one transaction. | Yes |
| Settings UI | Delivered in Run 2 following the repo's conventions (typed config file + CLI commands + Claude Code skill): saved layer `.council/settings.json`, `council settings show|set|unset|reset|validate|routes|presets|wizard`, skill `/council-settings`, and since §17 the local web page `council ui` (`/settings`) (`.claude/skills/council-settings/SKILL.md`). Every write validates the *effective* configuration and refuses invalid values without touching the file (§16.2). | Yes |

No design question needed the user: one plausible implementation target and one chat surface. Assumptions above are reversible.

---

## 2. Reference coverage matrix

Legend: **A** adopt, **I** improve, **E** equivalent, **X** exclude (with reason). "Impl" names the module/function in this engine; "Check" names the deterministic test that exercises it (all in `tests/`). Classification of the reference finding: *code* = implemented mechanism, *prompt* = prompt‑level behaviour only, *reported* = result claimed by authors, not reproduced here. File references are relative to `council/original/<project>/` and were verified by direct reading on 2026‑11‑24.

### 2.1 council-master (MIT, Michael Dubell)

| Capability (evidence) | Class | Verdict | Impl | Check |
|---|---|---|---|---|
| Bounded proposal → debate loop, `max_turns` default 3 enforced after the consensus check (`src/council/nodes/debate_node.py:348-358`, `flow.py:60-77`) | code | **I** — outer round loop with `min_rounds`/`max_rounds`, finalisation reserve and explicit stop reasons | `engine.py: Engine._decide_continue`, `config.py: Limits` | `test_engine_fixture_main.py::test_run_completes_with_recorded_stop_reason`, `test_budget.py` |
| Typed debate actions `REVISE/AGREE/CONCERN` (`models.py:9-14`, validation `debate_node.py:242-296`) | code | **I** — richer typed records (`Challenge`, `Response{rebut, concede, revise, request_verification, withdraw, reinstate}`, `OptionVersion` with `change_reason`) validated before commit | `ontology.py`, `phases.py` | `test_ontology_and_lenses.py::test_store_rejects_unknown_references_before_mutation` |
| Partial revisions, lists replaced wholesale, state replayed from transcript (`context.py:6-41`); **no proposal ids or versions**, `Proposal.turn` always 0 | code | **I** — immutable `OptionVersion` with stable `option_id`, `parent_version_id`, `supersedes` relation | `ontology.py: OptionVersion`, `state.py: Store.commit` | `test_ontology_and_lenses.py::test_lineage_supersedes_relation_and_duplicate_ids`, `test_engine_fixture_main.py::test_rejected_regression_round_2` |
| Latest‑action agreement map (`context.py:52-61`) and **agreement‑based early exit** (`debate_node.py:363-383`) | code | **X** (replaced) — stopping uses ranking stability on comparable rounds + absence of blocking objections + budget, never agreement counts | `engine.py: blocking_challenges, _decide_continue` | `test_engine_fixture_main.py::test_no_agreement_based_stop` |
| Per‑agent summaries with deterministic fallback (`agent_summary_node.py:108-197`), deterministic compaction (`context.py:64-99`) | code | **E** — `RoundSummary` is computed by the controller from records; open challenges and dissent ids are carried | `report.py: build_round_summary` | `test_engine_fixture_main.py::test_withdrawal_and_dissent_survive` |
| Per‑persona provider/model/temperature from YAML (`input_node.py:32-73`); moderator borrows persona 0 (`consensus_node.py:40-44`) | code | **I** — per‑role routing in `routing.roles[role]` for all seven roles | `config.py: Routing.for_role` | `test_config.py::test_role_routing_defaults_and_override` |
| Approval parse failure counts as approval (`consensus_node.py:323-331`); single silent revision pass (`:396-401`) | code | **X** (anti‑pattern) — malformed output is rejected and retried; the report is rendered from committed records only | `engine.py: _apply_submission` | `test_schema_rejection.py` |
| Failed turn written into the debate as a CONCERN with exception text (`debate_node.py:311-317`) | code | **X** — failures become `RunEvent{request_failed}` and never deliberation records | `engine.py: _on_request_failed` | `test_schema_rejection.py::test_retries_exhausted_fails_run_with_event_not_record` |

### 2.2 council-review-main (MIT, Neal Meyer; archived at V2.1)

| Capability (evidence) | Class | Verdict | Impl | Check |
|---|---|---|---|---|
| Five distinct reasoning methods (`SKILL.md:47-53`, `:145-149`) | prompt | **A** — lens catalogue with method tags; automatic selection by stakes/reversibility/domain/evidence gaps | `lenses.py: LENSES, select_lenses` | `test_ontology_and_lenses.py::test_lens_selection_by_stakes_and_reversibility` |
| Sycophancy guardrail (`SKILL.md:137`) | prompt | **A** — in every request | `prompts.py: GUARDRAIL` | `test_ontology_and_lenses.py::test_guardrail_present_in_every_instruction` |
| Anonymous peer review; shuffle done by the orchestrating LLM "in its head" (`:176`); blindness only through separate subagent contexts (`:113-115`) | prompt (+ runtime isolation) | **I** — pseudonymised, authorship‑free review payload **only** on the isolated provider (OpenCode); the alias map never leaves the controller; in shared mode no pseudonyms and the report states the limitation | `engine.py: _alias_for, _on_REVIEWING` | `test_opencode_route.py::test_isolated_review_payload_withholds_authorship`, `test_engine_fixture_main.py::test_generation_precedes_review_and_shared_mode_recorded` |
| Devil's Advocate against the emerging consensus, "the ONE thing" (`:223-250`) | prompt | **I** — `CHALLENGING` phase: losing scenario, strongest alternative, distinguishing evidence, `could_alter_outcome`; reopens deliberation when it could alter the outcome and budget/rounds remain | `engine.py: _on_CHALLENGING`, `phases.py: apply_leader_challenge` | `test_engine_fixture_main.py::test_unresolved_challenge_changes_final_action` |
| Mediating Assessments: attributes before the verdict (`:256`) | prompt | **A (enforced)** — the judge schema has no overall score; the controller computes the aggregate | `ontology.py: Judgement`, `judge.py: finalize_judgement` | `test_judge.py::test_model_cannot_supply_aggregate` |
| Dissent preservation "What You Lose" (`:302`) | prompt | **A** — `Dissent` records → `Decision.material_dissent_ids`, trade‑offs | `report.py: build_decision` | `test_first_pass_and_report.py::test_decision_fields_and_report_sections` |
| Optional jury (`:258`; same‑model jury "mostly theater" `:357`) | prompt | **E** — `judge.jury_size`; disagreement widens bounds and is reported; model diversity only real on the OpenCode route | `judge.py: combine` | `test_judge.py::test_jury_disagreement_widens_bounds_and_is_measured` |
| `--measure-diversity`, `--adaptive` KS/Jaccard numbers (`:161-172`, `:209-221`) | prompt (LLM‑estimated) | **X / E** — convergence = controller‑measured ranking stability on comparable judgements; correlated reasoning surfaced by the review question "genuine agreement or shared framing" and lens diversity; decision quality = judge aggregate. Reported as three separate signals. | `report.py: Signals` | `test_engine_fixture_main.py::test_signals_reported_separately` |
| Scope gate for trivial questions (`:75`) | prompt | **E** — `decision_kind = trivial` → direct baseline answer, stop reason `trivial_question` | `engine.py: _decide_continue` | `test_schema_rejection.py::test_malformed_then_valid_is_rejected_then_retried` |
| `tests/eval.sh` greps SKILL.md | code | **X** — our tests execute the engine | — | — |

### 2.3 llm-as-a-verifier-main (MIT)

| Capability (evidence) | Class | Verdict | Impl | Check |
|---|---|---|---|---|
| Criterion‑level scoring, 20‑letter scale, expectation over logprobs (`llm_verifier/fine_grained_reward.py:70-90`, `:668-712`) | code | **E / optional** — criteria‑first scoring adopted; log‑probability scoring is an optional method (`judge.method = logprob_expectation`) that no available provider supports today; `structured_scores` recorded | `judge.py`, `ontology.py: ScoringMethod` | `test_judge.py::test_method_recorded` |
| Swapped order on odd repeats (`:851-857`); `compare()` does not swap (`__init__.py:264-275`) | code | **A** — close comparisons run two pairwise passes with swapped order; disagreement → `inconclusive` | `engine.py: _compare_request, _adjudicate`, `judge.py: promotion` | `test_judge.py::test_swapped_order_disagreement_is_inconclusive_and_agreement_breaks_tie` |
| Missing results silently 0.5 (`:794-795`, `:832-834`) | code | **X** — missing judgements are explicit (`status = missing`), comparisons `non_comparable`, never imputed | `judge.py: combine, promotion` | `test_judge.py::test_mixed_keys_are_non_comparable_and_missing_is_explicit`, `test_budget.py` |
| Pivot tournament (`pivot_tournament.py:28-71`) | code | **E (bounded)** — absolute per‑option scoring ranks all candidates (the screening); the incumbent and the top challenger are then **directly compared** pairwise when close. A bounded top‑k pairwise round was **not delivered**: `judge.screen_above` and `judge.finalists` are accepted and validated by the configuration contract but read nowhere in `src/` (inert settings, documented in §16.7). | `engine.py: _adjudicate` | `test_judge.py::test_promotion_rule_outcomes`; engine‑level swapped‑order compare: `test_reframe_reinstate_tiebreak_jury.py` |
| Progress tracking (`progress.py:236-400`) | code | **E** — per‑round `delta_vs_prior_incumbent` / `net_vs_round0` as decision‑quality progress | `report.py` | `test_engine_fixture_main.py::test_material_promotion_round_1` |
| Token accounting, no cost (`fine_grained_reward.py:235-314`) | code | **A** — measured tokens when the provider reports them (OpenCode), estimated (len/4) otherwise, labelled | `budget.py` | `test_budget.py::test_budget_labels_measured_vs_estimated`, `test_opencode_route.py` |
| Reported results (TB4.0 Bo5 64.8 → 69.2 %, `README.md:125-132`) | reported | not reproduced (no log‑probability backend; §16.5 status table) | — | — |
| Logprob backends exclude plain Gemini and Anthropic (`:110-111`; deps `pyproject.toml:25-29`) | code | constraint recorded: logprob signal unavailable on both routes here | — | — |

### 2.4 LLM-Council-Decide-master (no LICENSE file → all rights reserved; nothing copied, only public framework names mapped)

| Capability (evidence) | Class | Verdict | Impl | Check |
|---|---|---|---|---|
| Brief parsing to JSON (`prompts/context_parser.md:6-22`), silent raw fallback (`backend/council.py:22-23`) | code + prompt | **I** — validated `DecisionBrief`; parse failure rejected and retried | `phases.py: FrameResponse, apply_frame` | `test_schema_rejection.py` |
| Selector picks ≤ 5 of 15 frameworks with rules (`selector.py:20-43`, `framework_selector.md:11-19`) | code + prompt | **A** — automatic or explicit lens selection; at least one lens challenges the lean | `lenses.py: select_lenses` | `test_ontology_and_lenses.py::test_lens_selection_by_stakes_and_reversibility` |
| Cross‑review letters in panel order, own analysis unmarked (`council.py:52-61`) | code | **I** — seeded shuffle by the controller on the isolated route; reviewer payload never contains the alias map | `engine.py: _alias_for` | `test_opencode_route.py::test_isolated_review_payload_withholds_authorship` |
| Random model per call, model not recorded (`council.py:33,66`) | code | **X** — per‑role routing; actual provider/model/substitution recorded per participant | `providers/opencode.py`, `engine.py: _apply_submission` | `test_opencode_route.py::test_opencode_route_records_identity_isolation_and_measured_tokens`, `::test_model_substitution_recorded` |
| Chairman dossier: option or "gather X", confidence + load‑bearing facts, kill criteria (`chairman.md:32-38`) | prompt | **A** — `Decision.kind`, `confidence{raise_if, lower_if}`, `reversal_conditions`, `next_action` | `report.py: build_decision` | `test_first_pass_and_report.py::test_decision_fields_and_report_sections` |
| Chairman hard‑codes seven frameworks (`chairman.md:1`, `:15-23`) | prompt | **X** — report is data‑driven | — | — |

**Map of the 15 catalogue entries** (`backend/config.py:21-127`) to engine lenses or equivalents (lens texts written fresh):

| Catalogue entry | Engine equivalent (`lenses.py` id) | Applies when |
|---|---|---|
| Pros & Cons | `balanced_ledger` | low stakes |
| Weighted Decision Matrix | **core judge** (criteria, normalised weights, scores, weight sensitivity) | always |
| Expected Value | `expected_value` | clear/complicated domain, stakes > low |
| 10/10/10 | `time_horizons` | values/emotional decisions (filler when more lenses needed) |
| Regret Minimization | `regret` | irreversible or personal/strategic |
| Type‑1 / Type‑2 Doors | brief field `reversibility` + `staging` | reversibility costly or one‑way |
| Pre‑Mortem / Inversion | `inversion` (also the leader challenge's method) | stakes ≥ medium |
| Second‑Order Thinking | `second_order` | competitive/market decisions |
| OODA Loop | `tempo` | time pressure (explicit selection) |
| Cynefin | brief field `domain` drives lens count and the information option | always framed |
| Kepner‑Tregoe | hard gates from stated constraints + weighted criteria | always |
| SWOT | `internal_external` | positioning/brand |
| Six Thinking Hats | `hats` bundle, observer‑only | exploratory topics (explicit selection) |
| Munger Latticework | `multidisciplinary` | novel/cross‑domain |
| WRAP | `widen_reality_test` (tripwires → `reversal_conditions`) | high stakes, narrow option set |

### 2.5 llm-council-main (MIT, Geoffrey Byers)

| Capability (evidence) | Class | Verdict | Impl | Check |
|---|---|---|---|---|
| First‑pass separation, five blind advisors in parallel (`agents/council-orchestrator.md:36-50`); relies on nested subagent spawning that the files never wire (`commands/council.md:6`) | prompt | **I** — generation is collected before any review by the controller; blindness is a recorded provider property, not an assumption | `engine.py: GENERATING → REVIEWING` | `test_engine_fixture_main.py::test_generation_precedes_review_and_shared_mode_recorded` |
| Lenses with anti‑theatre rules (`council-skeptic.md:43-44`, `council-opportunist.md:41-44`, `council-operator.md:44`) | prompt | **A** — `inversion`, `first_principles`, `asymmetric_upside`, `execution`, `outside_view` with "say so if nothing material" | `lenses.py` | `test_ontology_and_lenses.py::test_catalogue_covers_reference_methods` |
| Relevance weighting, "what did all five miss" (`council-chairman.md:31-40`) | prompt | **E** — reviewers report `shared_blind_spot` challenges (target `__all__`); weighting is by criteria | `phases.py: apply_review` | `test_engine_fixture_main.py::test_resolution_rules` |
| One concrete next step (`:47`, `:88`) | prompt | **A** — `Decision.next_action` mandatory | `report.py` | `test_first_pass_and_report.py` |
| Rebuttal round only sketched (`:148-153`) | prompt | **I** — `RESPONDING` phase with typed responses and controller resolution rules | `phases.py: apply_respond` | `test_engine_fixture_main.py::test_resolution_rules` |
| No persistence/export | — | **I** — event log, snapshot, `report.md`, `decision.json`, resume | `state.py` | `test_cancel_and_state.py::test_resume_from_snapshot_reproduces_identical_outcome` |
| "Test what later deliberation adds" | — | preset `first_pass` (frame → policy → generate → judge → report) for the Run 2 comparison | `config.py: PRESETS` | `test_first_pass_and_report.py::test_first_pass_preset_runs_generation_and_judging_only` |

### 2.6 neuralhats-main (MIT, Giorgi Kobaidze)

| Capability (evidence) | Class | Verdict | Impl | Check |
|---|---|---|---|---|
| Six hats, sequential, each hat sees prior hats (`backend/orchestrator.py:9-16`, `:134-145`, `:289-304`) | code | **E (adapted)** — `hats` bundle of six observer‑only lenses; outputs collected before review, no hat addresses another | `lenses.py: HATS_BUNDLE` | `test_ontology_and_lenses.py::test_explicit_and_hats_observer_only` |
| Facilitator rounds, `MAX_ROUNDS = 5`, CONTINUE/STOP parse **defaulting to CONTINUE** (`:17`, `:348-357`) | code | **X** (replaced) — continuation is a controller decision; unparseable model output never continues or stops a run | `engine.py: _decide_continue` | `test_engine_fixture_main.py::test_run_completes_with_recorded_stop_reason` |
| SSE progress events (`orchestrator.py:130-170`, `frontend/src/types/index.ts:33-39`) | code | **E** — `RunEvent` kinds (`phase_entered`, `request_issued`, `response_committed/rejected`, `incumbent_changed`, `challenge_opened/resolved`, `evidence_snapshot_changed`, `route_fallback`, `stop_decided`, …); `council status` | `ontology.py: EventKind`, `cli.py: status_text` | `test_cli_entrypoint.py::test_step_mode_end_to_end_through_cli` |
| SQLite persistence per turn (`database.py:24-58`, `orchestrator.py:144`) | code | **E** — JSONL per commit + snapshot; one run per directory; resume | `state.py` | `test_cancel_and_state.py` |
| Local Ollama execution (`ollama_client.py:58-74`) | code | **E (via OpenCode)** — local models reachable through OpenCode providers when configured | `providers/opencode.py` | — |
| Drift detection "whether vs how" (`orchestrator.py:227-233`) | prompt | **E** — reviewers may propose a `reframe`; the controller creates brief v+1 and reruns affected judgements (capped by `max_reframes`). Exercised by the Run 2 fixture `reframe_reinstate.json`. | `engine.py: _maybe_reframe` | `test_reframe_reinstate_tiebreak_jury.py::test_reframe_creates_brief_v2_with_lineage_and_copies_the_policy` (+2 more) |

---

## 3. Architecture

```
/council (project root)
├── .claude/skills/council/SKILL.md      chat entry point (/council …)
├── .claude/skills/council-settings/SKILL.md   settings entry point (/council-settings …)
├── council.config.json                  project defaults (layer 2)
├── .council/settings.json               saved settings (layer 3; written only by `council settings …`)
├── benchmarks/cases.json, run_campaign.py, results/   Run 2 benchmark spec, runner and published results
├── council_outcomes/<date-time>_<slug>/ one folder per run: index.html (dashboard), TITLE.txt, events.jsonl, state.json,
│                                        requests/, responses/, report.md, decision.json   (legacy: .council/runs/<run_id>/)
├── adapters/opencode/opencode.json      restricted OpenCode agent "council-member"
├── src/llm_council/
│   ├── ontology.py      protocol v1.0 records, enums, relations, role permissions, transitions
│   ├── config.py        CouncilConfig, layers, precedence, presets, provenance, enforcement table
│   ├── settings.py      saved‑settings layer: validated set/unset/reset, routes table, wizard plan
│   ├── lenses.py        lens catalogue + selection
│   ├── prompts.py       context block (phases, position, consumer, terms, tools, date, size), role instructions, guardrail
│   ├── discussion.py    discussion transcript, discussion payload (blind / summaries), documents, question-path detection
│   ├── trail.py         reasoning workflow reconstructed from the records
│   ├── phases.py        response models with field descriptions, payload builders, appliers (partial-accept review)
│   ├── judge.py         scoring contract, bounds, jury combination, promotion rule, sensitivity
│   ├── budget.py        measured/estimated usage, limits, finalisation reserve
│   ├── state.py         Store: validated commits, transactions, event log, snapshot, dedup, resume
│   ├── engine.py        state machine: Engine.step(submission) -> request | terminal
│   ├── report.py        RoundSummary, Decision, markdown report, chat summary
│   ├── dashboard.py     per-run index.html: state JSON + the inlined React bundle (static/dashboard.{js,css})
│   ├── ui.py            local web UI: works list, served dashboards, DELETE /runs/<id>/, settings editor (stdlib, 127.0.0.1)
│   ├── static/          built frontend (from web/ via `npm run build`), committed
│   ├── providers/       base.py, fixture.py, opencode.py, driver.py
│   └── cli.py           council start|submit|next|run|status|report|rereport|cancel|runs|dashboard|ui|config show|settings …
├── web/                 React interface source: Vite + Tailwind 4 + Radix primitives (shadcn style); kind.js = verdict palette
└── tests/               130 deterministic tests; fixtures built by tests/fixtures/build_fixtures.py
```

**Control flow.** `Engine.step(submission)` applies one submission to the pending request (validate → commit atomically → advance) and then runs controller‑only transitions until a new request is needed or a terminal state is reached. A **driver** obtains responses:

- `drive_until_chat_or_terminal` loops while requests are routed to `fixture` or `opencode` providers and returns as soon as a request is routed to `chat`, or at a terminal state. In autonomous mode (`council run --fixture …`) it runs the whole deliberation.
- Step mode (`council start` / `council submit`) persists the pending request to `requests/<id>.json`, prints it, and exits; the chat model answers by writing `responses/<id>.json` and running `submit`. This is how one user‑visible conversation hosts controller‑managed phase calls. Requests routed to OpenCode inside a step‑mode run are answered automatically by the driver during `submit`.

Both paths use the same `Engine`, `Store`, validators, prompts and payloads; only the responder differs.

**Isolation.** A provider declares `isolation ∈ {shared, isolated}`. Chat = `shared`; OpenCode = `isolated` (fresh session per call, restricted agent, minimal payload). On `isolated`, review and compare payloads pseudonymise options (`OPT-n`, seeded shuffle), omit lens, version and change reason, and the alias map stays controller‑side. On `shared`, no pseudonyms; prior rankings are still omitted from review payloads; the report states the limitation.

**Transactions, interruption, concurrency.** `Store.begin()/end()/rollback()` wrap each submission: events are buffered and only written on success; a rejected response leaves no trace other than its `response_rejected` event. Every request has a `dedup_key`; `council submit --request-id` on an already‑answered request returns the recorded outcome. Each run owns a directory; `Store.load` + `Engine.result()` resume from `state.json`. Cancellation is a `.cancel` file checked before every request.

---

## 4. State machine (as implemented in `engine.py`)

Terminal states: `COMPLETE`, `FAILED`, `CANCELLED`.

| State | Entry condition | Responder role | Validated output committed | Budget charge | Failure transition | Exit → |
|---|---|---|---|---|---|---|
| `INIT` | run created | controller | `run_created` event, effective config | 0 | — | `FRAMING` |
| `FRAMING` | no brief | `framer` | `DecisionBrief` v1 (+ user‑supplied `Evidence`) | 1 | invalid → retry (≤ `retries.max_attempts`) → `FAILED` | `POLICY` |
| `POLICY` | no policy for the brief version | `policy_setter` | `EvaluationPolicy` (gates, criteria, anchors, weights, scenarios; controller echoes materiality, margin, unverified policy, judge hash) | 1 | retry → `FAILED` | `BASELINE` |
| `BASELINE` | no round‑0 option | `strategist` (lens `direct`) | 1–2 `OptionVersion` (status quo, direct answer) with `generation_note` | 1 | retry → `FAILED` | `JUDGING` (round 0) |
| `GENERATING` | round 1 | `strategist` × selected lenses | ≤ 2 `OptionVersion` per lens with claims/assumptions/evidence; duplicates by title merged (status `merged`, lineage kept) | 1 per lens | invalid → retry → lens skipped (event + unfinished check); < 2 candidates → `FAILED` | `REVIEWING` |
| `REVIEWING` | `review.panel_size` > 0 | `reviewer` × panel | `Challenge[]` (target, mechanism, severity, class, could_change, evidence, resolution condition, requires_verification, scope), `Evidence[]`, `Dissent[]`, optional `reframe` | 1 per reviewer | retry → reviewer skipped | `VERIFYING` if an open challenge needs verification and budget remains, else `RESPONDING` |
| `VERIFYING` | open challenge `requires_verification` not yet attempted, `verification_calls < max` | `verifier` | `Evidence[]` (verified / disputed / unavailable) linked to the challenge | 1 per challenge | failure → controller commits `Evidence{unavailable}` | `RESPONDING` |
| `RESPONDING` | a candidate version has open targeted challenges | `strategist` (owner) | `Response[]` (rebut / concede / revise(+ new version) / request_verification / withdraw / reinstate) | 1 per targeted version | retry → challenges stay open | `REVISING` |
| `REVISING` | always | controller | (revisions were committed with the responses) | 0 | — | `JUDGING` |
| `JUDGING` | a candidate (active latest versions ∪ incumbent) lacks a judgement under the **current comparison key** | `judge` × `jury_size` | `Judgement` (gates, per‑criterion scores with confidence and evidence/assumption refs, optional scenario scores); controller computes aggregate, bounds, eligibility, promotion, ranking, `RoundSummary`; close call → two `compare` requests (swapped order) | 1 per (version, judge); +2 for a tiebreak | retry → `Judgement{missing}` → `non_comparable`; budget → versions left unscored (event `rescore_required: skipped_budget`) | `_decide_continue` → `GENERATING` (after round 0), `REVIEWING` (next round), `CHALLENGING`, or `REPORTING` |
| `CHALLENGING` | stop reason pending, leader exists, `leader_challenges < max`, ≥ 2 calls remain (reserve may be used) | `challenger`, then `strategist` (leader owner) | `LeaderChallenge` + mirror `Challenge{critical}` on the leader; owner `Response` | 2 | retry → skipped (unfinished check) | reopen → `REVIEWING` (round+1) iff unresolved ∧ `could_alter_outcome` ∧ `reopens < max` ∧ `round < max_rounds` ∧ affordable; else `REPORTING` |
| `REPORTING` | stop reason set | controller | `Decision`, `report.md`, `decision.json` | 0 | — | `COMPLETE` (or `CANCELLED`) |

**`_decide_continue` (after each round's judging), in order:** budget limit hit (`budget_calls`, `budget_tokens`, `budget_time`, `budget_cost`) → `stable` (round ≥ `min_rounds`, `stable_streak ≥ stable_rounds_required`, no blocking challenge) → `no_productive_follow_up` (round ≥ `min_rounds`, last round unproductive, no blocking challenge) → `max_rounds` → `budget_calls` if the next round (panel + 1 call) is unaffordable → otherwise next round. Round 0 goes to `GENERATING`, or to `REPORTING` with `trivial_question` when the brief says so.

**Blocking challenge** = open, `could_change ∈ {ranking, action}`, targets a current candidate (not `__all__`), and has a credible path: not requiring verification, or verification not yet attempted with budget left, or attempted with qualifying evidence attached. A challenge whose only path is verification that returned `unavailable` does not block stability but is reported.

**Stable streak** increments when the round is comparable, `|delta_vs_prior_incumbent| < materiality` and no blocking challenge exists; otherwise it resets.

**Loops.** Outer rounds 1..`max_rounds`; inner challenge/response once per round (`challenge_cycles_max` reserved); verification bounded by `max_verification_calls`; reopen bounded by `max_reopens`; reframes by `max_reframes`. Finalisation reserve: `finalisation_reserve_calls` are never used for deliberation; the leader challenge may use two of them.

---

## 5. Roles and authority (`ontology.py: ROLE_PERMISSIONS`)

| Role | May author | Never |
|---|---|---|
| `controller` | any record; state transitions; aggregates, rankings, promotions, stop reasons, `RoundSummary`, `Decision` | model content |
| `framer` | `DecisionBrief`, `Evidence` (user facts), `Assumption` | options, judgements |
| `policy_setter` | `EvaluationPolicy` | changes after round 0 (a reframe copies the policy under a new brief version) |
| `strategist` | `OptionVersion`, `Claim`, `Assumption`, `Evidence`, `Response` (only to challenges open on its own option) | judgements, challenges, transitions |
| `reviewer` | `Challenge`, `Evidence`, `Dissent` | revisions, judgements |
| `verifier` | `Evidence` | anything else |
| `judge` | `Judgement` (scores, gates), `PairwiseComparison` | aggregate, ranking, promotion |
| `challenger` | `LeaderChallenge` (+ its mirror `Challenge`), `Dissent` | revisions |
| user | start, cancel, config overrides | mid‑run content |

`Store.commit` rejects a record whose author role is not allowed for its type, whose references do not exist, or whose id duplicates an existing one; `Store.set_state` rejects transitions outside `TRANSITIONS`. Rejections happen before any mutation; a whole submission is one transaction.

---

## 6. Ontology — protocol v1.0 (`ontology.py`)

All records carry `id` (type prefix: `brief_`, `pol_`, `optv_`, `clm_`, `asm_`, `ev_`, `chl_`, `rsp_`, `jdg_`, `cmp_`, `dis_`, `lch_`, `rsm_`, `dec_`, events `evt_`), `protocol_version = "1.0"` (validated), `created_at`, `author_participant_id`, `author_role`. Unknown fields are rejected everywhere (`extra="forbid"`).

| Record | Key fields | Required links |
|---|---|---|
| `DecisionBrief` | `version`, `question_raw`, `decision_statement`, `objectives[]`, `stakeholders[]`, `hard_constraints[{text, source ∈ {user_stated, inferred}}]`, `preferences[]`, `time_horizon`, `stakes`, `reversibility`, `domain`, `evidence_gaps[]`, `interpretations[{text, implied_action}]`, `inferred_assumptions[]`, `decision_kind ∈ {decision, trivial, conditional_candidate}`, `supersedes_id?` | `supersedes_id` must exist |
| `EvaluationPolicy` | `brief_id`, `brief_version`, `rubric_version`, `criteria[Criterion{id, name, kind ∈ {gate, score}, weight, anchor_0/5/10}]`, `scenarios[Scenario{id, name, likelihood, priority}]`, `materiality_threshold`, `promotion_margin`, `unverified_gate_policy`, `judge_config_hash` | ≥ 1 score criterion with positive weight; unique ids |
| `OptionVersion` | `option_id`, `version`, `title`, `summary`, `mechanism`, `lens_id`, `parent_version_id?`, `merged_from[]`, `status ∈ {active, withdrawn, merged, reinstated}`, `change_reason`, `claim_ids[]`, `assumption_ids[]`, `generation_note{how, resources, missing_inputs}`, `round` | parent must exist; claims/assumptions committed in the same transaction |
| `Claim` | `text`, `option_version_id`, `kind ∈ {fact, inference, prediction}`, `evidence_ids[]` | version and evidence must exist (`supports` relations created) |
| `Assumption` | `text`, `option_version_id?`, `influential`, `if_false_effect` | — |
| `Evidence` | `statement`, `source{kind ∈ {user, document, url, model_knowledge, computation}, ref}`, `verification_status ∈ {user_supplied, verified, inferred, disputed, unavailable}`, `snapshot_id`, `challenge_id?`, `round` | commits of non‑`unavailable` evidence bump the evidence snapshot (`snap-n`) |
| `Challenge` | `target_ref` (version id, claim id or `__all__`), `mechanism`, `severity ∈ {minor, material, critical}`, `challenge_class ∈ {factual, evidentiary, value, scenario, execution}`, `could_change ∈ {none, eligibility, ranking, action}`, `evidence_ids[]`, `resolution_condition`, `requires_verification`, `scope ∈ {targeted, shared_blind_spot}`, `status ∈ {open, resolved, withdrawn, unresolved_final}`, `round`, `resolution_note`, `verification_attempted` | target must exist (`challenges` relation) |
| `Response` | `challenge_id`, `kind ∈ {rebut, concede, revise, request_verification, withdraw, reinstate}`, `text`, `evidence_ids[]`, `new_version_id?`, `round` | challenge open on that option (`addresses` relation) |
| `Judgement` | `option_version_id`, `comparison_key{brief_version, rubric_version, evidence_snapshot_id, judge_config_hash}`, `participant_id`, `gate_results[{criterion_id, outcome ∈ {pass, fail, unverified}, rationale, evidence_ids, assumption_ids}]`, `criterion_scores[{criterion_id, score 0–10, confidence, rationale, evidence_ids, assumption_ids}]` (each score must cite evidence **or** assumptions), `scenario_scores{}`, `status ∈ {complete, missing}`, `method`, `round`; controller‑filled `aggregate`, `lower_bound`, `upper_bound`, `eligible`, `penalties`, `unverified_gates`, `failed_gates` | must cover every gate and score criterion exactly once |
| `PairwiseComparison` | `first_version_id`, `second_version_id`, `preferred ∈ {first, second, tie}`, `rationale`, `comparison_key`, `round` | — |
| `Dissent` | `participant_id`, `position`, `against_ref`, `reason`, `what_you_lose`, `round` | ref must exist |
| `LeaderChallenge` | `leader_version_id`, `losing_scenario`, `strongest_alternative_version_id`, `distinguishing_evidence`, `could_alter_outcome`, `response_id?`, `status`, `related_challenge_ids[]` (first = mirror challenge), `round` | both versions must exist and differ |
| `RoundSummary` | `round`, `incumbent_version_id`, `prior_incumbent_version_id`, `challenger_version_id`, `promotion_outcome`, `delta_vs_parent`, `delta_vs_prior_incumbent`, `net_vs_round0` (each `Delta{value, comparable, note}`), `comparison_key`, `comparable`, `open_challenge_ids`, `open_critical_count`, `resolved_challenge_ids`, `new_version_ids`, `new_evidence_ids`, `dissent_ids`, `ranking`, `non_comparable_version_ids`, `budget`, `productive`, `stable_streak`, `note` | — |
| `RunEvent` | `kind`, `state_before`, `state_after`, `round`, `payload`, `dedup_key?` | — |
| `Decision` | `kind ∈ {firm, conditional, shortlist, information_request, no_eligible_option}`, `recommended_version_id?`, `alternatives[]`, `decisive_evidence_ids[]`, `material_dissent_ids[]`, `unresolved_challenge_ids[]`, `trade_offs[]`, `confidence{level, basis, raise_if, lower_if}`, `signals{evidence_quality, judge_agreement, ranking_robustness, ranking_flips, decisive_uncertainty}`, `stop_reason`, `unfinished_checks[]`, `next_action`, `reversal_conditions[]`, `round_history[]`, `limitations[]`, `failed_to_establish[]`, `completed_phases[]`, `budget` | all ids must exist |

**Relations** (`Relation{kind, from_id, to_id}`): `supports` (evidence → claim), `contradicts`, `challenges` (challenge → target), `addresses` (response → challenge), `supersedes` (version → parent; brief → previous brief; survivor → merged duplicate).

**Responses are drafts.** `phases.py` defines what each role may propose (`FrameResponse`, `PolicyResponse`, `BaselineResponse`, `GenerateResponse`, `ReviewResponse`, `VerifyResponse`, `RespondResponse`, `JudgeResponse`, `CompareResponse`, `LeaderChallengeResponse`, `ChallengeReplyResponse`). Drafts may carry their own ids (prefix‑checked, unique) so that a response can create evidence and cite it in the same message. The `Applier` resolves pseudonyms, validates every reference against the store plus the ids created in the same response, assigns ids, and commits inside one transaction.

**Controller resolution rules.** `rebut` resolves a challenge only when it cites `verified` or `user_supplied` evidence; `concede` keeps it open (noted); `revise` creates a new version and resolves the challenge for that version once judged (the challenged version keeps it open while it is still a candidate; once superseded and out of contention it closes as superseded); `withdraw` closes challenges on the option; a leader‑challenge reply follows the rebut rule. Evidence from a reply counts (the twin fixture adds a verified production calendar).

### 6.1 Worked example A — successful revision (schema‑valid, from the main fixture)

Response of the staging strategist (round 2) to `chl_c_measure`:
```json
{"responses": [{"challenge_id": "chl_c_measure", "kind": "revise",
  "text": "Adding a geo-holdout and weekly readouts so the scale gate fires on a clean signal.",
  "revision": {"id": "optv_C_v2", "title": "Staged 10% pilot with geo-holdout and weekly readouts",
    "summary": "Move 10% into short-form video in two test regions with matched holdout regions for six weeks; weekly readouts; scale to 30% only if incremental ROAS >= 1.2x.",
    "mechanism": "The holdout isolates incrementality from attribution noise.",
    "claims": [{"id": "clm_c3", "text": "Geo-holdout pilots at 10% share give a readable signal within six weeks", "kind": "fact", "evidence_ids": ["ev_bench"]}],
    "assumptions": [{"id": "asm_c2", "text": "Two matched region pairs exist", "influential": false}],
    "generation_note": {"how": "revision after chl_c_measure", "resources": "model only", "missing_inputs": []},
    "change_reason": "Addresses chl_c_measure with a holdout design"}}]}
```
Controller effects: `OptionVersion optv_C_v2` (version 2, `parent_version_id = optv_C_v1`), relation `supersedes(optv_C_v2 → optv_C_v1)`, `Response rsp_…` with relation `addresses(→ chl_c_measure)`, challenge note "revision proposed; resolves for the new version once judged". In the fixture the revision is then judged lower (7.1 vs 7.7) and **rejected as a regression**; `optv_C_v1` stays incumbent and the challenge stays open until the owner rebuts it with the verified benchmark in round 3.

### 6.2 Worked example B — unresolved objection that changes the final outcome

```json
{"losing_scenario": "January creative-production capacity is fully booked, so the pilot cannot launch before week 6 and no readout exists before the Q1 budget lock.",
 "strongest_alternative_version_id": "optv_A_v1",
 "distinguishing_evidence": "Confirmed creative-production capacity for January (production calendar)",
 "could_alter_outcome": true, "related_challenge_ids": ["chl_shared_capacity"]}
```
Owner reply: `{"kind": "rebut", "text": "Capacity is likely available but no plan could be found.", "evidence_ids": ["ev_cap_unknown"]}` — `ev_cap_unknown` is `unavailable`, so the challenge is **not** resolved. `max_rounds` is reached, so no reopen; `LeaderChallenge lch_0001` and its mirror `chl_0001` become `unresolved_final`. The decision record (`.council/runs/sample_main_fixture/decision.json`) has `kind = conditional`, `unresolved_challenge_ids ∋ chl_0001`, `signals.decisive_uncertainty = ["lch_0001: Confirmed creative-production capacity …"]`, `next_action = "Resolve the decisive uncertainty first: …"`, `reversal_conditions ∋ "If: January … -> prefer optv_A_v1"`. The twin fixture replies with a verified production‑calendar evidence record and yields `kind = firm`, confidence `high` (`tests/test_engine_fixture_main.py::test_unresolved_challenge_changes_final_action`).

---

## 7. Global judge — comparable across rounds (`judge.py`)

**Scoring contract** (registered in `EvaluationPolicy` before round 0; `judge_config_hash` = hash of the `judge` config section):

- Gates: `pass | fail | unverified`. `fail` → ineligible (excluded from ranking, kept visible). `unverified` → `unverified_gate_policy ∈ {fail, penalty, flag}` (default `penalty`: subtract `unverified_gate_penalty` = 1.0 per unverified gate from the aggregate, subtract twice that from the lower bound; always listed in `unverified_gates`).
- Criterion scores: integers 0–10 against anchors; weights normalised to sum 1 by the controller.
- Aggregate `S = Σ wᵢ·sᵢ − penalties`, clamped to [0, 10].
- Bounds (labelled **heuristic**, `judge.half_widths`): `h = {high: 0.5, medium: 1.0, low: 1.5}`; `S_low = Σ wᵢ·max(0, sᵢ − hᵢ) − 2·penalties`, `S_high = Σ wᵢ·min(10, sᵢ + hᵢ) − penalties`. With a jury, per‑criterion mean score and `hᵢ = max(h(confidence), spread/2)`; a judge who fails a gate makes the option ineligible; `spread` (mean normalised disagreement) is the judge‑agreement signal.
- Missing data: `Judgement{status = missing}` or no judgement under the key → `Combined.status = missing`; any comparison needing it is `non_comparable`. Nothing is imputed.
- Each criterion score must cite ≥ 1 evidence id or ≥ 1 assumption id; a judgement must cover every gate and score criterion exactly once (else rejected → retry).

**Comparability.** Judgements are keyed by `(brief_version, rubric_version, evidence_snapshot_id, judge_config_hash)`. Promotion compares incumbent and challenger only under identical keys. When evidence is committed, the snapshot id changes and `_judge_queue` rescored every candidate under the new key (default `rescore_scope = all_active`; `incumbent_and_new` limits it). If rescoring cannot be afforded, the versions are listed in `unfinished_checks`, a `rescore_required: skipped_budget` event is written, and the round outcome is `non_comparable` with the earlier result preserved.

**Shown per round** (`RoundSummary`, report table): `delta_vs_parent` (challenger vs its parent under the same key), `delta_vs_prior_incumbent` (round winner vs prior incumbent under the same key), `net_vs_round0` (winner vs the round‑0 incumbent under the same key); each carries `comparable` and a note (e.g. "non‑comparable: judged under different keys; earlier result preserved").

**Promotion rule** (`promotion()`): eligible challenger with `S_low > incumbent.S_high + promotion_margin` → `promoted`; `|Δ| < materiality` → `retained_tie`; `Δ ≤ −materiality` → `retained_loss`; `Δ ≥ materiality` with overlapping bounds → `inconclusive`, unless a counterbalanced pairwise tiebreak was run: both passes prefer the challenger → `promoted`; both prefer the incumbent or both tie → `retained_tie`; disagreement → `inconclusive`. Incumbent failing a gate → `incumbent_ineligible` (best eligible becomes incumbent). No eligible challenger → `no_challenger`. Mixed keys → `non_comparable`.

**Bias controls.** Attribute scores precede any overall statement (no model‑written aggregate). Authorship and prior rankings are withheld only on isolated providers; prior rankings are omitted from review payloads on both. Close comparisons trigger two `compare` requests with swapped candidate order. Judge disagreement is measured as spread. Cyclic preferences among ≥ 3 options cannot arise in this design because only the incumbent/top‑challenger pair is compared pairwise; the bounded top‑k pairwise round was not added in Run 2 (`judge.screen_above`/`finalists` stay inert); if it is added later, cycles must be reported as `ranking_robustness = cyclic`. Log‑probability scoring: optional method, unavailable on both routes today; `method = structured_scores` is recorded on every judgement.

**Sensitivity** (`sensitivity()`, no model calls): each criterion weight ±`weight_perturbation` (20 %) one at a time with renormalisation; ranking per scenario when scenario scores exist. Flips are listed with the perturbation; `ranking_robustness = 1 − flips/perturbations`. Signals reported separately in `Decision.signals`: `evidence_quality` (share of cited evidence that is verified or user‑supplied), `judge_agreement` (None with a single judge, stated), `ranking_robustness`, `decisive_uncertainty` (blocking challenges and unresolved leader challenges with the evidence that would settle them). Confidence level: `high` if (firm/information outcome with a clear last round) ∧ no open critical objection ∧ robustness ≥ 0.8; `medium` if exactly one fails; `low` otherwise; `raise_if`/`lower_if` list the distinguishing evidence, losing scenarios and ranking flips.

**Stopping is testable.** `stable_rounds_required` (2) consecutive comparable rounds with `|delta_vs_prior_incumbent| < materiality` and no blocking challenge ⇒ `stable`. Unproductive round (no new versions, no new evidence, no resolutions, no promotion) with no blocking challenge ⇒ `no_productive_follow_up`. Budget stops record the limit and the outstanding checks (`tests/test_budget.py`).

### 7.1 Worked examples (numbers from `tests/fixtures/main_run.json`; criteria weights 4/3/2/1 → 0.4/0.3/0.2/0.1)

**Genuine promotion (round 1).** Round‑0 incumbent A "keep budget in search": 3/8/9/6 → S = 6.00, bounds [5.25, 6.75]. Challenger C v1 "staged 10 % pilot": 7/8/8/6 at high confidence → S = 7.40, bounds [6.85, 7.95]. 6.85 > 6.75 ⇒ **promoted**; `delta_vs_prior_incumbent = +1.40`, `net_vs_round0 = +1.40`.

**Apparent improvement caused by new evidence (round 2).** The verifier commits `ev_bench` (verified) → snapshot `snap-3`. C v1 rescored under `snap-3`: 7/9/8/6 → S = 7.70 (+0.30 purely from evidence). C v2 (revision) judged under `snap-3`: 7/9/5/6 → S = 7.10. Comparing C v2 (snap‑3) with C v1's old 7.40 (snap‑2) is refused (`non_comparable`, test asserts it). Matched: `delta_vs_parent = 7.10 − 7.70 = −0.60` ⇒ **retained_loss** (rejected regression). Without the rescore the revision would have looked like −0.30.

**Inconclusive comparison** (`test_judge.py`): incumbent 6/6 at high confidence → 6.00 [5.50, 6.50]; challenger 7/6 at low confidence → 6.75 [5.25, 8.25]: Δ = +0.75 ≥ materiality but bounds overlap ⇒ `inconclusive`; with swapped‑order pairwise verdicts that disagree it stays `inconclusive`; if both prefer the challenger it is `promoted`.

**Unverified gate kept visible.** B "shift 30 %" has gate `unverified` → aggregate 5.6 − 1.0 = 4.6, `unverified_gates = [crit_gate_budget]`, still eligible under `penalty`; its owner later withdraws it after a critical challenge.

---

## 8. Chat integration (default mode)

`/council <question> [--preset quick|standard|deep|first_pass] [--opencode] [--lenses a,b,c] [--set key=value]`

The skill (`.claude/skills/council/SKILL.md`) tells the chat model to run `.venv/bin/council start --args-file <file> --ui` (which also opens the run's dashboard, §17), answer **only** the printed request in the named role by writing one JSON object to the printed response path, run the printed `.venv/bin/council submit <run_id> <path> --request-id …`, and repeat until `=== RUN COMPLETE … ===`, then show the summary, `report.md` and the `decision.json` path. Rejections are printed as `NOTE: submission … was rejected: <error>` with the retried request following.

In this mode every role is served by one model in one visible conversation. The decision record states: "Shared context: all roles served through one conversation; pseudonymisation was not applied because it would not withhold information; no blind review is claimed." Measured: model calls, elapsed time. Estimated: tokens (`len/4`, labelled). Unavailable: cost.

`council status <run_id>` prints state, round, incumbent and its change history, open critical objections, open challenges, stable streak, budget (measured/estimated/unavailable labels), completed phases, unfinished checks and the pending request.

**Host constraints identified.** Claude Code can run shell commands and persist files, so controller‑managed calls and persistence are available; it cannot let the Python controller call the chat model directly, which the step protocol closes. Nested subagent spawning is not relied on. Skill discovery from a fresh session started in `council/` was confirmed live in Run 2 (§16.3), including unattended operation under the skills' `allowed-tools` (no permission denials in headless `claude -p` runs). The skill must pass `--run-id`, `--preset`, `--opencode`, `--lenses` and `--set` through the args file verbatim; the controller splits flags from the question.

---

## 9. Configuration contract and precedence (`config.py`)

```
protocol_version: "1.0"
routing:
  default_provider: chat | opencode | fixture            (chat)
  roles.{framer,policy_setter,strategist,reviewer,verifier,judge,challenger}: {provider?, model?, temperature?, top_p?}
  opencode: {enabled: false, binary: "opencode", agent: "council-member", config_dir: "adapters/opencode",
             timeout_seconds: 300 (project; built‑in default 300, range 5–3600), retries: 1, fallback: chat|fixture|fail,
             default_model?, model_fallbacks: {}, verify_version: true, discover_models: true, standalone: true}
judge:   {jury_size: 1, method: structured_scores, half_widths: {high: .5, medium: 1, low: 1.5}, half_width_label: heuristic,
          promotion_margin: 0, materiality_threshold: .5, unverified_gate_policy: penalty, unverified_gate_penalty: 1,
          pairwise_tiebreak: true, screen_above: 6, finalists: 3 (both inert: validated, read nowhere), weight_perturbation: .2, rescore_scope: all_active}
lenses:  {selection: auto|explicit, explicit: [], min: 3, max: 5, always_include_status_quo, always_include_staged, always_include_information_option}
review:  {panel_size: 2, challenge_cycles_max: 1}
limits:  {min_rounds: 2, max_rounds: 4, stable_rounds_required: 2, max_model_calls: 60 (project; 40 in the Run 1 handoff),
          max_tokens_estimate: 400000, max_elapsed_seconds: 1800, max_cost_usd: null, finalisation_reserve_calls: 3,
          max_reframes: 1, max_reopens: 1, max_verification_calls: 3, max_leader_challenges: 1}
policy:  {weight_overrides: {}}        # Run 2: rubric weights — {"criterion name or crit_id": weight > 0}, applied when the
                                        # policy is registered (matched by id or slugged name, score criteria only), then
                                        # normalised; applied/unapplied keys recorded on the EvaluationPolicy and as a
                                        # `policy_weights_overridden` event
retries: {max_attempts: 2}
report:  {narrative_model_call: false}
fixture_path?, seed: 7
```

All fields are range‑validated; unknown keys and unknown roles are rejected; `min_rounds ≤ max_rounds`, `finalisation_reserve_calls < max_model_calls`, `lenses.min ≤ lenses.max`.

**Precedence (lowest → highest):** built‑in defaults → project `council.config.json` → saved `.council/settings.json` → preset (`--preset quick|standard|deep|first_pass`) → per‑run overrides (`--set a.b=c` with JSON values, `--opencode`, `--provider`, `--fixture`, `--lenses`). The effective configuration and per‑key provenance (`defaults`, `project`, `saved`, `preset:<name>`, `override`) are stored in the run's `state.json` and printed by `council config show [--run-id id]`, together with enabled external routes and an enforcement table (calls counted; elapsed measured; tokens measured on OpenCode, estimated on chat; cost measured only when a provider reports it, otherwise unavailable and not enforceable). Sampling parameters are accepted per role; the chat route cannot apply them (`Participant.sampling_supported = false`).

---

## 10. OpenCode adapter contract (`providers/opencode.py`)

Verified on this machine on 2026‑11‑24 (real infrastructure, recorded separately from fixtures):

- `opencode v2.3.2` at `/Users/massimo/.opencode/bin/opencode`; `opencode models` lists 79 models (providers seen: `claude-agent`, `google`, `muse-code`, `openai`, …). Credentials are held by OpenCode (`opencode auth list`); the adapter never reads or passes them.
- `opencode run --format json` emits NDJSON events `step_start`, `text` (`part.text`), `step_finish` (`reason`, `cost`, `tokens{input, output, reasoning, cache{read, write}}`) or `error` (`error.type` e.g. `provider.no-route`, `provider.quota` with `status: 402`; `error.message`). Exit code 1 on an error event, 0 on success. Recorded payloads: `tests/fixtures/opencode/*.jsonl`.
- The default agent loads ≈ 36 k tokens of system context (cache write 35 888 for a one‑word reply). `adapters/opencode/opencode.json` defines agent `council-member` (`mode: primary`, deliberation‑only system prompt, `permissions: [{action: "*", resource: "*", effect: "deny"}]`): ≈ 3.7 k tokens and no tools. `steps: 1` must not be set (it injected a "maximum steps reached" artefact).
- **Project resolution:** OpenCode resolves the project (and therefore the project `opencode.json`) from the `PWD` environment variable, not from the process working directory, and the background service resolves it to the enclosing project root (the council folder), where the agent is not defined. The adapter therefore runs each call with `--standalone` and `PWD=<config_dir>` (`OpenCodeConfig.standalone`, `_run`). The `OPENCODE_CONFIG` environment variable did not override this.
- Model identity: `opencode session export <sessionID>` returns `.info.model = {id, providerID, variant}`; the id is the requested alias (`haiku`), so identity is recorded as "requested + reported by OpenCode; alias unresolved".
- `cost: 0` on the subscription provider means **unavailable**. Google provider returned HTTP 402 (prepayment depleted) — recorded as `error_quota_402.jsonl`.
- **Live adapter call (one judge request from the sample run, `claude-agent/haiku`, restricted agent):** success in 16.5 s, `isolation = isolated`, tokens measured 10 501 (input 2, output 851, reasoning 1 964, cache read 3 164, cache write 4 520), cost unavailable, `model_reported = claude-agent/haiku`, session id recorded. The reply was well‑formed JSON that scored every gate and criterion with rationale and references; it initially failed validation because it cited an assumption on a gate result, so the contract now allows `GateResult.assumption_ids` (validated against the store). This was a one‑off interface check, not a council run: live runs are Run 2 scope.

Adapter behaviour:
1. Off unless `routing.opencode.enabled` or `--opencode`; when disabled the binary is never resolved or spawned (`test_disabled_opencode_never_spawns_binary` with a marker‑writing fake binary).
2. Preflight once per run: `--version` (must be v2.x) and `models` (discovery). A requested model not listed is substituted via `model_fallbacks`, else `default_model`, with a `route_substitution` event and `Participant.substitution`.
3. Per call: `opencode run --format json --archived --title "council <run_id> <request_id>" --agent council-member --standalone --model <provider/model> <prompt>` with `cwd = PWD = adapters/opencode`. Prompt = role instructions + payload (data) + response schema; no configuration, no credentials.
4. Events parsed; an `error` event, non‑zero exit or timeout → retry up to `retries`, then `route_fallback` event and fallback to `fallback` provider (`chat` by default: the request is re‑routed to the chat model in step mode; `fixture` in tests; `fail` fails the request).
5. The text is validated against the request's response model before anything is committed (same path as every provider); invalid → retry/failure handling of the engine.
6. Recorded per participant: provider, `model_requested`, `model_reported`, `substitution`, `isolation = isolated`; measured tokens; cost `unavailable` unless reported > 0.
7. Partial results: a response is committed atomically or not at all.

---

## 11. Verification (deterministic) — `python -m pytest` → 58 passed at the Run 1 handoff, 98 at the Run 2 delivery, 102 after the first §17 items, 130 on 2026‑11‑25 (§16.1 lists the Run 2 tests)

Fixture provider (`providers/fixture.py`): entries match request **content** (`kind`, `role`, `round`, `lens`, `version_id`, `snapshot`, `challenge_id`, `reviewer`, `judge`, `slot`, `attempt`), never call order; an unmatched request fails the run; unconsumed `once` entries fail the run (`finish()`); `raw` entries exercise schema rejection. Fixtures are generated by `tests/fixtures/build_fixtures.py` (regenerated at test start).

| Check | Fixture / test | What the controller computed |
|---|---|---|
| **Handoff gate: end‑to‑end through the entry point, OpenCode disabled** | `main_run.json`; `test_engine_fixture_main.py` (API) and `test_cli_entrypoint.py::test_step_mode_end_to_end_through_cli` (the skill's exact `council start` / `council submit` loop via subprocess, fixture standing in for the chat model) | 5 round summaries (rounds 0–4); promotion in round 1 (+1.40, matched); regression rejected in round 2 (C v2 −0.60 vs parent under `snap-3`); C v1 and A rescored under `snap-3`, mixed‑key comparison refused; leader challenge unresolved → `conditional` citing `chl_0001`/`lch_0001`; twin `main_run_resolved.json` → `firm`; stop reason `stable` (streak 2, no blocking); 32 calls; shared‑context limitation recorded; dissent and withdrawn option survive |
| Schema rejection and retries | `schema_rejection.json`, `retries_exhausted.json`; `test_schema_rejection.py` | malformed frame and unparseable policy rejected with `response_rejected` events, retried with attempt 2, rejected submissions still charged; after `max_attempts` → `FAILED` with reason; no records created from failures |
| Budget exhaustion and reserve | `test_budget.py` | `budget_calls` stop; unscored versions explicit (`rescore_required: skipped_budget`); partial report lists completed phases and outstanding checks; leader challenge runs from the reserve |
| Cancellation | `test_cancel_and_state.py::test_cancellation_mid_run_produces_partial_report` | `.cancel` → `CANCELLED` with decision and `unfinished_checks` |
| Resume and dedup | `test_cancel_and_state.py` | reload from `state.json` reproduces the identical pending request and final decision; duplicate submission rejected without mutation; `council submit --request-id` idempotent |
| Config precedence and overrides | `test_config.py`, `test_cli_entrypoint.py::test_config_show_prints_provenance_and_enforcement` | defaults < project < saved < preset < override with provenance; invalid values rejected; presets valid |
| OpenCode route and fallback | fake `opencode` binary replaying the recorded real payloads; `test_opencode_route.py` | identity, isolation and measured tokens recorded; pseudonymised review payload without authorship, alias map controller‑side; quota error → retry → `route_fallback`; disabled → binary never spawned; model substitution recorded |
| Judge rules | `test_judge.py` | aggregate/bounds/normalisation; gate fail/unverified; coverage and citation requirements; no model aggregate; all promotion outcomes; mixed keys and missing → non‑comparable; swapped‑order tiebreak; jury widening; sensitivity flips; method recorded |
| Ontology, store, lenses, prompts | `test_ontology_and_lenses.py` | unknown refs, unauthorised roles, bad transitions rejected before mutation; transaction rollback; lineage relation; lens selection; hats observer‑only; guardrail everywhere |
| First‑pass preset and report | `test_first_pass_and_report.py` | frame → policy → generate → judge → report only (11 calls); report sections and decision fields |
| Discussion transcript and documents | `test_discussion_documents.py` | every contribution written in order and fed to later roles; cap shortens then drops oldest first; rejected replies in the transcript but not fed; `--docs` → evidence, excerpts in every request, INDEX.md |
| Dashboard, UI server, settings page | `test_dashboard_ui.py` | state JSON for the React app, home state, `/`, `/runs/<id>/`, `/settings` (tabs, defaults panel, validated writes), port handling, Markdown modal map |
| Validation fallbacks | `test_schema_rejection.py` (2026‑11‑25 tests) | after `retries.max_attempts` the request goes to each `routing.validation_fallbacks` model once; `route_fallback {reason: validation}`; exhausted fallbacks still fail |
| Prompt contract | `test_prompt_context.py` | context block and capabilities on every request; `valid_target_ids`; judges without ranking numbers, summaries only; `see_payload`; schema descriptions and `builds_on`; JSON repair; retry with `previous_reply`; partial review commit with notes; blind discussion; question paths → documents; follow‑up prompt in report and state |

Not fixture‑tested in Run 1, covered in Run 2 by `tests/test_reframe_reinstate_tiebreak_jury.py` (9 tests, §16.6): reframe (`Engine._maybe_reframe`), `reinstate` responses, pairwise tiebreak inside an engine run, jury > 1 inside an engine run.

---

## 12. Operations

`council status` shows phase, round, incumbent changes, open critical objections, open challenges, stable streak, budget with labels, completed phases, unfinished checks and the pending request. The run's `index.html` dashboard shows the same plus the verdict card, the stat strip, the rounds table with the decision taken per round, objections, settings with provenance, the request/response log, the files and the follow‑up prompt; `council ui` serves every run as a list of work buttons with a delete action per work (§17). Partial results always list completed phases and outstanding checks. Logs, requests and reports never contain credentials or provider configuration beyond provider name and model id.

Day‑to‑day commands (from `council/`): `python -m pytest` (130 tests, no model calls); `cd web && npm run build` after editing `web/src` (the bundle in `src/llm_council/static/` is what pages inline); the UI server is restarted with `lsof -ti tcp:8771 | xargs kill` followed by `/council … --ui` or `.venv/bin/council ui`; JS/CSS changes need a rebuild, Python changes need a server restart.

---

## 13. Benchmark design, resource limits and Run 2 acceptance criteria

**Case sets** (delivered as `benchmarks/cases.json`, run by `benchmarks/run_campaign.py`; results in §16.5): objective cases with known outcomes (dominant option by EV; a constraint‑violating option that must fail a gate); open‑ended marketing decisions with independent assessment criteria (budget reallocation, channel entry, pricing test, campaign kill/continue); failure‑mode cases — misframing, conflicting values, missing evidence, false consensus (shared wrong premise), hard‑gate failure, evidence change mid‑run, regression, close ranking, justified deferral; straightforward cases to measure deliberation overhead (calls, tokens, time vs a single pass).

**Matched inputs:** same question text, evidence pack, candidate pool (fixed candidates for verifier‑only comparisons), model/provider and call budget. Independent evaluator (different model or human rubric), output identity blinded where practical.

**Primary quality measures (fixed now):** (1) correct option on objective cases; (2) independent rubric score 0–10 on open cases (defensibility, completeness of trade‑offs, actionability); (3) planted failure‑mode detection rate. **Secondary:** calls, measured tokens, elapsed time, variability over 3 seeds, mismatches.

**Superiority hypotheses (to verify per reference, per task class):** vs llm‑council first pass (`--preset first_pass` vs `standard`): ≥ 1.0 rubric point and ≥ 2 more planted failures caught on open cases; vs council‑review: equal or better detection with fewer calls at `quick`; vs council‑master: no false consensus on false‑consensus cases; vs Council‑Decide: better handling of questions without explicit options; vs neuralhats: fewer calls for equal rubric; vs llm‑as‑a‑verifier (fixed candidates): pairwise selection accuracy within 5 pp without logprobs, or report the gap. Incremental contribution of incumbent tracking, targeted follow‑up and the leader challenge on a small matched set if budget permits; one‑model vs OpenCode runs where the route can be exercised.

**Resource limits for Run 2 campaigns:** per run ≤ 40 calls, ≤ 400 k estimated tokens, ≤ 30 min; per campaign ≤ 60 runs; stop at the first provider quota error and record it. Preflight each reference (dependencies, providers, credentials, cost); status per reference ∈ {completed live comparison, blocked by dependencies/credentials, deferred under budget}. Known now: Google provider quota depleted (402); `claude-agent` subscription provider works through OpenCode; llm‑as‑a‑verifier needs a logprob backend not available here; Council‑Decide needs an OpenRouter key and Typst; neuralhats needs Ollama + Gemma.

**Run 2 acceptance criteria:** (1) Run 1 checks rerun green (`uv run pytest`); (2) settings interface writes `.council/settings.json`, validates against `CouncilConfig`, shows effective config with provenance, enabled routes and enforcement modes; (3) live `/council` run in Claude Code with OpenCode disabled, transcript saved, skill discovery confirmed; (4) opt‑in OpenCode route exercised live in a council run with ≥ 1 participant on another provider, identity/isolation recorded, fallback demonstrated; (5) benchmark results under `benchmarks/results/` with wins/ties/losses, variability, measured usage, mismatches and explicit status for all six references; (6) reframe, reinstate, engine‑level pairwise tiebreak and jury > 1 covered by fixtures; (7) this document updated.

---

## 14. Run 1 handoff (recorded 2026‑11‑24)

**Project root and chat surface.** Root `/Users/massimo/Projects_Massimo/strategy-tribunal` (repository `github.com/mbuon/strategy-tribunal`). Chat surface: Claude Code 2.1.331; entry point `/council` = `.claude/skills/council/SKILL.md` driving the `council` CLI in step mode.

**Run and test commands** (from the root; quote the path):
```
uv sync                                   # Python 3.12+, pydantic 2, pytest (uv-managed .venv)
uv run pytest                             # 58 passed
uv run council start "<question>" [--preset quick|standard|deep|first_pass] [--opencode] [--lenses a,b] [--set key=value]
uv run council submit <run_id> <response.json> [--request-id req_xxxx]
uv run council next|status|report|cancel <run_id> ; uv run council runs
uv run council config show [--preset …] [--set …] [--opencode] [--run-id <id>]
uv run council run "Should we shift 30% of our Q1 paid-search budget into short-form video?" \
   --fixture tests/fixtures/main_run.json --lenses staging,information_option,asymmetric_upside --run-id sample
python tests/fixtures/build_fixtures.py   # regenerate fixtures
```
Sample runs kept: `.council/runs/sample_main_fixture` (conditional, stable, 32 calls, confidence low) and `.council/runs/sample_resolved_fixture` (firm, stable, 32 calls, confidence high; notes that the reply's evidence changed the snapshot after final judging without a rescore).

**Resolved architectural decisions.** Controller/responder split with a resumable step engine; shared‑context default without pseudonyms; isolation as a provider property; per‑response transactions; content‑matched fixtures; comparison keys with mandatory rescoring on evidence change; promotion by conservative bounds with counterbalanced pairwise tiebreak; controller‑computed reports (no narrative model call); OpenCode via standalone subprocess with `PWD` set to the adapter directory and a tools‑denied agent.

**Configuration schema and override contract.** §9; file `council.config.json`; `--set` JSON overrides; provenance per key; `council config show`.

**Adapter contract.** §10; fixtures `tests/fixtures/opencode/`; fake binary in `tests/test_opencode_route.py`.

**Test outcomes.** 58/58 deterministic tests pass (`uv run pytest`, ~25 s). Gate fixture: 4 deliberation rounds, promotion, rejected regression, matched rescore, unresolved leader challenge → conditional (twin → firm), stop reason `stable`, 32/40 calls.

**Real infrastructure exercised (separately from fixtures):** OpenCode v2.3.2 probes — no‑route error, Google quota 402, default‑agent cost (35 888 cache‑write tokens), restricted agent (≈ 3.7 k), `PWD`/standalone project resolution, `session export` identity; one live judge request through the adapter with `claude-agent/haiku` (valid structured scores after the gate‑assumption contract fix). No live council run and no live `/council` invocation were performed in Run 1.

**Open dependencies / blockers for Run 2.** Google provider credits depleted (402); logprob scoring has no backend on either route; skill discovery from a fresh Claude Code session to be confirmed; benchmark references need their own dependencies (OpenRouter key + Typst, Ollama + Gemma, logprob backend); OpenCode standalone calls cost ~2 s startup each. No Run 1 gate failed.

**Changed/created files.** `docs/llm_council.md`, `README.md`, `pyproject.toml`, `.gitignore`, `council.config.json`, `adapters/opencode/opencode.json`, `.claude/skills/council/SKILL.md`, `src/llm_council/{__init__,ontology,config,lenses,prompts,phases,judge,budget,state,engine,report,cli}.py`, `src/llm_council/providers/{__init__,base,fixture,opencode,driver}.py`, `tests/conftest.py`, `tests/test_*.py` (10 files), `tests/fixtures/build_fixtures.py` + generated `*.json`, `tests/fixtures/opencode/*`. Reference directory `original/` untouched.

---

## 15. Licences

- council-master (MIT, Michael Dubell), council-review-main (MIT, Neal Meyer), llm-as-a-verifier-main (MIT), llm-council-main (MIT, Geoffrey Byers), neuralhats-main (MIT, Giorgi Kobaidze): no code or prompt text is copied into this engine; mechanisms are re‑implemented. Any future copied snippet must carry the copyright and permission notice.
- LLM-Council-Decide-master: **no licence file** → all rights reserved. Nothing copied; only public framework names are referenced in §2.4.

---

## 16. Run 2 delivery (recorded 2026‑11‑24, evening session)

Run 2 was executed in two sittings on the same day. An earlier sitting (same conversation, before a `/clear`) built the settings module and skill, the benchmark spec and runner, ran a live standard‑preset `/council` smoke (`live_smoke`, 45 calls), a first‑pass baseline (`live_first_pass`), an all‑OpenCode quick run (`live_opencode_quick`) and three benchmark campaigns while still fixing the engine (gate detection, baseline, per‑request budget enforcement). This section records the **final** state: the acceptance checks were rerun, the earlier campaigns are kept as superseded history, and every live result below was produced on the final engine code unless marked otherwise; the `report.py` next‑action ordering fix (16.5) landed after the live runs and the campaign, so all live‑run and benchmark decision records were rebuilt with `council rereport` (no model calls) and the quoted outcomes are from the rebuilt records. No git repository exists, so no worktree isolation was possible; all work happened in place.

### 16.1 Run 1 acceptance checks rerun

`uv run pytest` → **102 passed** (58 at the Run 1 handoff). No regression. Tests added in Run 2: `test_settings.py` (4: saved layer validation, refusal leaves the file untouched, unset/reset, every CLI subcommand), `test_policy_weights.py` (3: rubric weight overrides by name or id, untouched policy without overrides, config/settings validation), `test_benchmark_checks.py` (5: checkers cannot pass on field names, whole‑phrase title matching, campaign limits and primary measure, preset call cap is never raised, evaluator summary capped on whole lines), `tests/test_report_priority.py` (2: objection ordering), `tests/test_reframe_reinstate_tiebreak_jury.py` (9, see 16.6), plus the earlier‑sitting additions to `test_engine_fixture_main.py`, `test_budget.py` (token/time limits enforced before every request), `test_opencode_route.py`, `test_schema_rejection.py`, `test_first_pass_and_report.py`, `test_judge.py` and `test_cli_entrypoint.py`. Acceptance item (6) — fixtures for reframe, reinstate, engine‑level pairwise tiebreak and jury > 1: see 16.6.

### 16.2 Settings interface (verified live)

Convention followed: typed config file + CLI subcommands + Claude Code skill (the same three surfaces the engine already used).

- **Saved layer** `.council/settings.json`, written only through `settings.py` (atomic replace). Precedence unchanged: defaults < `council.config.json` < saved < `--preset` < per‑run flags.
- **CLI** `uv run council settings show [--section x] | set k=v … | unset k … | reset [--yes] | validate [file] | routes | presets | wizard [--answer k=v …]`. `set`/`unset`/`wizard --answer` validate the whole *effective* configuration (defaults + project + candidate saved layer) before writing; an invalid value prints `error: invalid settings: … / nothing written` and exits 2 with the file untouched.
- **Displayed**: every effective key with its layer (`<- project`, `<- saved`, …), enabled external routes (`external routes: none (opencode disabled; binary never spawned)` / `opencode ENABLED`), per‑role routing with model, and the limit‑enforcement table (calls counted per request with the finalisation reserve; tokens measured on OpenCode replies and estimated len/4 on chat; elapsed measured; cost measured only when a provider reports it, otherwise unavailable and not enforceable; routes opt‑in only).
- **Exposed keys** (spec list): provider and model selection (`routing.default_provider`, `routing.opencode.*`), per‑role routing and sampling (`routing.roles.<role>.provider|model|temperature|top_p`; the chat route cannot apply sampling and says so), jury (`judge.jury_size`), lenses (`lenses.*`), rubric thresholds (`judge.materiality_threshold|promotion_margin|unverified_gate_policy|half_widths`), **rubric weights** (`policy.weight_overrides`, added this sitting: name‑ or id‑keyed relative weights applied when the policy is registered, score criteria only, normalised afterwards, applied/unapplied keys recorded on the `EvaluationPolicy` and as a `policy_weights_overridden` event), limits for rounds, calls, tokens, time and cost (`limits.*`).
- **Skill** `/council-settings [show | set … | unset … | wizard | routes | presets | reset]` (`.claude/skills/council-settings/SKILL.md`) runs the CLI and reports its output verbatim; `reset` requires confirmation.
- **Live verification (this sitting, project root):** `settings show` (absent file, provenance, routes, enforcement) → `set limits.max_rounds=3 routing.roles.judge.provider=opencode routing.opencode.enabled=true` (saved, `external routes: opencode ENABLED`, routes table shows `judge provider=opencode model=(opencode default: claude-agent/haiku)`) → `set limits.min_rounds=9` refused (`limits.min_rounds must be <= limits.max_rounds`, exit 2, nothing written) → `validate` VALID → `wizard` lists every key with current and default → `unset routing.opencode.enabled` → `reset --yes` → file absent again; `config show` and `settings show` agree. Rubric weights end to end: `council run … --fixture tests/fixtures/first_pass.json --set 'policy.weight_overrides={"Brand fit":5,"crit_reach":1,"nonexistent":2}'` (run `weights_check`) recorded `policy_weights_overridden {applied: [crit_reach, Brand fit], unapplied: [nonexistent]}`, the committed policy carries weights reach 1 / measurability 3 / execution 2 / brand 5, provenance `policy.weight_overrides.* <- override`, and the decision changed from the fixture's default (shortlist instead of firm). Headless end‑to‑end check of the skill from a fresh Claude Code session started in `council/`: `claude -p "/council-settings show"` ran `uv run council settings show` + `routes` under the skill's `allowed-tools` with **no permission denials** and summarised layers, routing, judge, lenses, limits and enforcement correctly (transcript `.council/inbox/live_run2/headless_settings_show.json`, 2 turns).

### 16.3 Live `/council` runs in Claude Code (OpenCode disabled) and skill discovery

**Skill discovery.** A fresh headless session started in `council/` (`claude -p`, no tools) listed exactly `council` and `council-settings` as available skills. The session that executed this Run 2 had been started in the *parent* folder and did not see either skill, which falsifies the Run 1 assumption that they would appear as directory‑scoped `council:council` skills: Claude Code must be started in `council/`.

**Live runs through the entry point.** Three runs were driven end to end by a fresh headless Claude Code session (`claude -p --output-format stream-json "/council …"`, model `claude-sonnet-5-5`, transcripts in `.council/inbox/live_run2/headless_council_*.jsonl`); the chat model followed `SKILL.md` unattended: args file → `council start --args-file` → one JSON response per request → `council submit … --request-id` → report. Permission denials across the three sessions: **0**; rejected submissions: **0** (every JSON response validated at the first attempt).

| run | preset | route | result | calls | tokens | elapsed | notes |
|---|---|---|---|---|---|---|---|
| `live_run2_quick` (smoke) | quick | chat only (`external routes: none`) | COMPLETE, stop `budget_calls` after round 1 (24/24 calls), **conditional**: keep the 70/30 mix; alternatives: marginal‑CAC spend‑step tests, TikTok Ads test to own site funded from Meta, margin/cohort‑gated TikTok test, phased 25 % move; confidence low (retained tie; leader challenge `lch_0001` unresolved and able to alter the outcome, no budget to reopen; ranking robustness 0.13; evidence quality 0.71); 9 challenges, 5 verifications pending; one new version unscored under the last snapshot | 24 | 35 136 estimated (chat) | 13 min 27 s engine; 72 chat turns, US$ 3.38 session cost | 0 rejected submissions; lenses first_principles, inversion, information_option; next action = resolve the decisive uncertainty (January backend new‑customer CAC vs ≈ 45–46 EUR threshold, measured marginal CAC by channel) |
| `live_run2_first_pass` (matched single‑pass baseline, same question) | first_pass | chat only | COMPLETE, stop `stable` after round 1, **shortlist** between the status quo and a 4‑week information sprint (alternatives also: readiness‑gated TikTok Shop launch, marginal‑CAC re‑split, 25 % move); confidence low (retained tie; ranking robustness 0.19; evidence quality 0.71); no review, no challenges, no verification by design | 21 | 40 629 estimated (chat) | 17 min 4 s engine; 53 chat turns, US$ 3.33 session cost | 0 rejected submissions; 5 lenses (first_principles, inversion, information_option, asymmetric_upside, execution); next action = obtain the evidence separating the two shortlisted options |

**What the deliberation added over the single pass on this question (same model, same session type, same question):** the quick council produced 9 typed challenges (two material ones open against the leader), a leader challenge whose unresolved status turned a firm‑looking status quo into a *conditional* recommendation with an explicit reversal threshold (January backend CAC vs ≈ 45–46 EUR), and five verification items it could not afford; the first pass ended `stable` with a two‑option shortlist and no objections at all. Cost of that: +3 calls (24 vs 21) but ‑5 k estimated tokens (fewer lenses), and 19 more chat turns. Neither run promoted a challenger: on this question both routes kept the status quo as incumbent, so the live smoke exercised framing, policy, generation, review, verification, matched judging and the leader challenge, but not a promotion (promotion, regression and rescoring remain covered by the deterministic fixtures and by the benchmark runs below).
| `live_run2_mixed` (typo‑before‑launch question) | first_pass | chat + judge on OpenCode (`--opencode --set routing.roles.judge.provider=opencode`) | COMPLETE, `stable` after round 1, **shortlist** (leader "Ship a text‑only fix tonight, check it, and launch on schedule"; alternatives: tie paid start to a verified page; launch with the typo; 30‑min delivery check), confidence low, ranking robustness 0.0 (close scores) | 18 (7 judge calls on OpenCode) | 142 107 measured (OpenCode) + 8 829 estimated (chat) | 6 min 42 s engine; 25 chat turns, US$ 0.96 session cost | framer did not mark the question trivial, so 5 lenses ran; decision limitation records "Providers used: chat, opencode; tokens partly measured, partly estimated; cost unavailable"; `p_judge_1 opencode claude-agent/haiku isolated`, all other participants `chat shared`; no permission denials |

Earlier‑sitting live runs kept for reference (engine code older than the final one): `live_smoke` (standard preset, chat, 45 calls, 4 rounds, `max_rounds`, conditional recommendation to keep the mix with an unresolved leader challenge) and `live_first_pass` (14 calls, `stable`).

### 16.4 OpenCode route (live)

Preflight this sitting: `opencode v2.3.2`; `opencode models` lists 79 models — 13 `claude-agent/*`, 21 `google/*`, 22 `openai/*` (gpt‑5.5 … gpt‑6.2 families), 4 `ollama/*` (local: `gemma4:latest`, `gemma4:26b`, two Qwen 3.8 builds), 9 `muse-code/*`, 10 `opencode/*`; `opencode auth list` shows Claude Agent, Google (3 accounts) and OpenAI credentials stored **inside OpenCode** (never read by the engine; no provider API key is present in the shell environment). Direct probes with the restricted agent on *listed* ids: `claude-agent/haiku` ✔; `ollama/gemma4:26b` ✔ ("pong", local, cost 0); `openai/gpt-6.2-sol` ✔ (ChatGPT‑account Codex route; `openai/gpt-5.5-fast` → HTTP 400 `model_not_in_accessible_catalog`, so only the gpt‑6.x family is usable on this account); `google/gemini-flash-latest` → `provider.quota` HTTP 402 "prepayment credits are depleted" (unchanged since the earlier sitting). Unlisted ids (`google/gemini-2.5-flash`, `openai/gpt-5-mini`) return `provider.no-route`, which says nothing about the provider. **Usable external providers today: `claude-agent` (subscription), `openai` gpt‑6.x (ChatGPT account) and local `ollama`; all three report `cost: 0`, recorded as *unavailable*; Google is blocked by quota.**

- **Council runs with ≥ 1 participant on the external route.** Every benchmark run (16.5) is a full council run with all roles on `claude-agent/haiku` through the restricted `council-member` agent, `isolation = isolated`, `model_requested = model_reported = claude-agent/haiku` (alias unresolved by OpenCode's `session export`), measured tokens per call, cost unavailable. The in‑chat mixed run `live_run2_mixed` routed only the judge to OpenCode while framer, policy setter and strategists stayed on the chat model (participants table in its `state.json`: `p_judge_1 opencode claude-agent/haiku claude-agent/haiku isolated`, all others `chat … shared`), so identity and isolation are recorded per participant inside one run.
- **Fallback demonstrated live, in chat (`live_run2_fallback`, driven in this session as the responder).** `--opencode --set routing.roles.judge.provider=opencode --set routing.opencode.timeout_seconds=5`: both judge calls timed out after 5 s, were retried once and fell back to the chat model (`route_fallback` events `req_0004`, `req_0005`: `from opencode to chat, error "opencode call failed after 2 attempt(s): opencode timed out after 5s"`); the judge requests were then printed to the chat with `provider=chat isolation=shared`, answered, and the run completed (`trivial_question`, firm, 5 calls; participant `p_judge_1 provider=chat model_requested=claude-agent/haiku isolation=shared`; decision limitation "Providers used: chat"). The earlier sitting also recorded a fallback to `fail` (`live_opencode_quick`, 120 s timeout → `route_fallback to fail` → request failed → run resumed with a 300 s timeout via `council next --set`).
- **Second external provider, local model (`live_run2_ollama`, autonomous `council run --provider opencode --opencode`, all roles on `ollama/gemma4:26b`, first_pass preset, typo question).** COMPLETE, `stable`, shortlist (direct fix vs parallel asset sweep), 23 calls, 205 752 measured tokens, 39 min 20 s (local 26 B model), cost 0 → unavailable, every participant `opencode ollama/gemma4:26b ollama/gemma4:26b isolated`. The validation layer did its job on a weaker model: 4 responses rejected before commit (a claim citing an assumption id as evidence; judges citing claim ids as assumptions), 3 retried successfully, 1 judge request failed after `max_attempts` and is recorded as an explicit missing judgement (`judgement missing for optv_decoupled_path_v1 under snap-4`) instead of an imputed score. This also exercises the neuralhats‑style local‑model execution on the engine side. The same run on the smaller `ollama/gemma4:latest` (≈ 6.6 GB, the size class neuralhats defaults to) **failed cleanly** (`live_run2_ollama_e4b`): the baseline strategist reply was unparseable twice (`options: Field required; __unparseable__`), the run ended `FAILED` after 4 calls with the reason recorded, nothing was committed from the bad replies.
- **Fix shipped this sitting.** A run resumed after a provider error kept `failure_reason` and printed `failure: provider error …` even when it later reached `COMPLETE` (`live_opencode_quick`). `cli.py` now clears a recovered provider failure after a successful `next`/`submit` (the error stays in `events.jsonl`; a `budget_warning` event records `recovered_from`).
- **Known cosmetic inconsistency (not fixed, documented):** after a fallback the persisted `requests/<id>.json` still carries the original `provider: opencode, isolation: isolated` and the payload's `context_isolation: "isolated"`, while the printed request header and the participant record show `chat/shared`. Events are authoritative.

### 16.5 Benchmarks

**Published results:** `benchmarks/results/2026-11-24_final/{summary.md, runs.json, evaluations.json}` (consolidated from parts A/B/C run in parallel 19:15–20:20 CET on the final engine code; every `bench_*` run directory under `.council/runs/` is the primary record). Three earlier campaigns (`2026-11-24_run2`, `_run2_rerun`, `_run2_rerun2`) are **superseded** and kept with a note: they ran while the engine was still being fixed (gate detection, baseline for user‑named options, per‑request budget enforcement), their call‑cap override raised the quick preset from 24 to 40, and one of their runs exceeded the declared limits (41 calls, 1.06 M tokens). Their checkers were also partly vacuous and have been re‑scored with the fixed checkers.

**Design as executed (`benchmarks/cases.json` v2026‑11‑24.2).** 6 cases: `obj_vendor_ev` (objective: vendor A dominates by expected cost), `gate_budget_fail` (planted 65 k option must fail the 50 k gate), `open_channel_mix` (open: the same Meta/TikTok question as the live smoke), `false_premise` ("short‑form video always has lower CAC"), `deferral_missing_info` (no deliverability data, no quotes), `trivial_overhead` (typo before launch). 2 systems: `council_quick` (full protocol, quick preset, own cap 24 calls) and `first_pass` (llm‑council‑style single pass: frame → policy → baseline → lenses → judge → report). In‑run model for all roles: `claude-agent/haiku` through the restricted OpenCode agent (isolation `isolated`, tokens measured, cost unavailable). Evaluator for the open case: `claude-agent/sonnet`, blinded A/B with randomised order, ids and lens/round hints removed, 2–3 repeats; separate from the in‑run judge. Primary measures fixed beforehand (§13): correct option on objective cases, planted‑issue detection on failure‑mode cases, independent 0–10 rubric (defensibility, completeness, actionability) on open cases. Resource limits: ≤ 40 calls (never above a preset's own cap), ≤ 400 k measured tokens (enforced before each request; one reply may overshoot), ≤ 30 min per run; ≤ 60 runs per campaign; stop at the first provider quota error. **Checker fixes this sitting:** the premise check matched field names (`inferred_assumptions` contains "inferred"/"assum") and passed on every run; it now matches text values only against planted‑claim phrases. The title check used a loose substring (`"A ("`); it is now a whole‑phrase match and an empty title never matches. `tests/test_benchmark_checks.py` guards both.

**Results — 20 runs, 0 provider errors or route fallbacks, 0 failed runs, 0 runs over the call or time limits; 16 responses were rejected by the validator and retried (12 in council runs, 4 in first‑pass runs — haiku citing claim ids as assumptions or evidence ids it did not create; every retry validated), counted as mismatches; the 400 k measured‑token cap was overshot by the last reply in 7 of the 8 non‑trivial runs (402 k–442 k), because the cap is checked before a request is issued and one haiku reply with its cached agent context adds ≈ 19 k tokens.** All 20 decision records were rebuilt with `council rereport` after the `report.py` next‑action fix below (no model calls; checks unchanged).

| case | system | n | primary pass | calls mean [min–max] | measured tokens | elapsed s | budget‑truncated | leader challenge reached |
|---|---|---|---|---|---|---|---|---|
| obj_vendor_ev | council_quick | 3 | 3/3 (Vendor A every time) | 7 [7–7] | 108 k | 195 | 0 | 0 (trivial stop) |
| obj_vendor_ev | first_pass | 3 | 3/3 | 11.3 [7–20] | 197 k | 316 | 0 | 0 |
| gate_budget_fail | council_quick | 1 | 1/1 (65 k TV spot fails the gate, never recommended) | 21 | 407 k | 629 | 1 | 0 |
| gate_budget_fail | first_pass | 1 | 1/1 | 22 | 402 k | 567 | 1 | 0 |
| open_channel_mix | council_quick | 1 | rubric (below) | 18 | 411 k | 742 | 1 | 0 |
| open_channel_mix | first_pass | 1 | rubric | 15 | 403 k | 692 | 1 | 0 |
| false_premise | council_quick | 1 | 1/1 (premise labelled an unverified hypothesis; conditional) | 24 | 439 k | 638 | 1 | **1** |
| false_premise | first_pass | 1 | 1/1 (premise flagged in evidence gaps; firm) | 24 | 437 k | 628 | 1 | 0 |
| deferral_missing_info | council_quick | 1 | 1/1 (conditional: defer, measure, quote, then decide) | 20 | 442 k | 785 | 1 | 0 |
| deferral_missing_info | first_pass | 1 | 1/1 (shortlist: measure‑then‑decide) | 21 | 371 k | 533 | 0 | 0 |
| trivial_overhead | council_quick | 3 | 3/3 | 6.7 [6–8] | 79 k | 122 | 0 | 0 |
| trivial_overhead | first_pass | 3 | 3/3 | 6.3 [6–7] | 79 k | 131 | 0 | 0 |

**Open case, blinded rubric (`open_channel_mix`, same pair of runs).** Pass 1 (original report and 6 000‑character evaluator cut): first_pass won 2–0; the evaluator's reasons were that the council record "is cut off" and that its next action was "merge OPT‑6 into OPT‑5", an internal housekeeping objection. Both causes were defects, not deliberation quality: (a) `report.py` picked the first open blocking objection in store order as the next action — it now orders objections by relevance to the recommended option (target, then what it could change, then severity; `challenge_priority`, `tests/test_report_priority.py`), and the council record's next action became "Resolve: move G1 to 2027‑02‑05 or later, or state the shortened holdout length and its power"; (b) the evaluator input hard‑cut at 6 000 characters — it now keeps whole lines up to 14 000 characters with per‑section caps and the recommended option's objections first. Both open‑case records were rebuilt from committed state with `council rereport` (no model calls) and re‑evaluated as pass 2 (3 repeats, random order): council_quick 2 – first_pass 1 — but every pass‑2 verdict went to whichever record was shown first, so a **pass 3 with balanced order** was added (3 repeats with the council shown first, 3 with the first pass shown first): the verdict followed the presentation order in all 6 cases (3–3). **The overall winner is therefore inconclusive (order effect in the evaluator).** The per‑criterion scores are stable across orders and passes: council_quick defensibility 6–8 / completeness 8 / actionability 4–6 vs first_pass defensibility 6 / completeness 5–6 / actionability 8 (order‑balanced pass 3, n = 6 each: council 6.67 / 8.00 / 5.00, mean 6.56; first pass 6.00 / 5.83 / 8.00, mean 6.61; passes 2+3, n = 9: council 6.89 / 8.00 / 5.11, mean 6.67; first pass 6.00 / 5.67 / 8.00, mean 6.56). The evaluator consistently credits the council for stating low confidence, open objections and reversal conditions, and the first pass for a concrete staged budget plan; the council's actionability deficit comes from a budget‑truncated run whose next action is an objection to resolve rather than a plan to start. All three passes are kept in `evaluations.json` and `summary.md`.

**Verdict against the predeclared hypotheses (§13).**
- *vs llm‑council first pass (open cases: ≥ 1.0 rubric point and ≥ 2 more planted failures caught):* **not met.** Mean rubric equal (6.56 vs 6.61 on the order‑balanced pass; the verdict tracks presentation order), with a clear split: +0.7 defensibility, +2.2 completeness, −3.0 actionability. Planted‑failure detection was equal (both systems caught the gate failure, the false premise and the deferral), so the ≥ 2 gap was not observed. The council did what the first pass cannot by construction: typed challenges (15–24 per open run), a leader challenge on the false‑premise case, conditional outcomes with reversal conditions, and explicit unfinished checks; on the deferral and gate cases its recommendation was *conditional* where the first pass was *firm*, which the rubric evaluator rewarded for defensibility and penalised for actionability.
- *Overhead on straightforward cases:* equal — 6.7 vs 6.3 calls, 79 k tokens each, ≈ 2 min; the trivial‑question stop works on both. One first‑pass repeat recommended launching with the typo unchanged; the overhead checker (stop reason + call cap) does not measure direction and this is recorded as a mismatch.
- *Objective case:* 6/6 correct on the final code (the superseded campaign had 0/2 before the baseline fix).
- *Variability (3 repeats, cheap cases):* council_quick is tight (7 calls every time on the vendor case; 6–8 on the trivial case); first_pass varied 7–20 calls on the vendor case because one repeat did not stop as trivial.
- *Budget truncation:* 7 of the 8 non‑trivial runs on OpenCode stopped on `budget_tokens` or `budget_calls` (the deferral first pass stopped `stable`); haiku replies plus ≈ 3.7 k cached agent tokens make ≈ 19 k measured tokens per call, so the 400 k cap binds at 21–24 calls and the leader challenge was reached once. Multi‑round deliberation under this cap needs the chat route (estimated tokens) or a larger token budget; the limit was kept fixed as declared. **Enforcement gap found (open item, engine not changed after the campaign):** `Budget.limit_hit` reports `budget_calls` before it looks at tokens, and `_advance` only short‑circuits on token/time/cost stops, so a run that exhausts its deliberation calls while already over the token cap still spends the finalisation reserve on the leader challenge (the `false_premise` council run stopped on `budget_calls` and finished at 438 k measured tokens after the two challenge calls; per‑call token counts are not in the event log, so the exact crossing point is not recorded).
- *vs council‑review, council‑master, Council‑Decide, llm‑as‑a‑verifier:* **no live comparison** (status below); the corresponding hypotheses are untested, not confirmed. **None of the six reference implementations was run as shipped except neuralhats** (paragraph below); the llm‑council comparison above is a proxy through the engine's own preset.
- *vs neuralhats (fewer calls for equal rubric):* see the neuralhats paragraph below the status table.
- *Incremental contribution of incumbent tracking, targeted follow‑up and leader challenge; one‑model vs OpenCode runs:* deferred under budget; the only matched one‑model vs OpenCode pair is the live smoke (`live_run2_quick`, chat, 24 calls, conditional, challenge reached) vs the benchmark run (`council_quick` on haiku, 18 calls, conditional, challenge not reached) on the same question — both kept a cautious outcome, the chat model reached the leader challenge within the same call cap.

**Status of the six references (preflighted this sitting: `which ollama typst`, `ollama list`, provider‑key names in the environment, `opencode models` and one probe per provider; all six accounted for).**

| Reference | Status | Reason |
|---|---|---|
| llm‑council‑main (first‑pass workflow) | **proxy comparison only** — the engine's own `first_pass` preset (same lenses, no review/verification/challenge) stood in for the reference in 10 matched runs; the original agents were **not run** | the original is a set of Claude Code agents; it is runnable unattended through `claude -p` (≈ US$ 3 per case, new spend — the user's decision), which was not known when the campaign was designed |
| council‑review‑main | **not run** (runnable) | prompt‑only Claude Code skill; runnable unattended through `claude -p` at ≈ US$ 3–4 per case (new spend — the user's decision); not budgeted in this session |
| council‑master | blocked by credentials | needs `OPENAI_API_KEY`‑style keys for OpenAI‑compatible endpoints (Gemini/xAI) in the environment; none present — the OpenAI access on this machine is a ChatGPT‑account OAuth held inside OpenCode, not an API key; Google quota is depleted (402) |
| LLM‑Council‑Decide‑master | blocked by credentials and dependencies | `OPENROUTER_API_KEY` and Typst not available |
| neuralhats‑main | **live comparison attempted** (details below the table) | Ollama is installed with `gemma4:latest` and `gemma4:26b`; the FastAPI backend was installed in a scratch copy and driven through its HTTP API (no frontend, no cost); see the neuralhats paragraph |
| llm‑as‑a‑verifier‑main | blocked by dependencies (possibly unblockable) | needs a log‑probability backend (DeepSeek, Vertex or OpenAI‑compatible with logprobs); none configured; the local Ollama server may expose logprobs on its OpenAI‑compatible API but this was not tested |

**neuralhats live comparison (attempted this sitting, no money spent).** The reference was copied out of the read‑only `original/` folder into a scratch directory, its seven Ollama hat models were created from its Modelfile template on `gemma4:latest` (≈ 6.6 GB; its default `gemma4:e4b` is the same size class — the 26 B model would not have fitted the 45‑minute cap), its FastAPI backend was installed in a throw‑away venv and driven through its HTTP API only (`POST /debates` in `boardroom` mode, polled `GET /debates/{id}`, then `POST /debates/{id}/report`); the frontend was not started. Case: the engine's typo‑before‑launch question. Outcome: **completed** — 5 rounds × 6 hats = 30 hat turns plus 1 facilitator report call (its Blue hat answered `CONTINUE` in rounds 1–4 and `STOP` in round 5, its `MAX_ROUNDS`), 11 min 34 s debate + 47 s report; the synthesis (3 144 characters, ending mid‑sentence — "A simple, immediate" — as produced by its facilitator model) drifts from the typo to a "minimal proxy endpoint" and GDPR/CCPA exposure. Engine counterpart on local Ollama: `live_run2_ollama` (`first_pass` preset, all roles on `ollama/gemma4:26b`, 23 calls, 39 min, shortlist "fix the typo immediately", medium confidence; the matched attempt on `gemma4:latest` failed cleanly at the baseline step, 16.4). **Blinded evaluator (`claude-agent/sonnet`, both presentation orders × 2, hat names masked as whole words):** engine 4 – neuralhats 0, independent of order; mean rubric engine 5.0 / 4.0 / 4.0 vs neuralhats 3.75 / 4.75 / 2.75 (defensibility / completeness / actionability) — neuralhats scores higher on completeness, the engine on defensibility and actionability. Reasons given: the engine record "gives a clear recommendation to fix the typo, with alternatives and trade‑offs listed, though its next action is muddled and it records no reversal conditions"; the neuralhats synthesis is "a rambling, truncated debate summary with unsupported statistics" that "never states a clear recommendation" and drifts to "overengineered solutions (proxy endpoint)". **Mismatches that limit the claim:** different local models (26 B vs the ≈ 8 B class), one case, and a format asymmetry (structured decision record vs narrative synthesis). The §13 hypothesis "fewer calls for equal rubric" reads as 23 calls vs 31 with a higher rubric on this one case — a result on *this case and these models*, not a general verdict. Artefacts: `.council/inbox/live_run2/neuralhats_{messages,report,meta,eval}.json`, `neuralhats_backend.log`, `neuralhats_debate.log`. Side effects cleaned up: the seven `neuralhats-*` Ollama models created for the attempt were removed again (`ollama rm`), the backend process was stopped (nothing listens on port 8017), and the scratch install lives outside the project in the job's temp folder.

### 16.6 Acceptance item (6): fixtures for reframe, reinstate, engine‑level tiebreak, jury > 1

Delivered as two new content‑matched fixtures built in `tests/fixtures/build_fixtures.py` (the five Run 1 fixtures are byte‑identical) and `tests/test_reframe_reinstate_tiebreak_jury.py` (9 tests). No engine code was changed for them.

| Behaviour | Fixture / config | Controller outcome asserted |
|---|---|---|
| Reframe | `reframe_reinstate.json`; lens `staging`, `limits.min_rounds=max_rounds=2`, `max_leader_challenges=0`, `max_verification_calls=0`, `review.panel_size=1`; 14 calls, stop `max_rounds` | reviewer `reframe` → brief v2 with `supersedes_id`, controller‑authored, `supersedes` relation; policy copied under brief_version 2 / rubric 1; `reframes_used = 1`; `rescore_required {reason: reframe}`; every candidate re‑judged under the new comparison key (A and B under v1 round 0 and v2 round 1, C only under v2); v1/v2 judgements never combined; a second reframe is refused by `max_reframes` and recorded as an unfinished check |
| Reinstate | same fixture | withdrawn round‑0 incumbent reinstated as a new version with parent chain, `supersedes` relations, `change_reason "reinstated: …"`, claims and assumptions restored, `Response.kind = reinstate` addressing the withdrawing challenge; reinstated version is a candidate, judged under the current key, round‑2 challenger → `retained_tie` |
| Engine‑level pairwise tiebreak | `tiebreak_jury.json`; preset `first_pass`, lens `staging`, `judge.jury_size=2`; 12 calls | close call (Δ 0.9 ≥ materiality, overlapping bounds) → two `compare` requests by `p_judge_1` with swapped candidate order (slots a/b, payload titles swapped, ids are literal labels), issued after all judgements; two `PairwiseComparison` records; both passes prefer C → `promoted`, incumbent history and firm decision on C |
| Jury > 1 | same fixture | every version scored by `p_judge_1` and `p_judge_2`; combined 6.9 with bounds [6.0, 7.8] (width 1.8 vs 1.4 for either judge alone); `signals.judge_agreement = 0.95` with note "across 2 judges", printed in `report.md` |

**Engine gaps found while fixturing (documented, not changed, so that the benchmark results below stay on the delivered code):** (a) `_on_RESPONDING` polls `candidates()` (active latest versions + incumbent), so the owner of a withdrawn *non‑incumbent* option is never asked again and `reinstate` is reachable only for a withdrawn incumbent; (b) the `reinstate` branch of `Applier.apply_respond` leaves the withdrawing challenge open and blocking (`withdraw` resolves its challenge; `reinstate` should too), so such a run cannot stop `stable`; (c) a withdrawn incumbent remains incumbent, so its reinstated copy competes with itself and the decision degrades to a two‑version `shortlist`. Fixture matching cannot distinguish judge requests by brief version (no `brief_version` match hint); the fixture pins them by round instead.

### 16.7 Changed files, run instructions, blockers

**Changed/created in Run 2** (relative to the Run 1 handoff; `original/` untouched):
- Settings interface: `src/llm_council/settings.py` (new), `src/llm_council/cli.py` (`settings show|set|unset|reset|validate|routes|presets|wizard`, `rereport`, `next --set` operational override, recovered‑failure clearing), `.claude/skills/council-settings/SKILL.md` (new), `tests/test_settings.py` (new).
- Rubric weights in settings: `src/llm_council/config.py` (`PolicyConfig.weight_overrides`), `src/llm_council/phases.py` (`Applier.apply_policy` applies and records overrides), `src/llm_council/ontology.py` (`EvaluationPolicy.weight_overrides_applied|unapplied`, `EventKind.POLICY_WEIGHTS_OVERRIDDEN`), `src/llm_council/engine.py` (passes the overrides), `tests/test_policy_weights.py` (new).
- Engine fixes from the earlier sitting (recorded in their tests): per‑request enforcement of token/time/cost limits (`engine.py: _advance`, `tests/test_budget.py`), gate detection and baseline handling for user‑named options (`engine.py`, `phases.py`, `ontology.py`, `prompts.py`), OpenCode timeout/retry and `GateResult.assumption_ids` (`providers/opencode.py`, `providers/driver.py`, `providers/base.py`), `council.config.json` (timeout 300 s, 60 calls).
- Acceptance item (6): `tests/fixtures/build_fixtures.py` (two new fixture builders), generated `tests/fixtures/reframe_reinstate.json`, `tests/fixtures/tiebreak_jury.json`, `tests/test_reframe_reinstate_tiebreak_jury.py` (new).
- Report next‑action ordering (benchmark finding): `src/llm_council/report.py` (`challenge_priority`; open objections ordered by relevance to the recommendation before the next action, decisive‑uncertainty list and confidence basis are derived), `tests/test_report_priority.py` (new).
- Benchmarks: `benchmarks/cases.json` (6 cases, 2 systems, limits, primary/secondary measures, checker notes; v2026‑11‑24.2 tightened the premise and title checkers), `benchmarks/run_campaign.py` (runner, values‑only checkers, preset‑respecting call cap, `--repeat`, `--rescore`, `--merge`, aggregates), `benchmarks/results/2026-11-24_final*/` (published), `benchmarks/results/2026-11-24_run2*/` (superseded, re‑scored with notes), `tests/test_benchmark_checks.py` (new).
- Docs: `docs/llm_council.md` (§1, §3, §8, §9, §11, §13 updated; §16 added), `README.md`.
- Live artefacts (not code): `.council/runs/live_run2_{quick,first_pass,mixed,fallback,ollama,ollama_e4b}/`, `.council/runs/weights_check/`, `.council/inbox/live_run2/neuralhats_*` (the neuralhats scratch install itself lives outside the project, under the job's temp folder, and is disposable), `.council/inbox/live_run2/` (headless transcripts, args files), earlier‑sitting `live_smoke`, `live_first_pass`, `live_opencode_quick`, `manual_check`, and the `bench_*` run directories referenced by `benchmarks/results/*/runs.json`.

**Run instructions** (from `council/`, quote the path; start Claude Code *in this folder* for the skills). Post‑delivery change (same day, at the user's request): plain `pip` is the only supported install, the venv must live at `.venv` in the project root, and the two skills plus the printed `SUBMIT_COMMAND` call `.venv/bin/council`:
```
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
python -m pytest                                           # 102 passed
/council <question> [--preset quick|standard|deep|first_pass] [--opencode] [--lenses a,b] [--set k=v] [--run-id id]   # opens the dashboard (--ui)
/council-settings show | set k=v … | unset k | wizard | routes | presets | reset
council start --args-file <file> [--ui|--open] | submit <run_id> <response.json> --request-id req_x | next <run_id> [--set k=v] | status | report | rereport | cancel | runs
council dashboard <run_id> [--open] | council ui [--port 8771] [--no-open]
council config show [--preset …] [--set …] [--opencode]
council settings …                                          # same as the skill; or the /settings page of `council ui`
council run "<q>" --preset quick --provider opencode --opencode          # autonomous, all roles on OpenCode
council run "<q>" --fixture tests/fixtures/main_run.json --lenses staging,information_option,asymmetric_upside
python benchmarks/run_campaign.py [--cases a,b] [--systems council_quick,first_pass] [--repeat N] [--out DIR]
python benchmarks/run_campaign.py --rescore DIR | --merge DIR1,DIR2 --out DIR
claude -p --verbose --output-format stream-json "/council <q> --preset quick --run-id <id>"   # unattended live run (used for §16.3)
```

**Remaining blockers and open items.**
- External references: none of the six was run as shipped except neuralhats (one case, local models, mismatches listed in 16.5); the llm‑council comparison is a proxy through the engine's own `first_pass` preset; council‑review and the original llm‑council agents are runnable unattended through `claude -p` at a few dollars per case and await the user's decision to spend; council‑master, Council‑Decide and llm‑as‑a‑verifier are blocked by credentials or dependencies.
- Through OpenCode, `claude-agent`, `openai` (gpt‑6.x on a ChatGPT account) and local `ollama` models are reachable; Google is blocked by quota (402). None of them reports cost, so the cost limit is not enforceable. Log‑probability scoring has no backend on either route.
- Engine gaps found by the new fixtures (16.6 a–c) are documented, not fixed. Cosmetic: the persisted request file keeps the original route after a fallback (16.4). Token‑cap enforcement gap when the call budget is exhausted first (16.5). `judge.screen_above` and `judge.finalists` are inert settings (bounded top‑k pairwise screening not delivered).
- Quick‑preset runs on OpenCode reach the token cap at 21–24 calls and are budget‑truncated before the leader challenge on open questions; on the chat route the same preset reaches the challenge but exhausts the call cap after one round. `standard` is needed for multi‑round deliberation; it costs ≈ 45 chat calls / 15 min (earlier sitting `live_smoke`).
- No git repository: no commits or branches exist; the folder is the only copy.

---

## 17. Post‑delivery additions (2026‑11‑24, evening, at the user's request)

**Run storage.** New runs live in `<project root>/council_outcomes/<YYYY-MM-DD_HH-MM-SS_question-slug>/` (`storage.runs_root`, default `council_outcomes`); the run id is the folder name (no spaces: safe in commands and URLs); `TITLE.txt` holds the framed decision statement once the framer has answered, so the folder is never renamed while commands reference it. Older runs under `.council/runs/` (`storage.legacy_runs_root`) are still found by every command. `council runs` lists both with outcome, confidence, stop reason, rounds and calls.

**Graphical interface.** `dashboard.py` writes a self‑contained `index.html` into the run folder after every controller step (`storage.dashboard`), auto‑refreshing while the run is active: KPI tiles (calls, tokens, elapsed, cost, rounds, options, promotions, open objections, rejected replies, confidence, evidence quality, judge agreement, ranking robustness), outcome, rounds table with the decision taken per round and the incumbent history, controller events, objections/dissent/leader challenge, settings in effect with provenance and one‑line explanations (`settings.SETTINGS_DOCS`), request/response log with links to the files, files generated, and the report. `ui.py` (`council ui`, standard library, `127.0.0.1` only, `storage.ui_port` 8771) serves the runs overview with KPIs, every dashboard regenerated on view, the run files, `/api/runs.json`, and a settings editor whose set/unset/reset go through `settings.py` validation (invalid values refused, nothing written; path traversal refused). `/council` now runs `council start … --ui`, which starts the server if the port is closed (`ui.ensure_server`, detached, log in `council_outcomes/.ui.log`) and opens the served dashboard. Tests: `tests/test_dashboard_ui.py` (4). Suite: 102 passed.

**Why this shape.** Claude Code is a terminal, so a browser page is the only graphical surface; the deliberation itself still runs in the chat (the chat model answers the controller's requests), so the page monitors and configures rather than drives. A static page per run keeps every outcome folder portable and readable with no process; the optional server adds editing and the cross‑run view. Known limits: the slug keeps letters and digits only (`2+2=5` → `2-2-5`), the static page's settings link only works when served, and the server has no authentication (local loopback only).

**Answer attribution.** Every answer records who produced it: `ModelReply`/`ReplyMeta` carry `tokens_detail` (input/output/reasoning/cache), `latency_seconds` and `effort` (OpenCode model variant after `#`, or `reasoning` when reasoning tokens were reported); `Participant` accumulates `calls`, `tokens`, `latency_seconds`, `effort`; `response_committed`/`response_rejected` events carry provider, model, tokens (measured or estimated), detail, latency and effort. The conversation model's identity is declared with `council start --chat-model <id>` (the `/council` skill passes its own model id) and recorded as `model_reported` on chat‑routed participants; chat latency is the time from request file to submit. The report gains a "Who answered (workflow)" table; the dashboard gains the header line `Answered by: …`, a participants table and a step‑by‑step workflow table (round, phase, role/lens, participant, who answered, tokens, latency, result). Runs recorded before this change show provider and model but no per‑call detail.

**Home page per work.** `dashboard.py` was refactored into `build_context()` + section builders (`sec_kpis`, `sec_outcome`, `sec_rounds`, `sec_objections`, `sec_who`, `sec_reasoning`, `sec_orchestration`, `sec_discussion`, `sec_settings`, `sec_log`, `sec_files`, `sec_report`) so that the full dashboard and the compact `work_panel()` share one implementation. The home page (`/`) now has one tab per work under `council_outcomes/` (newest first, up to 25) embedding that panel, an *All works* summary tab and a *Legacy runs* tab; every page (home, settings, served dashboards) carries *Works* and *Settings* navigation.

**Discussion transcript and input documents.** (1) *Discussion transcript:* `discussion.py` writes every model contribution, committed or rejected, to `<run>/discussion/NNN_rR_<phase>_<role>[_<lens>].md` and appends it to `<run>/discussion.md` (readable Markdown rendering of the JSON plus the raw JSON); `RunData.discussion` indexes them with who answered and a one‑paragraph summary. Every request now carries `discussion_so_far` (`discussion.include`: full text of the current round's committed contributions, the controller's digest of each earlier round — incumbent, outcome, ranking, open objections — and short summaries of earlier contributions; `discussion.max_chars` cap, oldest material shortened then dropped; option ids masked with the alias map on isolated review requests) and the role instructions tell the model to build on, answer or contest the others and cite D‑numbers. Rejected replies are in the transcript but never fed to other roles. The report records "Discussion transcript shared with every role" as a limitation of blindness. `discussion.include="none"` restores the Run 1 behaviour for comparison. (2) *Input documents:* `--docs path,folder` (`documents.*` limits) copies text files into `<run>/inputs/`, writes `inputs/INDEX.md` (read and skipped files with reasons), commits one `user_supplied` Evidence per file (`ev_doc_<slug>`, source `document`, author controller) under the initial snapshot (`Store.commit_baseline_evidence`, so comparison keys are unaffected), and places capped excerpts in every request's `documents` with the path of the full copy. Dashboard: new *Discussion* tab (every contribution, expandable, plus the input documents) and the files table explains the new files. The `/council` skill passes `--docs` through and tells the responder to read `discussion.md` and `inputs/` with the Read tool when excerpts are truncated.

**Tabbed dashboards.** `dashboard.tabify()` reorganises the flat sections into tabs (Overview, Reasoning workflow, Orchestration, Settings, Files, Report; settings page: Defaults, All settings, Presets, Saved layer) with a dependency‑free switcher that keeps the active tab in the URL hash across the auto‑refresh. No UI library is used: pages are hand‑written HTML with an inline stylesheet so that run folders remain self‑contained; a vendored classless stylesheet (Pico CSS) was considered and left out to avoid an 80 KB copy per run folder.

**Reasoning vs orchestration workflows; explained settings.** `trail.py` reconstructs the **reasoning workflow** from the committed records (brief versions, rubric, options per lens and revisions, objections and dissent per reviewer, verifications, responses, judgements per judge, pairwise comparisons, controller adjudications per round, leader challenge, decision), each step attributed to role · provider · model or to the controller; the dashboard shows it above the **orchestration workflow** (one row per controller request) and the report gains a "Reasoning workflow" list. The settings page explains every key with its allowed values derived from the configuration schema (`settings.allowed_values`), explains each preset in words (`settings.PRESET_DOCS`, also printed by `council settings presets`) and explains the defaults panel choices.

**Defaults panel.** `/settings` now opens with a *Defaults* panel: default route (chat/OpenCode), default OpenCode model picked from `opencode models` (cached 5 min, free text when OpenCode is absent), provider and model per role, default preset and chat‑model identity; one submit writes the saved layer through `settings.set_values`/`unset_values` (cleared fields are removed, never stored as nulls). New configuration section `defaults` (`preset`, `chat_model`): `cli.effective()` applies `defaults.preset` when the command line names none; `defaults.chat_model` is the fallback identity for chat replies.

**Run id slug format.** Run ids originally contained spaces (`2026-11-25-08-08-47 2 2 5 dimostralo`), which forced quoting in commands and `%20` in URLs. They are now `YYYY-MM-DD_HH-MM-SS_<hyphenated-slug>` (`2026-11-25_08-08-47_2-2-5-dimostralo`); existing folders were renamed and their `state.json` run ids updated.

**Port conflict handling.** When the preferred port is held by another local program, the launcher previously sent the browser there. `ui.py` now has `/api/health` (`{"app": "llm-council", "root": …}`), `is_ours()` verifies identity and project root, `pick_port()` skips ports held by other programs (up to 20 above the preferred one) and reuses an existing council ui, `serve()` refuses a busy port with a clear message, and the default `storage.ui_port` is 8771. Verified against the live foreign server on 8765: `ensure_server` reported the conflict and started on 8766. Test: `test_health_and_foreign_port_detection`. Suite: 103 passed.

**Markdown modal viewer.** Clicking any `.md` link in the interface (Files tab, discussion transcript and per‑contribution links, input document copies, report/discussion shortcuts on the home page) now opens the file fully formatted in a modal window (title, *open raw* link, Close button, Esc and click‑outside to dismiss) instead of navigating to raw text. Implementation: `dashboard._md_link()` marks every Markdown anchor with `class="md-link"`; `render_dashboard()` appends the modal skeleton, a `<script type="application/json" id="md-contents">` payload of pre‑rendered HTML (`md_to_html`, the same renderer as the report section) and a dependency‑free viewer script. Embedded content (100 KB per file, 1 MB total caps in `md_embed_map`) keeps the modal working offline from `file://`; when served, files outside the payload are fetched raw and rendered client‑side by a fallback formatter verified byte‑identical to the Python renderer on sample documents. Opening the modal pauses the running‑dashboard auto‑refresh so it cannot close the view. Served pages regenerate per view, so they pick the modal up immediately; static `index.html` files need `council dashboard <run_id>`, and the `council ui` server — which runs the code loaded at startup — must be restarted. The home and settings pages carry the modal via `ui.page()`.

**React single‑page dashboard with ARIA.** The run and home pages are a React 18 app (`web/src/*.jsx`, no JSX compiler at runtime): the Python controller computes `dashboard_state()` (plain JSON‑serializable data) and `render_dashboard()` inlines the Vite production bundle plus the state into `index.html`, so folders stay self‑contained and readable offline. Tabs are ARIA tablists with arrow‑key navigation, panels are tabpanels, the Markdown viewer is a dialog with aria‑modal, focus trap, focus return and Esc, tables use scoped headers, and a skip link targets the main content. The settings page stays server‑rendered. Tests assert on the embedded state instead of markup. Previous static tab/modal scripts are retired.

**shadcn/ui + Tailwind conversion with light/dark mode.** The dashboard UI is now shadcn‑style (Radix Tabs/Dialog/Accordion, Tailwind v4 design tokens, `tw-animate-css`): `web/` is a Vite + React + Tailwind frontend (`npm install`, `npm run build`) whose output (`dashboard.js`/`dashboard.css`) is committed under `src/llm_council/static/` and inlined by the Python shell — no CDN, no runtime build, offline pages keep working. A theme toggle in each dashboard header switches the `dark` class (persisted in `localStorage`, system preference as default). Rebuild after any `web/src` change and re‑run the suite; the UI server must be restarted to serve the new code. Tests assert Radix/shadcn wiring in source, the dark tokens in CSS, the inlined bundle (no external scripts) and the embedded state. Suite: 121 passed.

**Remove-a-work button.** Each home‑page work row and legacy entry has a trash button opening a Radix AlertDialog (“Delete this work?”, named run, irreversible); confirm issues `DELETE /runs/<run_id>/`, which removes the folder only after the same `_locate` checks as GET (direct child of a runs root with `state.json`; anything else 404s) and answers `{"deleted": id}`; the list updates in place, failures show an inline alert. Test: `test_delete_run_removes_the_work_folder` (delete, gone‑after‑GET, unknown/traversal/file‑path 404s). Suite: 122 passed.

**Plain‑words verdict and 600‑word floor.** `report.render_report()` now opens with an **In plain words** section built only from committed records: the decision named in one sentence, what it means in practice (recommended mechanism/summary), why it won (incumbent vs strongest‑alternative combined scores, or an honest statement that nothing was judged under the final comparison), the caveats (alternatives proposed but never scored, non‑stable stop reason, unfinished‑check count) and the clearest tripwire from the reversal conditions. `MIN_REPORT_WORDS = 600` is enforced in the same function: when the report would be shorter, an appendix is appended with the full texts of the recommended and alternative options, the assumptions and — if still short — the challenges, so the floor is met with record‑derived substance, never filler. Every preset and every `rereport` applies both.

**Review 2026‑11‑25 of the React interface (click‑tested with Playwright).** The React/htm rewrite was reviewed in a real browser. Found and fixed: (1) the home page rendered blank — React error #31, because the overview table handed React a bare `{"html": ""}` object for runs without a confidence level (`GenTable` now accepts React elements, `{html}` wrappers or text, never a bare object; `home_state` emits a plain string); (2) link cells (React elements) were stringified to `[object Object]` after the first fix — `GenTable` checks `React.isValidElement` first; (3) the Markdown modal did not take focus and Escape did not close it, because its lifecycle effect ran once at mount with no document (now per opened document: focus into the dialog, document‑level Escape, focus returned to the opener); (4) the run page duplicated the "run · created · folder" line and nested `<main>` inside `<main>` (server shell now carries only the nav); (5) finished runs showed the elapsed time since start instead of the time at completion (`build_context` uses the decision's budget snapshot for terminal runs); (6) settings tabs showed a stray "1" count; (7) `/favicon.ico` 404 noise (204 now). Verified in the browser: home overview and per‑work tabs with arrow‑key navigation, run tabs with hash navigation, Discussion tab for a 17‑contribution live run (chat `muse-spark`, OpenCode `claude-agent/claude-opus-5` framer, `claude-agent/claude-fable-5` judge), Files tab links, modal open/close/focus, settings page cross‑links; zero console errors. Regression test for (1): `test_home_state_never_hands_react_an_empty_html_object`. Known limits: the per‑run `index.html` is 200–850 KB because React, the discussion HTML and the Markdown map are inlined; the settings page keeps the older non‑ARIA tab switcher; a hash‑only navigation does not reload the page, so after a server restart a hard reload is needed to pick up new code.

**Home page redesign and validation fallbacks (2026‑11‑25, user request).** The home page no longer uses tabs: a sticky list of work buttons (left) and the selected work's detail (right). The colour language is the verdict kind — teal firm, amber conditional, violet shortlist, blue needs‑information, coral failed, lime running — used for the button stripe, the chips, the detail header and the summary strip; the selected button carries the URL hash (`#w3`) and ArrowUp/ArrowDown move the selection; older `.council/runs/` runs sit behind a toggle. Settings: `routing.validation_fallbacks` (project default `["openai/gpt-6.2-sol", "muse-code/muse-spark-1.3-contributor"]`): when a role's reply keeps failing validation after `retries.max_attempts` on its own route, the controller re‑issues the request to each fallback model in turn (one attempt each, through OpenCode, same payload with `discussion_so_far` and documents, plus the previous error) before taking the failure transition; recorded as `route_fallback {reason: validation}` and `request_issued {validation_fallback: n}`; the participant then shows the model that finally answered. Motivation: the ordina28 run lost its whole review phase to two rejected replies of one model. `build_providers` instantiates the OpenCode provider whenever fallbacks name real models, even with `routing.opencode.enabled=false`. Tests: `test_validation_fallback_model_answers_after_retries_are_exhausted`, `test_validation_fallbacks_are_validated_and_exhausted_fallbacks_still_fail`; the test harness switches the fallbacks off so no test reaches a real model.

**Home page: one column (2026‑11‑25, user request).** The two‑column home (list + inline detail) was replaced by a single column of work links: each button is the work's verdict colour, framed title, recommended action, confidence, stop reason, date, preset, rounds, calls and who answered, and opens the full dashboard page `/runs/<run-id>/`; the run page keeps the "← All works" and "Settings" navigation. ArrowUp/ArrowDown move focus along the list.

**Run page restyle (2026‑11‑25, user request).** The run page opens with a verdict‑coloured header card (title, question, chips for verdict/confidence/state/round/stop/preset, who answered, folder) and the Overview tab leads with the verdict card: recommended option and summary, confidence basis, next action, then reversal conditions, strongest alternatives and unfinished checks in three columns. Usage counters became a compact strip (calls, tokens, elapsed, cost, rounds, options, promotions, open objections, rejected replies) with the quality signals (evidence quality, judge agreement, ranking robustness) on a second row; tabs are pills; tables have zebra rows. Components: `RunHeader`, `VerdictCard`, `StatStrip` in `app.js`; CSS under "run page" in `dashboard.py`.

**Prompt contract review and fixes (2026‑11‑25, user request: "are these prompts complete?").** Review of `prompts.py`, the OpenCode agent config and the 17 live requests of the ordina28 run found eight gaps; all fixed. (1) Roles did not know whether they had tools: the framer (OpenCode, no permissions) was asked to "read /ordina28" and wrote "contents have not been read"; judges scored a gate "grounded in repo reality" without any way to look → `capabilities` in every payload, a tools sentence in the context block, and `register_question_documents` registers paths named in the question when `--docs` is absent. (2) Prompt/payload/validator disagreed on challenge targets (`asm_inv_light_food` rejected although listed) → `valid_target_ids` in the review payload, assumptions are legal targets (mapped to their option), `apply_review` commits the valid challenges and reports the dropped ones (`Applier.notes` → event `partial`, discussion entry note), rejects only when nothing is valid. (3) Retries carried only the error → `previous_reply` + repair instruction; `parse_reply_json` repairs trailing commas, parenthesised strings, smart quotes and comments before rejecting (the ordina28 reviewer failed on one stray parenthesis). (4) No process context → `context_block` (phase sequence, position, consumer of the reply, terms, tools, date, size). (5) Blindness claimed but not delivered → `discussion_payload(blind=…, hide_scores=…)`: no participant/provider/model for isolated routes, no ranking numbers for judges. (6) Discussion duplicated the payload (40 % of a 60k reviewer payload) → `summarize_kinds` marks option contributions `see_payload`; judges get summaries only. (7) Zero schema descriptions → `Field(description=…)` on every draft and response model and on `GateResult`/`CriterionScore`. (8) "Cites D1, D2." inside persisted text → `builds_on` list on every response model, stored on the discussion entry; guardrail forbids D-refs in text. Tests: `tests/test_prompt_context.py` (8 tests).

**Follow-up prompt (2026‑11‑25, user request).** `report.followup_prompt` builds a self-contained prompt (question, framed decision, constraints, outcome and confidence, recommended action and mechanism, alternatives, trade-offs, next action, reversal conditions, open objections, unfinished checks, influential assumptions, run folder, five-point ask); appended to `report.md` as a fenced block and exposed as `followUp` in the dashboard state; `web/src/components/FollowUp.jsx` renders it under Overview and Report with a Copy button (clipboard API, textarea fallback, selection fallback; click on the text copies too).

**React/Tailwind interface aligned with the earlier layout feedback (2026‑11‑25).** The user's Vite + Tailwind 4 + shadcn-style rewrite (`web/`, built into `src/llm_council/static/` and inlined by `dashboard.py`/`ui.py`) had reverted the home page to tabs and the run page to the KPI-grid/outcome-table layout. Reapplied: home = single column of work buttons (verdict stripe, title, recommended action, confidence/stop chips, date, preset, rounds, calls, who answered, Open button) linking to the run page, summary pills, older runs behind a toggle, ArrowUp/Down; run page = verdict-coloured header card, verdict card (recommendation, basis, next action; reversal/alternatives/unfinished in three columns), compact stat strip + quality signals, pill tabs synced with the URL hash (survive the auto-refresh, deep-linkable), zebra tables; verdict palette as Tailwind theme colours (`web/src/lib/kind.js`); `@source` so classes in Python-rendered markup are kept; settings page uses the same chrome. Rebuild with `cd web && npm run build` after any change under `web/src`.


---

## 18. State of the engine on 2026‑11‑25 (summary for a new reader)

**What exists.** A deterministic controller (`engine.py`) runs the deliberation; models answer validated requests in named roles, in the Claude Code chat (default) or through OpenCode (opt‑in, per role). Every run is a folder under `council_outcomes/` with the event log, state, requests, raw replies, the discussion transcript, the user's documents, the report (plain‑words verdict first, follow‑up prompt last), the decision record and a self‑contained dashboard. The local web interface (`council ui`, port 8771) lists the works as buttons coloured by verdict, opens each run's dashboard, deletes works on request and edits the saved settings.

**What a model receives** (§17, prompt contract): a context block (phase sequence, position, consumer of the reply, terms, tools, date, size), the role and lens instructions, the discussion so far (blind on isolated routes; summaries and no ranking numbers for judges; `see_payload` where the payload already carries the content), the documents (explicit `--docs` or paths named in the question), the payload (`capabilities`, `valid_target_ids` for reviewers, `previous_reply` on a repair retry) and a schema with a description per field. Replies list the D‑numbers they rely on in `builds_on`.

**What the controller tolerates:** JSON slips are repaired before validation; a review with some invalid targets is committed in part; after `retries.max_attempts` the request goes to the configured validation fallbacks (`openai/gpt-6.2-sol`, then `muse-code/muse-spark-1.3-contributor`), one attempt each, before the failure transition.

**How to run.** Install: `python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`. Chat: start Claude Code in `council/`, type `/council <question> [--preset quick] [--docs path] [--opencode]`; the dashboard URL is printed. Headless: `claude -p "/council …"`. Tests: `python -m pytest`. Interface rebuild: `cd web && npm install && npm run build`.

**Known limits.** Google provider has no credits (402); the chat route estimates tokens; the shared‑context limitation is recorded in every chat‑routed report; the settings page is server‑rendered (same chrome as the React pages, older CSS for its body).
