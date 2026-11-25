from __future__ import annotations

import json

from conftest import events, make_root, run_fixture
from llm_council.ontology import RunState, StopReason


def test_malformed_then_valid_is_rejected_then_retried(tmp_path):
    root = make_root(tmp_path)
    engine, result = run_fixture(root, "schema_rejection.json", run_id="schema", lenses="")
    d = engine.store.data
    ev = events(engine)
    rejected = [e for e in ev if e["kind"] == "response_rejected"]
    assert [r["payload"]["kind"] for r in rejected] == ["frame", "policy"]
    assert "schema validation failed" in rejected[0]["payload"]["error"]
    assert "unexpected" in rejected[0]["payload"]["error"] or "stakes" in rejected[0]["payload"]["error"]
    assert "__unparseable__" in rejected[1]["payload"]["error"] or "schema validation failed" in rejected[1]["payload"]["error"]
    retried = [e for e in ev if e["kind"] == "request_issued" and e["payload"].get("retry_of")]
    assert len(retried) == 2 and all(e["payload"]["attempt"] == 2 for e in retried)
    # the run proceeds: trivial decision answered directly after round zero
    assert d.state == RunState.COMPLETE and d.stop_reason == StopReason.TRIVIAL_QUESTION
    assert len(d.briefs) == 1 and len(d.policies) == 1
    # rejected submissions still cost a model call
    assert d.budget.model_calls_used == 7  # 2 frame + 2 policy + 1 baseline + 2 judge


def test_retries_exhausted_fails_run_with_event_not_record(tmp_path):
    root = make_root(tmp_path)
    engine, result = run_fixture(root, "retries_exhausted.json", run_id="retries", lenses="", strict=False)
    d = engine.store.data
    assert d.state == RunState.FAILED and d.stop_reason == StopReason.FAILED
    assert "frame request failed after 2 attempts" in d.failure_reason
    ev = events(engine)
    assert sum(1 for e in ev if e["kind"] == "response_rejected") == 2
    assert any(e["kind"] == "request_failed" for e in ev)
    # failures never become deliberation records
    assert not d.briefs and not d.challenges and not d.responses and not d.option_versions
    assert d.budget.model_calls_used == 2


def test_malformed_ids_are_renamed_and_remapped(tmp_path):
    """Models often write ids like 'E1'; the controller renames them and remaps references in the same response."""
    from llm_council.phases import Applier, FrameResponse, OptionDraft
    from llm_council.state import PendingRequest, RunData, Store
    from llm_council.ontology import Role, RunState
    store = Store(tmp_path / "r", RunData(run_id="r", question="q"))
    req = PendingRequest(request_id="req_1", attempt=1, kind="frame", role="framer", round=0, state="FRAMING",
                         participant_id="p_framer", dedup_key="k")
    ap = Applier(store, req)
    ap.apply_frame(FrameResponse(decision_statement="decide something concrete here", objectives=["o"], time_horizon="Q1",
                                 stakes="high", reversibility="costly",
                                 user_facts=[{"id": "E1", "statement": "budget is 400k", "source": {"kind": "user"}, "verification_status": "user_supplied"}]))
    assert "ev_e1" in store.data.evidence and ap.remap["E1"] == "ev_e1"
    req2 = PendingRequest(request_id="req_2", attempt=1, kind="generate", role="strategist", round=1, state="GENERATING",
                          participant_id="p_strategist_x", dedup_key="k2", lens_id="inversion")
    ap2 = Applier(store, req2)
    draft = OptionDraft.model_validate({"id": "OPT-A", "option_id": "A", "title": "Option alpha", "summary": "a summary that is long enough",
                                        "claims": [{"id": "C1", "text": "cites the budget", "evidence_ids": ["ev_e1"]}],
                                        "generation_note": {"how": "test"}})
    out = ap2.apply_options([draft], [], lens_id="inversion", round_no=1)
    v = out[0]
    assert v.id == "optv_opt_a" and v.option_id == "opt_a" and v.claim_ids == ["clm_c1"]
    assert store.data.claims["clm_c1"].evidence_ids == ["ev_e1"]


def test_existing_assumption_and_evidence_ids_are_references(tmp_path):
    from llm_council.phases import Applier, FrameResponse, OptionDraft, EvidenceDraft
    from llm_council.state import PendingRequest, RunData, Store
    store = Store(tmp_path / "r", RunData(run_id="r", question="q"))
    req = PendingRequest(request_id="req_1", attempt=1, kind="frame", role="framer", round=0, state="FRAMING", participant_id="p_framer", dedup_key="k")
    Applier(store, req).apply_frame(FrameResponse(decision_statement="decide something concrete here", objectives=["o"], time_horizon="Q1",
                                                  stakes="high", reversibility="costly",
                                                  user_facts=[{"id": "ev_budget", "statement": "budget", "source": {"kind": "user"}, "verification_status": "user_supplied"}]))
    req2 = PendingRequest(request_id="req_2", attempt=1, kind="baseline", role="strategist", round=0, state="BASELINE", participant_id="p_strategist_direct", dedup_key="k2", lens_id="direct")
    ap = Applier(store, req2)
    d1 = OptionDraft.model_validate({"id": "optv_a", "option_id": "opt_a", "title": "Option alpha", "summary": "a summary that is long enough",
                                     "assumptions": [{"id": "asm_shared", "text": "shared assumption"}], "generation_note": {"how": "t"}})
    ap.apply_options([d1], [], lens_id="direct", round_no=0)
    req3 = PendingRequest(request_id="req_3", attempt=1, kind="generate", role="strategist", round=1, state="GENERATING", participant_id="p_strategist_x", dedup_key="k3", lens_id="inversion")
    ap2 = Applier(store, req3)
    d2 = OptionDraft.model_validate({"id": "optv_b", "option_id": "opt_b", "title": "Option beta", "summary": "another summary long enough",
                                     "assumptions": [{"id": "asm_shared", "text": "shared assumption restated"}, {"id": "asm_new", "text": "new"}],
                                     "generation_note": {"how": "t"}})
    ev = [EvidenceDraft.model_validate({"id": "ev_budget", "statement": "budget again", "source": {"kind": "user"}, "verification_status": "user_supplied"})]
    out = ap2.apply_options([d2], ev, lens_id="inversion", round_no=1)
    assert out[0].assumption_ids == ["asm_shared", "asm_new"]
    assert len(store.data.evidence) == 1 and len(store.data.assumptions) == 2


def test_parse_reply_json_tolerates_prose_and_fences():
    from llm_council.providers.base import parse_reply_json
    assert parse_reply_json('Here is the answer:\n```json\n{"a": 1}\n```\nThanks.') == {"a": 1}
    assert parse_reply_json('Sure! {"a": {"b": [1, 2]}} done') == {"a": {"b": [1, 2]}}
    assert "__unparseable__" in parse_reply_json("no json here")
    assert "__unparseable__" in parse_reply_json('{"a": 1')


def test_claim_kind_synonyms_are_coerced():
    from llm_council.phases import ClaimDraft
    assert ClaimDraft(text="x", kind="computation").kind.value == "inference"
    assert ClaimDraft(text="x", kind="Estimate").kind.value == "prediction"
    assert ClaimDraft(text="x", kind="data").kind.value == "fact"
    assert ClaimDraft(text="x", kind="whatever").kind.value == "inference"


def test_review_evidence_may_reference_a_challenge_created_in_the_same_response(tmp_path):
    from llm_council.phases import Applier, FrameResponse, OptionDraft, ReviewResponse
    from llm_council.state import PendingRequest, RunData, Store
    store = Store(tmp_path / "r", RunData(run_id="r", question="q"))
    Applier(store, PendingRequest(request_id="r1", attempt=1, kind="frame", role="framer", round=0, state="FRAMING", participant_id="p_framer", dedup_key="k")).apply_frame(
        FrameResponse(decision_statement="decide something concrete here", objectives=["o"], time_horizon="Q1", stakes="high", reversibility="costly"))
    ap = Applier(store, PendingRequest(request_id="r2", attempt=1, kind="baseline", role="strategist", round=0, state="BASELINE", participant_id="p_strategist_direct", dedup_key="k2", lens_id="direct"))
    ap.apply_options([OptionDraft.model_validate({"id": "optv_a", "option_id": "opt_a", "title": "Option alpha", "summary": "a summary that is long enough", "generation_note": {"how": "t"}})], [], lens_id="direct", round_no=0)
    rv = Applier(store, PendingRequest(request_id="r3", attempt=1, kind="review", role="reviewer", round=1, state="REVIEWING", participant_id="p_reviewer_1", dedup_key="k3"))
    resp = ReviewResponse.model_validate({"challenges": [{"id": "chl_new", "target_ref": "optv_a", "mechanism": "breaks because of X", "severity": "material",
                                                           "challenge_class": "factual", "could_change": "ranking", "evidence_ids": ["ev_new"]}],
                                          "evidence": [{"id": "ev_new", "statement": "fact", "source": {"kind": "url", "ref": "x"}, "verification_status": "verified", "challenge_id": "chl_new"}]})
    chs, _ = rv.apply_review(resp, round_no=1)
    assert chs[0].id == "chl_new" and store.data.evidence["ev_new"].challenge_id == "chl_new"
    assert store.data.challenges["chl_new"].evidence_ids == ["ev_new"]


def test_user_named_options_flow_from_frame_to_baseline_payload(tmp_path):
    from conftest import FIXTURES, LENSES, QUESTION, make_root
    from llm_council.config import load_effective_config
    from llm_council.engine import Engine, ReplyMeta
    from llm_council.providers.base import parse_reply_json
    from llm_council.providers.fixture import FixtureProvider
    from llm_council.state import Store
    import json
    root = make_root(tmp_path)
    eff = load_effective_config(root, overrides={"lenses": {"selection": "explicit", "explicit": LENSES.split(",")}})
    store = Store.create(root / ".council" / "runs", "uno", QUESTION)
    store.data.effective_config = eff.config.model_dump(mode="json")
    engine = Engine(store, eff.config)
    fx = FixtureProvider(FIXTURES / "main_run.json", strict_consumption=False)
    result = engine.result()
    frame = json.loads(fx.answer(result.request).text)
    frame["user_named_options"] = ["shift 30% to video", "keep search"]
    result = engine.step(frame, ReplyMeta(provider="chat"))
    result = engine.step(parse_reply_json(fx.answer(result.request).text), ReplyMeta(provider="chat"))
    assert result.request.kind == "baseline"
    assert result.request.payload["user_named_options"] == ["shift 30% to video", "keep search"]
    assert store.current_brief().user_named_options == ["shift 30% to video", "keep search"]


def test_validation_fallback_model_answers_after_retries_are_exhausted(tmp_path):
    """After retries.max_attempts rejected replies, the request goes to the configured fallback models in order
    (one attempt each) instead of failing; the fallback sees the previous error and the discussion."""
    root = make_root(tmp_path)
    engine, result = run_fixture(root, "validation_fallback.json", run_id="vfb", lenses="staging,information_option,asymmetric_upside",
                                 preset="first_pass", overrides={"routing": {"validation_fallbacks": ["fixture"]}})
    d = engine.store.data
    ev = events(engine)
    assert d.state == RunState.COMPLETE and d.failure_reason is None
    fb = [e for e in ev if e["kind"] == "route_fallback"]
    assert len(fb) == 1 and fb[0]["payload"]["reason"] == "validation" and fb[0]["payload"]["to"] == "fixture:" and fb[0]["payload"]["fallback_index"] == 1
    issued = [e for e in ev if e["kind"] == "request_issued" and e["payload"].get("validation_fallback")]
    assert len(issued) == 1 and issued[0]["payload"]["attempt"] == 3
    req = json.loads((engine.store.run_dir / "requests" / issued[0]["payload"]["request_id"] + ".json").read_text()) if False else None
    files = sorted((engine.store.run_dir / "requests").glob("req_0003.json"))
    payload = json.loads(files[0].read_text())["payload"]
    assert "previous_attempt_error" in payload and "fallback model 1" in payload["note"]
    rejected = [e for e in ev if e["kind"] == "response_rejected"]
    assert len(rejected) == 2 and all(e["payload"]["kind"] == "frame" for e in rejected)
    assert d.briefs and list(d.briefs.values())[0].decision_statement.startswith("Decide how much")


def test_validation_fallbacks_are_validated_and_exhausted_fallbacks_still_fail(tmp_path):
    from pydantic import ValidationError
    from llm_council.config import CouncilConfig
    try:
        CouncilConfig.model_validate({"routing": {"validation_fallbacks": ["gpt-6.2-sol"]}})
        assert False
    except ValidationError:
        pass
    CouncilConfig.model_validate({"routing": {"validation_fallbacks": ["openai/gpt-6.2-sol", "muse-code/muse-spark-1.3-contributor", "fixture"]}})
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, "retries_exhausted.json", run_id="vfb2", lenses="", strict=False, overrides={"routing": {"validation_fallbacks": ["fixture"]}})
    d = engine.store.data
    assert d.state == RunState.FAILED and "frame request failed after 3 attempts" in d.failure_reason
