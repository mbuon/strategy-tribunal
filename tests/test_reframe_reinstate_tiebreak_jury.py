"""Run 2 acceptance criterion 6: reframe, reinstate, engine-level pairwise tiebreak and jury > 1 are exercised
by deterministic fixtures. As everywhere else, the fixtures supply only role outputs; every assertion is about
what the controller computed (brief versions, comparison keys, rescoring, lineage, compare requests, combined
bounds and signals)."""

from __future__ import annotations

import json

import pytest

from build_fixtures import A_REINSTATED_ID, A_WITHDRAWN_ID
from conftest import events, make_root, run_fixture
from llm_council.judge import combine
from llm_council.ontology import OptionStatus, PromotionOutcome, ResponseKind, RunState, StopReason

RR_OVERRIDES = {"limits": {"min_rounds": 2, "max_rounds": 2, "max_leader_challenges": 0, "max_verification_calls": 0},
                "review": {"panel_size": 1}}


@pytest.fixture(scope="module")
def rr(tmp_path_factory):
    root = make_root(tmp_path_factory.mktemp("rr"))
    engine, result = run_fixture(root, "reframe_reinstate.json", run_id="rr", lenses="staging", overrides=RR_OVERRIDES)
    return engine, result


@pytest.fixture(scope="module")
def tj(tmp_path_factory):
    root = make_root(tmp_path_factory.mktemp("tj"))
    engine, result = run_fixture(root, "tiebreak_jury.json", run_id="tj", lenses="staging", preset="first_pass",
                                 overrides={"judge": {"jury_size": 2}})
    return engine, result


def summaries(engine):
    return {s.round: s for s in engine.store.data.round_summaries.values()}


def issued(engine, kind):
    return [e["payload"] for e in events(engine) if e["kind"] == "request_issued" and e["payload"]["kind"] == kind]


# --------------------------------------------------------------------------- reframe


def test_reframe_creates_brief_v2_with_lineage_and_copies_the_policy(rr):
    engine, result = rr
    d = engine.store.data
    assert result.status == "terminal" and d.state == RunState.COMPLETE
    briefs = sorted(d.briefs.values(), key=lambda b: b.version)
    assert [b.version for b in briefs] == [1, 2]
    v1, v2 = briefs
    assert v2.supersedes_id == v1.id and v1.supersedes_id is None
    assert v2.decision_statement.startswith("Decide how to stage a move")
    assert v2.author_role.value == "controller"
    assert any(a.startswith("reframe: ") for a in v2.inferred_assumptions)
    assert any(r.kind.value == "supersedes" and r.from_id == v2.id and r.to_id == v1.id for r in d.relations)
    # the policy is carried over under the new brief version with its rubric reset to 1
    pol = engine.store.current_policy()
    assert pol.brief_id == v2.id and pol.brief_version == 2 and pol.rubric_version == 1
    assert len(d.policies) == 2
    assert d.budget.reframes_used == 1


def test_reframe_changes_the_comparison_key_and_reruns_every_candidate_judgement(rr):
    engine, _ = rr
    d = engine.store.data
    assert any(e["kind"] == "rescore_required" and e["payload"] == {"reason": "reframe", "brief_version": 2} for e in events(engine))
    by_version = {}
    for j in d.judgements.values():
        by_version.setdefault(j.option_version_id, set()).add((j.round, j.comparison_key.brief_version))
    # the incumbent and B were judged under brief v1 in round 0 and again under brief v2 in round 1; C only under v2
    assert by_version["optv_A_v1"] == {(0, 1), (1, 2)}
    assert by_version["optv_B_v1"] == {(0, 1), (1, 2)}
    assert by_version["optv_C_v1"] == {(1, 2)}
    s = summaries(engine)
    assert s[0].comparison_key.brief_version == 1 and s[1].comparison_key.brief_version == 2
    assert s[1].comparable and s[1].promotion_outcome == PromotionOutcome.RETAINED_LOSS
    # a brief-v1 judgement is never combined with a brief-v2 one
    old_key = s[1].comparison_key.model_copy(update={"brief_version": 1})
    assert engine.combined("optv_A_v1", old_key).status == "complete"
    assert engine.combined("optv_C_v1", old_key).status == "missing"
    judges_round1 = [p for p in issued(engine, "judge")]
    assert len(judges_round1) == 6  # 2 (round 0) + 3 (rescore after reframe) + 1 (reinstated version)


def test_second_reframe_is_capped_by_max_reframes(rr):
    engine, _ = rr
    d = engine.store.data
    assert engine.cfg.limits.max_reframes == 1
    assert len(d.briefs) == 2 and d.budget.reframes_used == 1
    assert "reframe proposed but max_reframes reached" in d.unfinished_checks
    assert d.decision is not None and "reframe proposed but max_reframes reached" in d.decision.unfinished_checks


# --------------------------------------------------------------------------- reinstate


def test_withdrawn_incumbent_is_reinstated_with_reason_and_lineage(rr):
    engine, _ = rr
    d = engine.store.data
    v1, v2, v3 = d.option_versions["optv_A_v1"], d.option_versions[A_WITHDRAWN_ID], d.option_versions[A_REINSTATED_ID]
    assert (v1.version, v2.version, v3.version) == (1, 2, 3)
    assert v2.status == OptionStatus.WITHDRAWN and v2.parent_version_id == v1.id and v2.round == 1
    assert v3.status == OptionStatus.REINSTATED and v3.parent_version_id == v2.id and v3.round == 2
    assert v3.change_reason.startswith("reinstated: Reinstating the status quo")
    assert v3.option_id == v1.option_id == "opt_A"
    # the reinstated version restores the withdrawn content (claims and assumptions) from the pre-withdrawal version
    assert v2.claim_ids == [] and v3.claim_ids == v1.claim_ids and v3.assumption_ids == v1.assumption_ids
    assert v3.title == v1.title and v3.author_participant_id == "p_strategist_direct"
    chain = [(r.from_id, r.to_id) for r in d.relations if r.kind.value == "supersedes"]
    assert (v2.id, v1.id) in chain and (v3.id, v2.id) in chain
    # the response that did it is recorded against the challenge, with the explicit reason
    rs = [r for r in d.responses.values() if r.kind == ResponseKind.REINSTATE]
    assert len(rs) == 1 and rs[0].challenge_id == "chl_a_withdrawn" and rs[0].round == 2
    assert "never evidenced" in rs[0].text
    assert any(r.kind.value == "addresses" and r.from_id == rs[0].id and r.to_id == "chl_a_withdrawn" for r in d.relations)


def test_reinstated_version_is_a_candidate_and_is_judged_under_the_current_key(rr):
    engine, _ = rr
    d = engine.store.data
    active_ids = {v.id for v in engine.store.active_versions()}
    assert A_REINSTATED_ID in active_ids and A_WITHDRAWN_ID not in active_ids and "optv_A_v1" not in active_ids
    assert {v.id for v in engine.candidates()} == {A_REINSTATED_ID, "optv_B_v1", "optv_C_v1", "optv_A_v1"}  # + incumbent
    js = [j for j in d.judgements.values() if j.option_version_id == A_REINSTATED_ID]
    assert len(js) == 1 and js[0].round == 2 and js[0].comparison_key.as_tuple() == engine.key().as_tuple()
    assert [p["kind"] for p in issued(engine, "respond")] == ["respond", "respond"]
    r2 = summaries(engine)[2]
    assert r2.challenger_version_id == A_REINSTATED_ID and r2.promotion_outcome == PromotionOutcome.RETAINED_TIE
    assert r2.delta_vs_prior_incumbent.comparable and r2.delta_vs_prior_incumbent.value == pytest.approx(0.0)
    assert A_REINSTATED_ID in r2.new_version_ids
    assert d.stop_reason == StopReason.MAX_ROUNDS and d.budget.model_calls_used == 14
    # the withdrawal challenge is settled by the owner's answer: the owner is not asked again
    ch = d.challenges["chl_a_withdrawn"]
    assert not engine.challenge_awaits_owner(ch)
    assert d.challenges["chl_a_stale"].status.value == "resolved" and "withdrawn" in d.challenges["chl_a_stale"].resolution_note


# --------------------------------------------------------------------------- pairwise tiebreak


def test_close_call_issues_two_compare_requests_with_swapped_order(tj):
    engine, result = tj
    d = engine.store.data
    assert result.status == "terminal" and d.state == RunState.COMPLETE
    cmp_issued = issued(engine, "compare")
    assert len(cmp_issued) == 2 and all(p["participant"] == "p_judge_1" and p["role"] == "judge" for p in cmp_issued)
    reqs = [json.loads((engine.store.run_dir / "requests" / f"{p['request_id']}.json").read_text()) for p in cmp_issued]
    hints = [(r["match_hints"]["slot"], r["match_hints"]["first"], r["match_hints"]["second"]) for r in reqs]
    assert hints == [("a", "optv_A_v1", "optv_C_v1"), ("b", "optv_C_v1", "optv_A_v1")]
    # the payload labels the candidates only as first/second; the content is swapped between the two passes
    for r in reqs:
        assert r["payload"]["first"]["id"] == "first" and r["payload"]["second"]["id"] == "second"
    assert reqs[0]["payload"]["first"]["title"] == reqs[1]["payload"]["second"]["title"] == d.option_versions["optv_A_v1"].title
    assert reqs[0]["payload"]["second"]["title"] == reqs[1]["payload"]["first"]["title"] == d.option_versions["optv_C_v1"].title
    # both compare requests were issued after every judgement of the round
    kinds = [e["payload"]["kind"] for e in events(engine) if e["kind"] == "request_issued"]
    assert kinds[-2:] == ["compare", "compare"] and kinds.count("judge") == 6
    # committed comparison records keep the order and the verdict
    cmps = list(d.comparisons.values())
    assert [(c.first_version_id, c.second_version_id, c.preferred) for c in cmps] == \
        [("optv_A_v1", "optv_C_v1", "second"), ("optv_C_v1", "optv_A_v1", "first")]
    assert all(c.comparison_key.as_tuple() == engine.key().as_tuple() and c.round == 1 for c in cmps)


def test_tiebreak_is_triggered_only_by_a_close_call_and_both_passes_decide_promotion(tj):
    engine, _ = tj
    d = engine.store.data
    s = summaries(engine)
    key = s[1].comparison_key
    inc, chal = engine.combined("optv_A_v1", key), engine.combined("optv_C_v1", key)
    # material delta with overlapping bounds: inconclusive by scores alone
    assert chal.aggregate - inc.aggregate == pytest.approx(0.9)
    assert chal.aggregate - inc.aggregate >= engine.cfg.judge.materiality_threshold
    assert chal.lower <= inc.upper + engine.cfg.judge.promotion_margin
    assert inc.lower <= chal.upper
    assert s[1].promotion_outcome == PromotionOutcome.PROMOTED and s[1].incumbent_version_id == "optv_C_v1"
    assert "preferred the challenger twice" in s[1].note
    assert [h["version_id"] for h in d.incumbent_history] == ["optv_A_v1", "optv_C_v1"]
    assert d.cursor.get("compare") is None and d.cursor.get("compare_done_round") == 1
    assert d.decision.recommended_version_id == "optv_C_v1" and d.decision.kind.value == "firm"
    assert d.budget.model_calls_used == 12  # 3 + 4 + 1 + 2 judgements + 2 compares


# --------------------------------------------------------------------------- jury > 1


def test_jury_of_two_scores_every_version_and_disagreement_widens_bounds(tj):
    engine, _ = tj
    d = engine.store.data
    assert engine.cfg.judge.jury_size == 2
    by_version = {}
    for j in d.judgements.values():
        by_version.setdefault(j.option_version_id, set()).add(j.participant_id)
    assert by_version == {v: {"p_judge_1", "p_judge_2"} for v in ("optv_A_v1", "optv_B_v1", "optv_C_v1")}
    assert {p["participant"] for p in issued(engine, "judge")} == {"p_judge_1", "p_judge_2"}
    assert {"p_judge_1", "p_judge_2"} <= set(d.participants) and all(d.participants[p].role.value == "judge" for p in ("p_judge_1", "p_judge_2"))
    key = engine.key()
    c = engine.combined("optv_C_v1", key)
    assert c.n_judges == 2 and c.aggregate == pytest.approx(6.9)
    assert c.criterion_means["crit_reach"] == pytest.approx(7.0) and c.spread == pytest.approx(0.05)
    assert (c.lower, c.upper) == (pytest.approx(6.0), pytest.approx(7.8))
    # the same two judgements taken singly give narrower bounds (width 1.4 vs 1.8): the spread/2 of 1.0 on reach
    # replaces the high-confidence half-width of 0.5, so disagreement widened them
    policy = engine.store.current_policy()
    js = engine.store.judgements_for("optv_C_v1", key.as_tuple())
    assert len(js) == 2
    for j in js:
        single = combine([j], policy, engine.cfg.judge, "optv_C_v1", key.as_tuple())
        assert single.n_judges == 1 and single.spread == 0.0
        assert single.upper - single.lower == pytest.approx(1.4)
    assert c.upper - c.lower == pytest.approx(1.8)
    # judges who agree exactly produce no spread
    a = engine.combined("optv_A_v1", key)
    assert a.n_judges == 2 and a.spread == 0.0 and (a.lower, a.upper) == (pytest.approx(5.25), pytest.approx(6.75))


def test_judge_agreement_is_measured_and_reported_for_a_jury(tj):
    engine, _ = tj
    sig = engine.store.data.decision.signals
    assert sig.judge_agreement == pytest.approx(0.95)
    assert sig.judge_agreement_note == "mean normalised score spread across 2 judges"
    report = (engine.store.run_dir / "report.md").read_text()
    assert "- Judge agreement: 0.95 (mean normalised score spread across 2 judges)" in report
