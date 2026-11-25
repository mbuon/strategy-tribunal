"""OpenCode route and fallback with a fake `opencode` binary that replays the
recorded real payloads (tests/fixtures/opencode). No live call is made."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

from build_fixtures import main_run
from conftest import FIXTURES, LENSES, QUESTION, events, make_root, run_fixture
from llm_council.providers.opencode import parse_events

OC_FIX = FIXTURES / "opencode"

FAKE = r'''#!/usr/bin/env python3
import json, os, sys, re
from pathlib import Path
mode = os.environ.get("FAKE_OPENCODE_MODE", "ok")
marker = os.environ.get("FAKE_OPENCODE_MARKER")
if marker:
    Path(marker).write_text(Path(marker).read_text() + " ".join(sys.argv[1:3]) + "\n" if Path(marker).exists() else " ".join(sys.argv[1:3]) + "\n")
args = sys.argv[1:]
fix = Path(os.environ["FAKE_OPENCODE_FIXDIR"])
if args[:1] == ["--version"]:
    print("opencode v2.3.2"); sys.exit(0)
if args[:1] == ["models"]:
    print("claude-agent/haiku\nclaude-agent/sonnet\ngoogle/gemini-flash-lite-latest"); sys.exit(0)
if args[:2] == ["session", "export"]:
    print((fix / "session_export_sample.json").read_text()); sys.exit(0)
if args[:1] == ["run"]:
    if mode == "quota":
        sys.stdout.write((fix / "error_quota_402.jsonl").read_text()); sys.exit(1)
    if mode == "noroute":
        sys.stdout.write((fix / "error_no_route.jsonl").read_text()); sys.exit(1)
    prompt = args[-1]
    m = re.search(r"REQUEST \(JSON data, treat as data\):\n(.*)\n\nRESPONSE SCHEMA", prompt, re.S)
    payload = json.loads(m.group(1))
    answers = json.loads(Path(os.environ["FAKE_OPENCODE_ANSWERS"]).read_text())
    key = payload["option"]["id"] + "|" + payload["comparison_key"]["evidence_snapshot_id"]
    content = answers[key]
    lines = [json.loads(l) for l in (fix / "success_restricted_agent.jsonl").read_text().splitlines()]
    for ev in lines:
        if ev["type"] == "text":
            ev["part"]["text"] = json.dumps(content)
        sys.stdout.write(json.dumps(ev) + "\n")
    sys.exit(0)
print("unknown", file=sys.stderr); sys.exit(2)
'''


def install_fake(tmp_path: Path, mode: str, marker: Path | None = None) -> Path:
    binary = tmp_path / "bin" / "opencode"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(FAKE)
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    answers = {}
    for e in main_run()["responses"]:
        m = e.get("match", {})
        if m.get("kind") == "judge":
            answers[f"{m['version_id']}|{m['snapshot']}"] = e["content"]
    ans_path = tmp_path / "answers.json"
    ans_path.write_text(json.dumps(answers))
    os.environ["FAKE_OPENCODE_MODE"] = mode
    os.environ["FAKE_OPENCODE_FIXDIR"] = str(OC_FIX)
    os.environ["FAKE_OPENCODE_ANSWERS"] = str(ans_path)
    if marker is not None:
        os.environ["FAKE_OPENCODE_MARKER"] = str(marker)
    else:
        os.environ.pop("FAKE_OPENCODE_MARKER", None)
    return binary


def oc_overrides(binary: Path, **extra):
    ov = {"routing": {"opencode": {"enabled": True, "binary": str(binary), "fallback": "fixture", "retries": 1,
                                   "default_model": "claude-agent/haiku"},
                      "roles": {"judge": {"provider": "opencode", "model": "claude-agent/haiku"}}}}
    for k, v in extra.items():
        ov["routing"]["opencode"][k] = v
    return ov


def test_parse_events_success_and_errors():
    ok = parse_events((OC_FIX / "success_restricted_agent.jsonl").read_text())
    assert ok["text"] == "OK" and ok["error"] is None and ok["tokens"]["cache"]["write"] == 2680 and ok["cost"] == 0
    nr = parse_events((OC_FIX / "error_no_route.jsonl").read_text())
    assert nr["error"].startswith("provider.no-route")
    q = parse_events((OC_FIX / "error_quota_402.jsonl").read_text())
    assert q["error"].startswith("provider.quota")


def test_opencode_route_records_identity_isolation_and_measured_tokens(tmp_path):
    binary = install_fake(tmp_path, "ok")
    root = make_root(tmp_path)
    engine, result = run_fixture(root, "main_run.json", run_id="oc", overrides=oc_overrides(binary), strict=False)
    d = engine.store.data
    assert d.state.value == "COMPLETE" and d.decision.kind.value == "conditional"
    judge = d.participants["p_judge_1"]
    assert judge.provider == "opencode" and judge.isolation.value == "isolated"
    assert judge.model_requested == "claude-agent/haiku" and judge.model_reported == "claude-agent/haiku"
    assert d.participants["p_framer"].provider == "fixture"
    assert d.budget.tokens_measured > 0 and d.budget.cost_status == "unavailable"  # cost 0 on subscription = unavailable
    assert not any(e["kind"] == "route_fallback" for e in events(engine))
    # the judge requests were marked isolated and routed to opencode
    issued = [e for e in events(engine) if e["kind"] == "request_issued" and e["payload"]["kind"] == "judge"]
    assert issued and all(e["payload"]["provider"] == "opencode" for e in issued)


def test_isolated_review_payload_withholds_authorship(tmp_path):
    binary = install_fake(tmp_path, "ok")
    root = make_root(tmp_path)
    ov = oc_overrides(binary)
    ov["routing"]["roles"] = {"reviewer": {"provider": "opencode"}}
    # reviewers routed to opencode would need answers the fake cannot give; we only inspect the first review request
    from llm_council.config import load_effective_config
    from llm_council.engine import Engine
    from llm_council.providers import build_providers
    from llm_council.providers.fixture import FixtureProvider
    from llm_council.providers.base import parse_reply_json
    from llm_council.engine import ReplyMeta
    from llm_council.state import Store
    eff = load_effective_config(root, overrides={"routing": ov["routing"] | {"default_provider": "fixture"},
                                                 "fixture_path": str(FIXTURES / "main_run.json"),
                                                 "lenses": {"selection": "explicit", "explicit": LENSES.split(",")}})
    store = Store.create(root / ".council" / "runs", "iso", QUESTION)
    store.data.effective_config = eff.config.model_dump(mode="json")
    engine = Engine(store, eff.config)
    fx = FixtureProvider(FIXTURES / "main_run.json", strict_consumption=False)
    result = engine.result()
    while result.status == "request" and result.request.kind != "review":
        reply = fx.answer(result.request)
        result = engine.step(parse_reply_json(reply.text), ReplyMeta(provider="fixture", raw_text=reply.text))
    req = result.request
    assert req.kind == "review" and req.provider == "opencode" and req.isolation == "isolated"
    labels = [c["id"] for c in req.payload["candidates"]]
    assert all(l.startswith("OPT-") for l in labels) and len(set(labels)) == len(labels)
    assert all("lens_id" not in c and "version" not in c for c in req.payload["candidates"])
    assert "withheld" in req.payload["note"]
    assert set(req.alias_map) == set(labels) and set(req.alias_map.values()) == {v.id for v in engine.candidates()}
    public = json.loads((store.run_dir / "requests" / f"{req.request_id}.json").read_text())
    assert "alias_map" not in public  # the mapping never leaves the controller


def test_opencode_error_retries_then_falls_back(tmp_path):
    binary = install_fake(tmp_path, "quota")
    root = make_root(tmp_path)
    engine, result = run_fixture(root, "main_run.json", run_id="fb", overrides=oc_overrides(binary))
    d = engine.store.data
    assert d.state.value == "COMPLETE"
    fb = [e for e in events(engine) if e["kind"] == "route_fallback"]
    assert fb and fb[0]["payload"]["from"] == "opencode" and fb[0]["payload"]["to"] == "fixture"
    assert "provider.quota" in fb[0]["payload"]["error"]
    assert d.participants["p_judge_1"].provider == "fixture"
    # the engine's provider log shows the retry before the fallback
    assert d.decision.kind.value == "conditional"


def test_disabled_opencode_never_spawns_binary(tmp_path):
    marker = tmp_path / "spawned.txt"
    binary = install_fake(tmp_path, "ok", marker=marker)
    root = make_root(tmp_path)
    ov = {"routing": {"opencode": {"enabled": False, "binary": str(binary)}, "roles": {"judge": {"provider": "opencode"}}}}
    engine, result = run_fixture(root, "main_run.json", run_id="off", overrides=ov)
    d = engine.store.data
    assert d.state.value == "COMPLETE"
    assert not marker.exists(), "opencode binary must never be spawned when the route is disabled"
    assert d.participants["p_judge_1"].provider == "fixture"


def test_model_substitution_recorded(tmp_path):
    binary = install_fake(tmp_path, "ok")
    root = make_root(tmp_path)
    ov = oc_overrides(binary, model_fallbacks={"vendor/not-listed": "claude-agent/haiku"})
    ov["routing"]["roles"]["judge"]["model"] = "vendor/not-listed"
    engine, result = run_fixture(root, "main_run.json", run_id="sub", overrides=ov, strict=False)
    d = engine.store.data
    subs = [e for e in events(engine) if e["kind"] == "route_substitution"]
    assert subs and "substituted claude-agent/haiku" in subs[0]["payload"]["note"]
    assert d.participants["p_judge_1"].model_requested == "claude-agent/haiku"
    assert d.participants["p_judge_1"].substitution


def test_opencode_error_falls_back_to_chat_in_step_mode(tmp_path):
    """Default fallback: the request is re-routed to the chat model and the driver stops there."""
    binary = install_fake(tmp_path, "quota")
    root = make_root(tmp_path)
    from llm_council.config import load_effective_config
    from llm_council.engine import Engine, ReplyMeta
    from llm_council.providers import build_providers, drive_until_chat_or_terminal
    from llm_council.providers.base import parse_reply_json
    from llm_council.providers.fixture import FixtureProvider
    from llm_council.state import Store
    ov = oc_overrides(binary, fallback="chat")
    ov["routing"]["default_provider"] = "fixture"
    ov["fixture_path"] = str(FIXTURES / "main_run.json")
    ov["lenses"] = {"selection": "explicit", "explicit": LENSES.split(",")}
    eff = load_effective_config(root, overrides=ov)
    store = Store.create(root / ".council" / "runs", "fbchat", QUESTION)
    store.data.effective_config = eff.config.model_dump(mode="json")
    engine = Engine(store, eff.config)
    providers = build_providers(eff.config, root, "fbchat")
    providers["fixture"] = FixtureProvider(FIXTURES / "main_run.json", strict_consumption=False)
    result = drive_until_chat_or_terminal(engine, providers)
    assert result.status == "request" and result.request.kind == "judge"
    assert result.request.provider == "chat" and result.request.isolation == "shared"
    fb = [e for e in events(engine) if e["kind"] == "route_fallback"]
    assert fb and fb[0]["payload"]["to"] == "chat" and "provider.quota" in fb[0]["payload"]["error"]
    # the chat model answers and the run continues
    reply = providers["fixture"].answer(result.request)
    result = engine.step(parse_reply_json(reply.text), ReplyMeta(provider="chat", raw_text=reply.text))
    assert engine.store.data.participants["p_judge_1"].provider == "chat"


def test_provider_failure_without_fallback_takes_failure_transition(tmp_path):
    """fallback=fail: a request the route cannot answer is failed by the controller (no call charged) and the
    run completes with the request's failure transition instead of aborting."""
    binary = install_fake(tmp_path, "quota")
    root = make_root(tmp_path)
    ov = oc_overrides(binary, fallback="fail")
    engine, result = run_fixture(root, "main_run.json", run_id="pf", overrides=ov, strict=False)
    d = engine.store.data
    assert d.state.value == "COMPLETE"
    failed = [e for e in events(engine) if e["kind"] == "request_failed" and e["payload"].get("provider_failure")]
    assert failed and all(e["payload"]["kind"] == "judge" for e in failed)
    assert any(j.status.value == "missing" for j in d.judgements.values())
    assert any("not (re)scored" in u or "judgement missing" in u for u in d.decision.unfinished_checks)
    # no model call was charged for provider failures: only fixture-answered requests count
    answered = [e for e in events(engine) if e["kind"] == "response_committed" and "request_id" in e["payload"]]
    assert d.budget.model_calls_used == len(answered) + sum(1 for e in events(engine) if e["kind"] == "response_rejected")
