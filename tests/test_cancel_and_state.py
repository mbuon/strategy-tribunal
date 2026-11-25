from __future__ import annotations

import json

from conftest import FIXTURES, LENSES, QUESTION, make_root
from llm_council.config import CouncilConfig, load_effective_config
from llm_council.engine import Engine, ReplyMeta
from llm_council.ontology import RunState, StopReason
from llm_council.providers.base import parse_reply_json
from llm_council.providers.fixture import FixtureProvider
from llm_council.state import Store


def _setup(root, run_id):
    ov = {"routing": {"default_provider": "chat"}, "lenses": {"selection": "explicit", "explicit": LENSES.split(",")}}
    eff = load_effective_config(root, overrides=ov)
    store = Store.create(root / ".council" / "runs", run_id, QUESTION)
    store.data.effective_config = eff.config.model_dump(mode="json")
    store.save()
    return Engine(store, eff.config), eff.config


def _answer(engine, fixture, result):
    reply = fixture.answer(result.request)
    return engine.step(parse_reply_json(reply.text), ReplyMeta(provider="chat", raw_text=reply.text))


def test_cancellation_mid_run_produces_partial_report(tmp_path):
    root = make_root(tmp_path)
    engine, cfg = _setup(root, "cancel")
    fixture = FixtureProvider(FIXTURES / "main_run.json", strict_consumption=False)
    result = engine.result()
    for _ in range(12):
        result = _answer(engine, fixture, result)
    assert result.status == "request" and engine.store.data.round >= 1
    (engine.store.run_dir / ".cancel").write_text("stop\n")
    # the controller checks the flag before issuing any further request
    engine.store.data.pending_request = None
    result = engine.result()
    d = engine.store.data
    assert result.status == "terminal" and d.state == RunState.CANCELLED
    assert d.stop_reason == StopReason.CANCELLED
    assert d.decision is not None and d.decision.stop_reason == StopReason.CANCELLED
    assert any("cancelled while in" in u for u in d.decision.unfinished_checks)
    assert (engine.store.run_dir / "report.md").exists()


def test_resume_from_snapshot_reproduces_identical_outcome(tmp_path):
    root = make_root(tmp_path)
    engine, cfg = _setup(root, "resume")
    fixture = FixtureProvider(FIXTURES / "main_run.json")
    result = engine.result()
    for _ in range(9):
        result = _answer(engine, fixture, result)
    pending_before = result.request.model_dump()
    # drop the in-memory engine and reload from disk
    store2 = Store.load(root / ".council" / "runs", "resume")
    engine2 = Engine(store2, CouncilConfig.model_validate(store2.data.effective_config))
    result2 = engine2.result()
    assert result2.status == "request" and result2.request.model_dump() == pending_before
    while result2.status == "request":
        result2 = _answer(engine2, fixture, result2)
    fixture.finish()
    d = engine2.store.data
    assert d.state == RunState.COMPLETE and d.decision.kind.value == "conditional"
    assert d.budget.model_calls_used == 32
    # events.jsonl is append-only and consistent with the state
    lines = (engine2.store.run_dir / "events.jsonl").read_text().splitlines()
    kinds = [json.loads(l)["kind"] for l in lines]
    assert kinds[0] == "run_created" and kinds[-1] == "phase_entered" and "run_finished" in kinds


def test_duplicate_submission_is_rejected_without_mutation(tmp_path):
    root = make_root(tmp_path)
    engine, cfg = _setup(root, "dedup")
    fixture = FixtureProvider(FIXTURES / "main_run.json", strict_consumption=False)
    result = engine.result()
    reply = fixture.answer(result.request)
    key = result.request.dedup_key
    result = engine.step(parse_reply_json(reply.text), ReplyMeta(provider="chat", raw_text=reply.text))
    assert engine.store.dedup_lookup(key)["outcome"] == "committed"
    briefs_before = dict(engine.store.data.briefs)
    calls_before = engine.store.data.budget.model_calls_used
    # submitting again for the already-answered request: the request is no longer pending
    import pytest
    from llm_council.state import RejectedUpdate
    engine.store.data.pending_request = None
    with pytest.raises(RejectedUpdate):
        engine.step(parse_reply_json(reply.text), ReplyMeta(provider="chat", raw_text=reply.text))
    assert engine.store.data.briefs == briefs_before and engine.store.data.budget.model_calls_used == calls_before
