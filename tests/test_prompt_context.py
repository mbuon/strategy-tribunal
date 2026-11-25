"""What a model receives is complete enough to answer: context block, capabilities, valid targets, blind discussion,
repair retries, partial acceptance, schema descriptions, auto-detected documents, follow-up prompt."""
from __future__ import annotations

import json
from pathlib import Path

from conftest import FIXTURES, LENSES, make_root, run_fixture
from llm_council.config import CouncilConfig
from llm_council.discussion import discussion_payload, paths_in_text, register_question_documents
from llm_council.phases import RESPONSE_MODELS, Applier, ReviewResponse
from llm_council.providers.base import parse_reply_json, repair_json_text
from llm_council.state import PendingRequest, RejectedUpdate


def _requests(run_dir: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((run_dir / "requests").glob("req_*.json"))]


def test_every_request_explains_the_council_the_role_and_what_the_model_can_do(tmp_path):
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, FIXTURES / "main_run.json", lenses=LENSES, run_id="ctx")
    reqs = _requests(engine.store.run_dir)
    first = reqs[0]
    ins = first["instructions"]
    assert ins.startswith("How the council works:") and "FRAMING (framer)" in ins and "REPORTING" in ins
    assert "You are in FRAMING, round 0 of at most" in ins
    assert "The policy setter derives gates from your hard constraints" in ins          # who consumes the reply
    assert "gate = must-pass criterion" in ins and "OPT-n" in ins                        # terms and aliases explained
    assert "You have no tools" in ins                                                    # fixture route: no tools
    assert "language of the user's question" in ins and "builds_on" in ins
    caps = first["payload"]["capabilities"]
    assert caps["tools"] == "none" and caps["can_read_files"] is False and len(caps["today"]) == 10
    # the review request lists what may be targeted, and the judge is told the ranking is withheld
    review = next(r for r in reqs if r["kind"] == "review")
    valid = review["payload"]["valid_target_ids"]
    assert "__all__" in valid and any(v.startswith("optv_") for v in valid) and any(v.startswith("clm_") for v in valid)
    assert any(v.startswith("asm_") for v in valid)
    assert "At most 6 challenges" in review["instructions"]
    judge = next(r for r in reqs if r["kind"] == "judge" and r["round"] >= 1)
    assert "the ranking is withheld from you on purpose" in judge["instructions"]
    disc = judge["payload"]["discussion_so_far"]
    assert disc["policy"] == "summaries" and all(len(c["says"]) <= 430 for c in disc["contributions"])
    assert all("Ranking:" not in x["controller_digest"] for x in disc["earlier_rounds"])  # no scores for judges
    # a reviewer's payload already carries the candidates: the strategists' contributions come as summaries, flagged
    cur = [c for c in review["payload"]["discussion_so_far"]["contributions"] if c["round"] == review["round"] and c["role"] == "strategist"]
    assert cur and all(c.get("see_payload") is True and len(c["says"]) <= 430 for c in cur)


def test_schemas_document_every_field_and_the_response_models_accept_builds_on():
    for kind, model in RESPONSE_MODELS.items():
        schema = json.dumps(model.model_json_schema())
        assert schema.count('"description"') >= 3, kind
        assert "builds_on" in schema, kind
    target = ReviewResponse.model_json_schema()["$defs"]["ChallengeDraft"]["properties"]["target_ref"]["description"]
    assert "valid_target_ids" in target and "asm_" in target


def test_repair_handles_the_slips_that_rejected_real_replies():
    assert parse_reply_json('{"evidence_ids": ["ev_a", ("ev_b")], "n": 1,}') == {"evidence_ids": ["ev_a", "ev_b"], "n": 1}
    assert parse_reply_json('Here it is:\n```json\n{"a": [1, 2,]}\n```\nthanks') == {"a": [1, 2]}
    assert parse_reply_json('{"q": “smart”}') == {"q": "smart"}
    assert repair_json_text('{"ok": true}') == '{"ok": true}'
    bad = parse_reply_json("not json at all")
    assert "__unparseable__" in bad


def test_retry_carries_the_previous_reply_and_asks_for_a_repair(tmp_path):
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, FIXTURES / "schema_rejection.json", lenses=LENSES, run_id="rep", strict=False)
    reqs = _requests(engine.store.run_dir)
    retry = next(r for r in reqs if r["attempt"] == 2)
    assert retry["payload"]["previous_attempt_error"] and retry["payload"]["previous_reply"]
    assert "Repair: your previous reply" in retry["instructions"]
    assert "capabilities" in retry["payload"] and "previous_reply" not in reqs[0]["payload"]


def test_review_commits_the_valid_challenges_and_reports_the_dropped_ones(tmp_path):
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, FIXTURES / "main_run.json", lenses=LENSES, run_id="partial")
    store = engine.store
    d = store.data
    v = next(x for x in d.option_versions.values() if x.assumption_ids)
    asm = v.assumption_ids[0]
    req = PendingRequest(request_id="req_t", attempt=1, kind="review", role="reviewer", round=d.round, state="REVIEWING",
                         participant_id="p_reviewer_9", dedup_key="t", match_hints={}, instructions="", payload={},
                         response_model="ReviewResponse", response_schema={}, provider="fixture")
    r = ReviewResponse.model_validate({"challenges": [
        {"target_ref": v.id, "mechanism": "valid target, unknown evidence id is ignored", "severity": "material",
         "challenge_class": "execution", "could_change": "ranking", "evidence_ids": ["ev_does_not_exist"]},
        {"target_ref": asm, "mechanism": "an assumption lands on its option", "severity": "minor",
         "challenge_class": "factual", "could_change": "none"},
        {"target_ref": "asm_invented", "mechanism": "this one is dropped", "severity": "critical",
         "challenge_class": "factual", "could_change": "eligibility"},
    ], "dissent": [{"position": "x", "against_ref": "optv_nope", "reason": "r"}], "builds_on": ["D3"]})
    store.begin()
    try:
        ap = Applier(store, req)
        challenges, dissents = ap.apply_review(r, round_no=d.round)
        assert len(challenges) == 2 and not dissents
        assert challenges[1].target_ref == v.id and challenges[1].mechanism.startswith(f"[assumption {asm}]")
        assert challenges[0].evidence_ids == []
        notes = "\n".join(ap.notes)
        assert "unknown evidence ids ignored: ev_does_not_exist" in notes and "'asm_invented' dropped" in notes and "dissent against unknown ref" in notes
        # nothing valid at all: the reply is rejected so the model can retry
        try:
            Applier(store, req).apply_review(ReviewResponse.model_validate({"challenges": [
                {"target_ref": "optv_ghost", "mechanism": "nothing valid here", "severity": "minor", "challenge_class": "factual", "could_change": "none"}]}), round_no=d.round)
        except RejectedUpdate as e:
            assert "every challenge was dropped" in str(e)
        else:
            raise AssertionError("an all-invalid review must be rejected")
    finally:
        store.rollback()


def test_blind_discussion_withholds_authorship_and_scores(tmp_path):
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, FIXTURES / "main_run.json", lenses=LENSES, run_id="blind")
    cfg = CouncilConfig.model_validate(engine.store.data.effective_config | {"discussion": {"include": "full", "max_chars": 2_000_000}})
    open_disc = discussion_payload(engine.store, cfg)
    blind = discussion_payload(engine.store, cfg, blind=True, hide_scores=True)
    assert all("participant" in c for c in open_disc["contributions"])
    assert all("participant" not in c for c in blind["contributions"])
    # transcript headers (who answered, which model) never travel in the payload text; the open form carries the participant key
    assert not any("answered by" in c["says"] or c["says"].startswith("# D") for c in open_disc["contributions"] + blind["contributions"])
    assert any("Ranking:" in x["controller_digest"] for x in open_disc["earlier_rounds"])
    assert not any("Ranking:" in x["controller_digest"] for x in blind["earlier_rounds"])
    assert all("open objection" in x["controller_digest"] for x in blind["earlier_rounds"])


def test_paths_named_in_the_question_become_documents(tmp_path):
    root = make_root(tmp_path)
    folder = tmp_path / "question_docs"
    folder.mkdir()
    (folder / "README.md").write_text("# Proj\nAn Italian ordering platform for restaurants.\n")
    q = f'read "{folder}" and find the best marketing strategies; ignore /nonexistent/path and ~/also-missing.'
    assert paths_in_text(q) == [str(folder)]
    assert paths_in_text("no path here") == []
    from llm_council.state import Store
    cfg = CouncilConfig()
    store = Store.create(root / "council_outcomes", "auto", q)
    ids = register_question_documents(store, cfg, q)
    assert ids == ["ev_doc_README"] or (len(ids) == 1 and ids[0].startswith("ev_doc_"))
    index = (store.run_dir / "inputs" / "INDEX.md").read_text()
    assert "auto-detected from the question" in index and str(folder) in index
    assert store.data.evidence[ids[0]].source.ref.endswith("README.md")


def test_report_ends_with_a_copyable_follow_up_prompt(tmp_path):
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, FIXTURES / "main_run.json", lenses=LENSES, run_id="fu")
    from llm_council.report import followup_prompt
    dec = engine.store.data.decision
    text = followup_prompt(engine, dec)
    assert text.startswith("Continue from the council decision below.")
    assert "Recommended action: Staged 10% pilot" in text and "Your task now:" in text and "Next action the council named:" in text
    assert "Reverse or reopen if:" in text and "run folder" in text
    report = (engine.store.run_dir / "report.md").read_text()
    assert "## Follow-up prompt (copy into the chat to continue)" in report and text in report
    from llm_council.dashboard import build_context, dashboard_state
    state = dashboard_state(build_context(engine), served=True, full=True)
    assert state["followUp"] == text
    web = Path(__file__).resolve().parent.parent / "web" / "src" / "components"
    assert "FollowUp" in (web / "RunDashboard.jsx").read_text() and "clipboard" in (web / "FollowUp.jsx").read_text()
