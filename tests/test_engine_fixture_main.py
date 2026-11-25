"""Run 1 handoff gate: the main deterministic fixture exercises multiple rounds, a
material promotion, a rejected regression, a matched rescore after an evidence
change, an unresolved challenge that changes the final action, and a recorded
stopping reason. The fixture only supplies role outputs; every assertion below
is about what the controller computed."""

from __future__ import annotations

import pytest

from conftest import events, make_root, run_fixture
from llm_council.judge import promotion
from llm_council.ontology import DecisionOutcomeKind, PromotionOutcome, RunState, StopReason


@pytest.fixture(scope="module")
def main(tmp_path_factory):
    root = make_root(tmp_path_factory.mktemp("main"))
    engine, result = run_fixture(root, "main_run.json", run_id="main")
    return engine, result


@pytest.fixture(scope="module")
def twin(tmp_path_factory):
    root = make_root(tmp_path_factory.mktemp("twin"))
    engine, result = run_fixture(root, "main_run_resolved.json", run_id="twin")
    return engine, result


def summaries(engine):
    return {s.round: s for s in engine.store.data.round_summaries.values()}


def test_run_completes_with_recorded_stop_reason(main):
    engine, result = main
    d = engine.store.data
    assert result.status == "terminal" and d.state == RunState.COMPLETE
    assert d.stop_reason == StopReason.STABLE
    assert d.decision is not None and d.decision.stop_reason == StopReason.STABLE
    assert any(e["kind"] == "stop_decided" and e["payload"]["reason"] == "stable" for e in events(engine))


def test_multiple_rounds(main):
    engine, _ = main
    s = summaries(engine)
    assert sorted(s) == [0, 1, 2, 3, 4]


def test_material_promotion_round_1(main):
    engine, _ = main
    s = summaries(engine)
    assert s[0].incumbent_version_id == "optv_A_v1" and s[0].promotion_outcome == PromotionOutcome.BASELINE
    r1 = s[1]
    assert r1.promotion_outcome == PromotionOutcome.PROMOTED
    assert r1.incumbent_version_id == "optv_C_v1" and r1.prior_incumbent_version_id == "optv_A_v1"
    assert r1.delta_vs_prior_incumbent.comparable and r1.delta_vs_prior_incumbent.value == pytest.approx(1.4)
    assert r1.net_vs_round0.comparable and r1.net_vs_round0.value == pytest.approx(1.4)
    changes = [e for e in events(engine) if e["kind"] == "incumbent_changed"]
    assert [c["payload"]["to"] for c in changes] == ["optv_A_v1", "optv_C_v1"]


def test_rejected_regression_round_2(main):
    engine, _ = main
    r2 = summaries(engine)[2]
    assert r2.challenger_version_id == "optv_C_v2"
    assert r2.promotion_outcome == PromotionOutcome.RETAINED_LOSS
    assert r2.incumbent_version_id == "optv_C_v1"
    assert r2.delta_vs_parent.comparable and r2.delta_vs_parent.value == pytest.approx(-0.6)
    # the regression stays available as an alternative with lineage intact
    v2 = engine.store.data.option_versions["optv_C_v2"]
    assert v2.parent_version_id == "optv_C_v1" and v2.status.value == "active"
    assert any(r.kind.value == "supersedes" and r.from_id == "optv_C_v2" and r.to_id == "optv_C_v1" for r in engine.store.data.relations)


def test_matched_rescore_after_evidence_change(main):
    engine, _ = main
    d = engine.store.data
    snaps = [e["payload"] for e in events(engine) if e["kind"] == "evidence_snapshot_changed"]
    assert snaps[-1]["to"] == "snap-3" and snaps[-1]["evidence_id"] == "ev_bench"
    keys_c1 = {j.comparison_key.evidence_snapshot_id for j in d.judgements.values() if j.option_version_id == "optv_C_v1"}
    assert keys_c1 == {"snap-2", "snap-3"}, "incumbent must be rescored under the new snapshot"
    keys_c2 = {j.comparison_key.evidence_snapshot_id for j in d.judgements.values() if j.option_version_id == "optv_C_v2"}
    assert keys_c2 == {"snap-3"}
    r2 = summaries(engine)[2]
    assert r2.comparison_key.evidence_snapshot_id == "snap-3" and r2.comparable
    # apparent vs matched improvement: C v1 moved 7.4 -> 7.7 purely from evidence
    c1_old = engine.combined("optv_C_v1", r2.comparison_key.model_copy(update={"evidence_snapshot_id": "snap-2"}))
    c1_new = engine.combined("optv_C_v1", r2.comparison_key)
    assert c1_old.aggregate == pytest.approx(7.4) and c1_new.aggregate == pytest.approx(7.7)
    # a mixed-snapshot comparison is refused
    c2_new = engine.combined("optv_C_v2", r2.comparison_key)
    outcome, note = promotion(c1_old, c2_new, engine.cfg.judge)
    assert outcome == PromotionOutcome.NON_COMPARABLE and "keys differ" in note
    # round 0 baseline also rescored, so the net change is comparable
    assert r2.net_vs_round0.comparable and r2.net_vs_round0.value == pytest.approx(1.7)


def test_unresolved_challenge_changes_final_action(main, twin):
    engine, _ = main
    dec = engine.store.data.decision
    lcs = list(engine.store.data.leader_challenges.values())
    assert len(lcs) == 1 and lcs[0].status.value == "unresolved_final" and lcs[0].could_alter_outcome
    mirror = lcs[0].related_challenge_ids[0]
    assert dec.kind == DecisionOutcomeKind.CONDITIONAL
    assert mirror in dec.unresolved_challenge_ids
    assert any(lcs[0].id in u for u in dec.signals.decisive_uncertainty)
    assert "capacity" in dec.next_action.lower()
    assert any(lcs[0].id in u or "unresolved" in u for u in dec.unfinished_checks)
    # twin fixture: same run, challenge rebutted with qualifying evidence -> firm
    tengine, _ = twin
    tdec = tengine.store.data.decision
    assert tdec.kind == DecisionOutcomeKind.FIRM and tdec.confidence.level.value == "high"
    assert tdec.recommended_version_id == dec.recommended_version_id == "optv_C_v1"
    assert list(tengine.store.data.leader_challenges.values())[0].status.value == "resolved"
    # the reply's verified evidence changed the snapshot: every candidate was rescored before reporting
    assert tengine.store.data.evidence_snapshot_id == "snap-4"
    assert not tdec.unfinished_checks and tengine.store.data.budget.model_calls_used == 37
    assert tengine.store.data.challenges["chl_shared_capacity"].status.value == "resolved"


def test_generation_precedes_review_and_shared_mode_recorded(main):
    engine, _ = main
    issued = [e for e in events(engine) if e["kind"] == "request_issued"]
    gen_idx = [i for i, e in enumerate(issued) if e["payload"]["kind"] == "generate"]
    rev_idx = [i for i, e in enumerate(issued) if e["payload"]["kind"] == "review"]
    assert max(gen_idx) < min(rev_idx)
    dec = engine.store.data.decision
    assert any("Shared context" in l for l in dec.limitations)
    assert all(p.isolation.value == "shared" for p in engine.store.data.participants.values())


def test_signals_reported_separately(main):
    engine, _ = main
    s = engine.store.data.decision.signals
    assert s.evidence_quality == pytest.approx(1.0)
    assert s.judge_agreement is None and "single judge" in s.judge_agreement_note
    assert s.ranking_robustness is not None and s.ranking_flips


def test_unverified_gate_visible_and_penalised(main):
    engine, _ = main
    d = engine.store.data
    jb = [j for j in d.judgements.values() if j.option_version_id == "optv_B_v1"][0]
    assert jb.unverified_gates == ["crit_gate_budget"] and jb.penalties == 1.0 and jb.eligible is True
    assert jb.aggregate == pytest.approx(4.6)


def test_withdrawal_and_dissent_survive(main):
    engine, _ = main
    d = engine.store.data
    assert any(v.option_id == "opt_B" and v.status.value == "withdrawn" for v in d.option_versions.values())
    dec = d.decision
    assert dec.material_dissent_ids and any("What you lose" in l for l in (engine.store.run_dir / "report.md").read_text().splitlines())


def test_budget_measured_and_labelled(main):
    engine, _ = main
    b = engine.store.data.decision.budget
    assert b.model_calls_used == 32 and b.model_calls_limit == 60
    assert b.tokens_measured == 0 and b.tokens_estimated > 0
    assert b.cost_status == "unavailable" and b.cost_usd is None


def test_no_agreement_based_stop(main):
    engine, _ = main
    # stopping was decided on stability + absence of blocking objections, never on agreement counts
    stop = [e for e in events(engine) if e["kind"] == "stop_decided"][0]["payload"]
    assert stop["reason"] == "stable" and stop["stable_streak"] == 2 and stop["blocking_challenges"] == []


def test_resolution_rules(main):
    engine, _ = main
    ch = engine.store.data.challenges
    assert ch["chl_b_gate"].status.value == "resolved" and "withdrawn" in ch["chl_b_gate"].resolution_note
    assert ch["chl_c_measure"].status.value == "resolved" and "qualifying evidence" in ch["chl_c_measure"].resolution_note
    assert ch["chl_e_speed"].status.value == "resolved" and "superseded" in ch["chl_e_speed"].resolution_note
    assert ch["chl_shared_capacity"].status.value == "open" and ch["chl_shared_capacity"].verification_attempted


def test_settled_challenges_are_not_reasked_and_do_not_block(main):
    """A conceded (or evidence-less rebutted) challenge records a final position: the owner is not asked
    again and the challenge no longer blocks stability, while it stays open and reported."""
    engine, _ = main
    from llm_council.ontology import Challenge, ChallengeClass, CouldChange, Response, ResponseKind, Role, Severity
    d = engine.store.data
    inc = d.incumbent_version_id
    ch = Challenge(id="chl_test_concede", target_ref=inc, mechanism="test objection that is conceded", severity=Severity.MATERIAL,
                   challenge_class=ChallengeClass.VALUE, could_change=CouldChange.RANKING, round=4,
                   author_participant_id="p_reviewer_1", author_role=Role.REVIEWER)
    engine.store.commit(ch)
    assert engine.challenge_awaits_owner(ch) and ch in engine.blocking_challenges()
    rs = Response(id="rsp_test_concede", challenge_id=ch.id, kind=ResponseKind.CONCEDE, text="conceded", round=4,
                  author_participant_id="p_strategist_staging", author_role=Role.STRATEGIST)
    engine.store.commit(rs)
    assert not engine.challenge_awaits_owner(ch) and ch not in engine.blocking_challenges()
    assert ch.status.value == "open"
    # a revision keeps the owner in the loop
    rs2 = Response(id="rsp_test_revise", challenge_id=ch.id, kind=ResponseKind.REVISE, text="revising", round=4,
                   author_participant_id="p_strategist_staging", author_role=Role.STRATEGIST)
    engine.store.commit(rs2)
    assert engine.challenge_awaits_owner(ch)
