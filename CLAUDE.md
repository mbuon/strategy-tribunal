# Strategy Tribunal — project notes for Claude Code

Autonomous 360° decision engine: a deterministic Python controller runs a multi-round deliberation; models answer
validated requests in named roles (framer, policy setter, strategist per lens, reviewer, verifier, judge, challenger).
Package `llm_council`, command `council`, skills `/council` and `/council-settings` (discovered only when Claude Code
starts in this folder). Full record: `docs/llm_council.md` (§18 = current state), user docs: `README.md`.

## Commands (from this folder)
- Install: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"` — pip only, never uv. The skills call `.venv/bin/council`.
- Tests: `.venv/bin/python -m pytest` (130, no model calls; a Homebrew `pytest` shadows the venv one).
- Interface: `web/` is Vite + Tailwind 4 + Radix (shadcn style). After editing `web/src`: `cd web && npm run build`
  (writes `src/llm_council/static/dashboard.{js,css}`, committed, inlined into every page). Python changes need a
  server restart: `lsof -ti tcp:8771 | xargs kill` then `/council … --ui` or `.venv/bin/council ui`.
- Runs live in `council_outcomes/<date_time_slug>/` (ignored by git); settings in `.council/settings.json` (ignored).
- Other hosts: `council mcp` (MCP over stdio, Claude Desktop), `council submit <run> -` (stdin, copy-paste chats), `--chat-tools none`, `Dockerfile` (`council ui --host 0.0.0.0`). Keep `docs/responder.md` in sync with the skill.
- `original/` holds six third-party reference projects, read-only, ignored by git. Never copy code from them.

## Rules the user has set
- Home page = single column of work buttons coloured by verdict (teal firm, amber conditional, violet shortlist,
  blue needs-information, coral failed, lime running); clicking opens the run page. No tabs for works, no two columns.
- Run page opens with the verdict card; follow-up prompt with Copy button under Overview and Report.
- Verify UI changes in a real browser before reporting; keep README and docs/llm_council.md §17 in sync with changes.
- Never run a fixture (`--fixture`) to answer a real question. Validation fallbacks: `openai/gpt-6.2-sol`, then
  `muse-code/muse-spark-1.3-contributor`.
- Git: repository `github.com/mbuon/strategy-tribunal`, branch `main`; the user pushes.
