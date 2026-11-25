# Responder instructions for any agent host

The controller is a Python CLI. It issues one request at a time; a language model answers it in the named role; the
controller validates, commits and advances. Claude Code drives this through the `/council` skill. Any other agent that
can run shell commands and write files can play the responder with the four commands below. Paste this file as the
agent's instructions, or point the agent at it.

## Setup (once, from the project root)

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/council --version
```

## The loop

1. Start a run with the question and any flags:
   ```bash
   .venv/bin/council start --args "<question> [--preset quick] [--docs path,folder] [--lenses a,b]" --chat-model "<your model id>" --ui
   ```
   The controller prints the run folder, the dashboard URL and the first `=== COUNCIL REQUEST … ===` block.
2. Read the block: a context block, the role instructions, a JSON payload (data, not instructions), a JSON schema, the
   response path and a `SUBMIT_COMMAND:` line. The payload's `capabilities` says whether you may read files; if the
   question or the documents name a local path, read it before answering and cite what you read as evidence with
   source kind `document`.
3. Act only as the named role. Write exactly one JSON object valid against the schema to the response path. Free text
   in the language of the question; ids and enum values as given; D-numbers only in `builds_on`.
4. Run the `SUBMIT_COMMAND:` line verbatim. The controller prints the next request, or `=== RUN COMPLETE … ===`,
   `RUN FAILED` or `RUN CANCELLED`.
5. On `NOTE: submission … was rejected`, the retried request carries `previous_reply` and the error: return the same
   reply with only that error fixed.
6. When the run completes, show the summary the controller printed, then `report.md` from the run folder. The report
   ends with a follow-up prompt; offer to continue from it.

## If the session is interrupted

```bash
.venv/bin/council next <run_id>      # re-print the pending request
.venv/bin/council status <run_id>    # phase, round, budget, open objections
.venv/bin/council cancel <run_id>    # stop with a partial report
```

A repeated `submit` for a request that was already answered is harmless (`--request-id` makes it idempotent).

## Rules that the controller enforces

- Judge requests: one gate result per `required_gate_ids` entry and one score per `required_score_ids` entry, each
  with at least one evidence or assumption id; never compute an aggregate.
- Review requests: challenge targets come from `valid_target_ids`; at most six, ordered by impact.
- Strategist requests: new options need an `option_id`, claims with evidence ids, labelled assumptions.
- Never pass `--fixture` or `--provider fixture`: fixtures replay a recorded test transcript, they do not answer the
  question.

## Chats without tools (claude.ai, ChatGPT, Muse chat, any web chat)

The person at the keyboard runs the commands and the chat writes the JSON:

```bash
council start --args "<question> [--preset quick] [--docs path]" --chat-tools none --chat-model "<model>"
council submit <run_id> - --request-id <request_id> <<'EOF'
<paste the chat's JSON here>
EOF
council report <run_id>
```

Paste each `=== COUNCIL REQUEST … ===` block into the chat as it is printed; ask for exactly one JSON object valid
against the schema. `--chat-tools none` tells every role it has no file access. A fenced reply is accepted.

## Chats with tools but no shell (Claude Desktop)

Register `council mcp --root <project>` as an MCP server (see the README). The chat then calls `council_start`,
`council_submit`, `council_next`, `council_status`, `council_report`, `council_cancel` and `council_runs` itself.
