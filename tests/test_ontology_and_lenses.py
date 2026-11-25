from __future__ import annotations

import pytest
from pydantic import ValidationError

from llm_council.lenses import HATS_BUNDLE, LENSES, select_lenses
from llm_council.ontology import (
    Challenge, ChallengeClass, CouldChange, DecisionBrief, Domain, GenerationNote, OptionVersion, Reversibility, Role, RunState,
    Severity, Stakes, StrictModel,
)
from llm_council.prompts import BY_KIND, GUARDRAIL, instructions_for
from llm_council.state import RejectedUpdate, RunData, Store


def brief(**kw) -> DecisionBrief:
    base = dict(id="brief_0001", question_raw="q", decision_statement="decide something concrete", objectives=["o"],
                time_horizon="Q1", stakes=Stakes.HIGH, reversibility=Reversibility.COSTLY, domain=Domain.COMPLICATED,
                author_participant_id="p_framer", author_role=Role.FRAMER)
    base.update(kw)
    return DecisionBrief(**base)


def test_store_rejects_unknown_references_before_mutation(tmp_path):
    store = Store(tmp_path / "r", RunData(run_id="r", question="q"))
    ch = Challenge(id="chl_x", target_ref="optv_missing", mechanism="breaks because", severity=Severity.MATERIAL,
                   challenge_class=ChallengeClass.FACTUAL, could_change=CouldChange.RANKING, round=1,
                   author_participant_id="p_reviewer_1", author_role=Role.REVIEWER)
    with pytest.raises(RejectedUpdate):
        store.commit(ch)
    assert not store.data.challenges and not store.data.relations


def test_store_rejects_unauthorised_role_and_bad_transition(tmp_path):
    store = Store(tmp_path / "r", RunData(run_id="r", question="q"))
    b = brief(author_role=Role.JUDGE, author_participant_id="p_judge_1")
    with pytest.raises(RejectedUpdate, match="may not author"):
        store.commit(b)
    with pytest.raises(RejectedUpdate, match="unauthorised transition"):
        store.set_state(RunState.JUDGING)
    store.set_state(RunState.FRAMING)
    assert store.data.state == RunState.FRAMING


def test_lineage_supersedes_relation_and_duplicate_ids(tmp_path):
    store = Store(tmp_path / "r", RunData(run_id="r", question="q"))
    note = GenerationNote(how="x")
    v1 = OptionVersion(id="optv_1", option_id="opt_1", version=1, title="Option one", summary="summary long enough", round=0,
                       generation_note=note, author_participant_id="p_strategist_direct", author_role=Role.STRATEGIST)
    store.commit(v1)
    v2 = v1.model_copy(update={"id": "optv_2", "version": 2, "parent_version_id": "optv_1", "change_reason": "revised"})
    store.commit(v2)
    assert any(r.kind.value == "supersedes" and r.from_id == "optv_2" and r.to_id == "optv_1" for r in store.data.relations)
    with pytest.raises(RejectedUpdate, match="duplicate id"):
        store.commit(v1)
    bad = v1.model_copy(update={"id": "optv_3", "parent_version_id": "optv_nope"})
    with pytest.raises(RejectedUpdate):
        store.commit(bad)


def test_unknown_fields_rejected_and_protocol_version_checked():
    class X(StrictModel):
        a: int
    with pytest.raises(ValidationError):
        X.model_validate({"a": 1, "b": 2})
    with pytest.raises(ValidationError):
        brief(protocol_version="0.9")


def test_transaction_rollback_restores_state(tmp_path):
    store = Store(tmp_path / "r", RunData(run_id="r", question="q"))
    store.begin()
    note = GenerationNote(how="x")
    store.commit(OptionVersion(id="optv_1", option_id="opt_1", version=1, title="Option one", summary="summary long enough", round=0,
                               generation_note=note, author_participant_id="p_strategist_direct", author_role=Role.STRATEGIST))
    assert "optv_1" in store.data.option_versions
    store.rollback()
    assert "optv_1" not in store.data.option_versions
    assert not (tmp_path / "r" / "events.jsonl").exists()


# ---- lenses -----------------------------------------------------------------


def test_lens_selection_by_stakes_and_reversibility():
    high = select_lenses(brief(), mode="auto", explicit=[], min_n=3, max_n=5, include_staged=True, include_information=True)
    assert "inversion" in high and "staging" in high and len(high) == 5
    assert any("challenges_lean" in LENSES[l].tags for l in high)
    low = select_lenses(brief(stakes=Stakes.LOW, reversibility=Reversibility.REVERSIBLE), mode="auto", explicit=[], min_n=3, max_n=5,
                        include_staged=True, include_information=True)
    assert "inversion" not in low and "staging" not in low and "balanced_ledger" in low
    gaps = select_lenses(brief(evidence_gaps=["x"]), mode="auto", explicit=[], min_n=3, max_n=5, include_staged=True, include_information=True)
    assert "information_option" in gaps


def test_explicit_and_hats_observer_only():
    sel = select_lenses(brief(), mode="explicit", explicit=["hats", "inversion"], min_n=1, max_n=12, include_staged=True, include_information=True)
    assert sel == [*HATS_BUNDLE, "inversion"]
    assert all(LENSES[h].observer_only for h in HATS_BUNDLE)
    with pytest.raises(ValueError):
        select_lenses(brief(), mode="explicit", explicit=["nope"], min_n=1, max_n=5, include_staged=True, include_information=True)


def test_catalogue_covers_reference_methods():
    for lid in ("first_principles", "inversion", "staging", "information_option", "asymmetric_upside", "outside_view", "execution",
                "second_order", "expected_value", "time_horizons", "regret", "tempo", "internal_external", "multidisciplinary",
                "widen_reality_test", "balanced_ledger"):
        assert lid in LENSES and "say so" in LENSES[lid].instruction


def test_guardrail_present_in_every_instruction():
    for kind in BY_KIND:
        text = instructions_for(kind, LENSES["inversion"].instruction if kind == "generate" else None)
        assert GUARDRAIL in text and "Do not defer" in text
