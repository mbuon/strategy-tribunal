"""The report orders open objections by relevance to the recommendation before choosing the next action."""
from __future__ import annotations

from types import SimpleNamespace

from llm_council.ontology import CouldChange, Severity
from llm_council.report import challenge_priority


def _c(target: str, could: CouldChange, sev: Severity) -> SimpleNamespace:
    return SimpleNamespace(target_ref=target, could_change=could, severity=sev)


def test_recommended_option_first_then_shared_then_others():
    inc, claims = "optv_rec", {"clm_rec_1"}
    minor_dup_on_other = _c("optv_other", CouldChange.RANKING, Severity.MINOR)
    material_on_rec = _c("optv_rec", CouldChange.RANKING, Severity.MATERIAL)
    action_on_rec_claim = _c("clm_rec_1", CouldChange.ACTION, Severity.MATERIAL)
    shared_action = _c("__all__", CouldChange.ACTION, Severity.MATERIAL)
    critical_on_other = _c("optv_other", CouldChange.ACTION, Severity.CRITICAL)
    ordered = sorted([minor_dup_on_other, material_on_rec, action_on_rec_claim, shared_action, critical_on_other],
                     key=lambda c: challenge_priority(c, inc, claims))
    assert ordered == [action_on_rec_claim, material_on_rec, shared_action, critical_on_other, minor_dup_on_other]


def test_without_a_recommendation_shared_objections_lead_and_severity_breaks_ties():
    a = _c("optv_x", CouldChange.ACTION, Severity.MINOR)
    b = _c("optv_x", CouldChange.ACTION, Severity.CRITICAL)
    s = _c("__all__", CouldChange.RANKING, Severity.MINOR)
    assert sorted([a, b, s], key=lambda c: challenge_priority(c, None, set())) == [s, b, a]
