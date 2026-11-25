# Recorded OpenCode payloads (real infrastructure, 2026-11-24, opencode v2.3.2)

- `error_no_route.jsonl` — `opencode run --format json --model nonexistent/no-such-model` → `provider.no-route`, exit code 1.
- `error_quota_402.jsonl` — Google provider with depleted prepayment credits → `provider.quota`, HTTP 402.
- `success_restricted_agent.jsonl` — restricted agent `council-member` from `adapters/opencode/opencode.json`, model `claude-agent/haiku`; one-word reply; tokens cache write 2680 / read 1042 (default agent: 35 888 write).
- `session_export_sample.json` — shape of `opencode session export <id>` used to read the reported model identity.

The fake `opencode` binary used by `tests/test_opencode_route.py` replays these envelopes; no live call is made in tests.
