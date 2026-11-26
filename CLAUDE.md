# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is
Strategy Tribunal, an autonomous 360° decision engine: a deterministic Python controller runs a multi-round deliberation;
models answer validated requests in named roles (framer, policy setter, strategist per lens, reviewer, verifier, judge,
challenger). Package `llm_council`, command `council`, skills `/council` and `/council-settings` (discovered only when
Claude Code starts in this folder). Design and delivery record: `docs/llm_council.md` (§18 = current state). User docs:
`README.md` (short), with the reference detail in `docs/guide.md` and `docs/settings.md`.

## Commands (from this folder)
- Install: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"` — pip only, never uv. The skills call
  `.venv/bin/council`.
- Tests: `.venv/bin/python -m pytest` (no model calls; a Homebrew `pytest` shadows the venv one). No linter, formatter or
  type checker is configured.
- Subset: `.venv/bin/python -m pytest tests/test_judge.py` (one file), `… tests/test_judge.py::<test_name>` (one test),
  `… -k tiebreak` (by name).
- Interface: `cd web && npm install` once, then `npm run build` (see Interface below). Restart a running server after
  Python changes: `lsof -ti tcp:8771 | xargs kill`, then `.venv/bin/council ui` or `/council … --ui`.
- Whole deliberation with no model calls, in a throwaway root (the question must match the fixture's):
  ```bash
  D=$(mktemp -d); cp council.config.json "$D/"
  .venv/bin/council run "Should we shift 30% of our Q1 paid-search budget into short-form video?" --root "$D" \
    --fixture "$PWD/tests/fixtures/main_run.json" --lenses staging,information_option,asymmetric_upside
  ```
- Rebuild outputs of an existing run from saved state, no model calls: `.venv/bin/council rereport <run_id>`,
  `.venv/bin/council dashboard <run_id>`. Inspect: `.venv/bin/council status <run_id>`,
  `.venv/bin/council config show`.
- `benchmarks/run_campaign.py` calls real models through OpenCode. `--merge` does not, nor does `--rescore` unless
  `--reevaluate` is added.

## Architecture
Unless a path says otherwise, files are under `src/llm_council/`.

**Control flow.** `engine.py`: `Engine.step(submission)` validates the reply to the pending request, commits it, then runs
controller-only transitions (`_on_<STATE>` handlers) until another request is needed or the run is terminal. The
controller never reasons about the question. Two ways to answer, same engine: step mode (`council start` / `submit`, the
chat model answers `requests/<id>.json`; there is no chat provider class) and drivers (`providers/driver.py` loops over
the `fixture` and `opencode` providers until a request is routed to chat).

**Modules.** Protocol: `ontology.py` (records, enums, `ROLE_PERMISSIONS`, `TRANSITIONS`). Persistence: `state.py`
(`Store`: transactions, `events.jsonl`, `state.json`, resume). What models see and may say: `prompts.py`, `lenses.py`,
`discussion.py` (transcript and user documents), `phases.py` (response models, payload builders, `Applier`). Decisions:
`judge.py`, `budget.py`. Output: `report.py`, `trail.py`, `dashboard.py`. Hosts: `cli.py`, `ui.py`, `mcp.py`. The only
runtime dependency is pydantic; the web server and the MCP server are standard library.

**Invariants that span files** (detail: `docs/llm_council.md` §3–§10)
- A submission is one transaction. A rollback swaps `store.data`, so re-read it afterwards.
- Records, replies and config reject unknown fields (`extra="forbid"`). `RunData` is reloaded from `state.json`, so a new
  field needs a default, and removing or renaming one breaks existing runs.
- Judgements compare only under an identical key (brief version, rubric version, evidence snapshot, judge config hash).
  Nothing is imputed; new evidence triggers a rescore, and what the budget cannot rescore stays non-comparable.
- An invalid reply is retried, then sent to `routing.validation_fallbacks` (real OpenCode models, even with the OpenCode
  route disabled), then takes the failure transition.
- Isolated (OpenCode) routes get pseudonymised, blind payloads; judges see no ranking numbers. The prompt contract
  (context block, `capabilities`, `valid_target_ids`, repair retries, partial-accept reviews, `builds_on`, documents
  auto-detected from the question) must stay intact: `docs/guide.md`, "What every model receives".
- Config layers: defaults (`config.py`) < `council.config.json` < `.council/settings.json` < preset < per-run flags. Each
  run snapshots its effective config in `state.json`; later config edits do not reach it.
- OpenCode calls need `--standalone` with `PWD=adapters/opencode`, and the agent must not set `steps: 1` (§10).
- The browser form and MCP are restricted on purpose (`ui.WEB_FORM_DENIED`, origin and token checks, MCP flag
  allow-list); `tests/test_hosts.py` covers them.

**Adding a request kind** touches `phases.py` (response model, `RESPONSE_MODELS`, `Applier` method), `prompts.py`
(`BY_KIND`, `CONSUMER`, `SIZE`), `engine.py` (state handler, `_apply_valid`, `_on_request_failed`), `discussion.py`
(rendering), `ontology.py` if states or permissions change, and the fixtures. **Adding a config key**: `config.py`,
`settings.SETTINGS_DOCS`, `docs/settings.md`, and `ui.WEB_FORM_DENIED` if the browser must not write it.

## Tests
- Fixture JSON files are regenerated from `tests/fixtures/build_fixtures.py` at the start of every test session: edit the
  builder, not the JSON. Entries match request content, not call order; unmatched requests and unconsumed `once` entries
  fail the run.
- `conftest.run_fixture` empties `validation_fallbacks`. `make_root` alone copies the project config, which names real
  models: empty the list in any new test that can exhaust retries.
- `tests/test_dashboard_ui.py` asserts on `web/src` sources, the inlined bundle and the embedded page state.

## Interface
`web/` is Vite + Tailwind 4 + Radix (shadcn style). `dashboard.dashboard_state()` builds plain JSON, which is inlined with
the bundle into each run page and read by `web/src/App.jsx`, so `index.html` works offline (`npm run dev` has no state to
show). The settings page is server-rendered by `ui.py`. `npm run build` writes
`src/llm_council/static/dashboard.{js,css}`, which is committed. Rebuild after editing `web/src` **or Tailwind classes in
Python markup** (Tailwind scans `src/llm_council`). Static `index.html` files of old runs change only after
`council dashboard <run_id>`.

## Runs and hosts
- Runs live in `council_outcomes/<date_time_slug>/` (older ones in `.council/runs/`); settings in
  `.council/settings.json`; all ignored by git. The project root is `--root`, else `$COUNCIL_ROOT`, else found upwards
  from the working directory.
- Other hosts: `council mcp` (MCP over stdio, Claude Desktop), `council submit <run> -` (stdin, copy-paste chats),
  `--chat-tools none`, `Dockerfile` (`council ui --host 0.0.0.0`). Keep `docs/responder.md` in sync with the skill.
- `original/` holds six third-party reference projects, read-only, ignored by git. Never copy code from them.

## Rules the user has set
- Home page = single column of work buttons coloured by verdict (teal firm, amber conditional, violet shortlist,
  blue needs-information, coral failed, lime running); clicking opens the run page. No tabs for works, no two columns.
- Run page opens with the verdict card; follow-up prompt with Copy button under Overview and Report.
- Verify UI changes in a real browser before reporting; keep README and docs/llm_council.md §17 in sync with changes.
- Never run a fixture (`--fixture`) to answer a real question. Validation fallbacks: `openai/gpt-6.2-sol`, then
  `muse-code/muse-spark-1.3-contributor`.
- Git: repository `github.com/mbuon/strategy-tribunal`, branch `main`; the user pushes. Commits and pull requests carry no
  Claude attribution.
