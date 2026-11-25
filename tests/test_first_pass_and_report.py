from __future__ import annotations

from conftest import events, make_root, run_fixture
from llm_council.ontology import RunState, StopReason


def test_first_pass_preset_runs_generation_and_judging_only(tmp_path):
    root = make_root(tmp_path)
    engine, result = run_fixture(root, "first_pass.json", run_id="fp", preset="first_pass")
    d = engine.store.data
    assert d.state == RunState.COMPLETE and d.stop_reason == StopReason.MAX_ROUNDS
    kinds = {e["payload"]["kind"] for e in events(engine) if e["kind"] == "request_issued"}
    assert kinds == {"frame", "policy", "baseline", "judge", "generate"}
    assert not d.challenges and not d.leader_challenges
    assert d.incumbent_version_id == "optv_C_v1" and d.decision.kind.value in ("firm", "shortlist")
    assert d.budget.model_calls_used == 11


def test_decision_fields_and_report_sections(tmp_path):
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, "main_run.json", run_id="rep")
    dec = engine.store.data.decision
    assert dec.recommended_version_id and dec.alternatives and dec.next_action and dec.reversal_conditions
    assert dec.confidence.basis and dec.round_history and dec.completed_phases
    assert dec.trade_offs and dec.decisive_evidence_ids
    report = (engine.store.run_dir / "report.md").read_text()
    for section in ("## Outcome:", "## Strongest alternatives", "## Decisive evidence", "## Material dissent",
                    "## Trade-offs", "## Round-by-round decision quality", "## Signals", "## Reopen or reverse when",
                    "## What the council failed to establish", "## Lineage", "## Budget", "## Limitations"):
        assert section in report, section
    assert "**Stopping reason:** stable" in report
    assert "(non-comparable)" in report  # round 0 has no prior incumbent
    # material objections and minority positions survive summarisation
    assert "chl_shared_capacity" in report and "dis_0001" in report


def test_unexamined_action_level_objection_prevents_a_firm_outcome(tmp_path):
    """A budget stop can leave an action-level objection against the leader unexamined; the decision must then be
    conditional, not firm, and the objection must appear as decisive uncertainty."""
    from conftest import make_root, run_fixture
    from llm_council.ontology import Challenge, ChallengeClass, CouldChange, Role, Severity
    from llm_council.report import build_decision
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, "main_run_resolved.json", run_id="unex")
    d = engine.store.data
    assert d.decision.kind.value == "firm"
    ch = Challenge(id="chl_unexamined", target_ref="__all__", mechanism="never examined action-level objection", severity=Severity.MATERIAL,
                   challenge_class=ChallengeClass.EXECUTION, could_change=CouldChange.ACTION, requires_verification=True, round=4,
                   author_participant_id="p_reviewer_1", author_role=Role.REVIEWER)
    engine.store.commit(ch)
    dec = build_decision(engine)
    assert dec.kind.value == "conditional"
    assert any("chl_unexamined (unexamined)" in u for u in dec.signals.decisive_uncertainty)
    assert dec.confidence.level.value != "high"


def test_report_states_the_decision_plainly_and_is_at_least_600_words(tmp_path):
    from llm_council.report import MIN_REPORT_WORDS
    assert MIN_REPORT_WORDS >= 600
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, "main_run.json", run_id="rep600")
    d = engine.store.data
    report = (engine.store.run_dir / "report.md").read_text()
    assert "## In plain words" in report
    plain = report.split("## In plain words")[1]
    assert d.option_versions[d.decision.recommended_version_id].title in plain  # the decision, named
    assert "What that means in practice" in plain and "The honest caveats" in plain
    assert len(report.split()) >= MIN_REPORT_WORDS
    # the floor holds for the smallest preset too
    root2 = make_root(tmp_path, name="proj2")
    engine2, _ = run_fixture(root2, "first_pass.json", run_id="fp600", preset="first_pass")
    report2 = (engine2.store.run_dir / "report.md").read_text()
    assert "## In plain words" in report2 and len(report2.split()) >= MIN_REPORT_WORDS
