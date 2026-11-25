from __future__ import annotations

import pytest
from pydantic import ValidationError

from llm_council.config import JudgeConfig
from llm_council.judge import Combined, combine, finalize_judgement, is_close, promotion, rank, sensitivity
from llm_council.ontology import (
    ComparisonKey, Confidence, Criterion, CriterionKind, CriterionScore, EvaluationPolicy, GateOutcome, GateResult, Judgement,
    JudgementStatus, PromotionOutcome, Role, Scenario,
)
from llm_council.phases import JudgeResponse

AUTH = {"author_participant_id": "p_judge_1", "author_role": Role.JUDGE}


def policy() -> EvaluationPolicy:
    return EvaluationPolicy(
        id="pol_1", brief_id="brief_1", brief_version=1, rubric_version=1, materiality_threshold=0.5, promotion_margin=0.0,
        unverified_gate_policy="penalty", judge_config_hash="h",
        criteria=[
            Criterion(id="crit_gate", name="gate", kind=CriterionKind.GATE),
            Criterion(id="crit_a", name="a", kind=CriterionKind.SCORE, weight=3),
            Criterion(id="crit_b", name="b", kind=CriterionKind.SCORE, weight=1),
        ],
        scenarios=[Scenario(id="scn_x", name="x")],
        author_participant_id="p_policy_setter", author_role=Role.POLICY_SETTER,
    )


def key(snap="snap-1") -> ComparisonKey:
    return ComparisonKey(brief_version=1, rubric_version=1, evidence_snapshot_id=snap, judge_config_hash="h")


def judgement(vid: str, a: int, b: int, conf=Confidence.MEDIUM, gate=GateOutcome.PASS, snap="snap-1", pid="p_judge_1", scen=None) -> Judgement:
    j = Judgement(id=f"jdg_{vid}_{pid}_{snap}", option_version_id=vid, comparison_key=key(snap), participant_id=pid, round=1,
                  gate_results=[GateResult(criterion_id="crit_gate", outcome=gate, evidence_ids=["ev_1"])],
                  criterion_scores=[CriterionScore(criterion_id="crit_a", score=a, confidence=conf, evidence_ids=["ev_1"]),
                                    CriterionScore(criterion_id="crit_b", score=b, confidence=conf, assumption_ids=["asm_1"])],
                  scenario_scores=scen or {}, **AUTH)
    return finalize_judgement(j, policy(), JudgeConfig())


def comb(*js: Judgement) -> Combined:
    j0 = js[0]
    return combine(list(js), policy(), JudgeConfig(), j0.option_version_id, j0.comparison_key.as_tuple())


def test_aggregate_bounds_and_normalised_weights():
    j = judgement("v1", 8, 4)
    assert j.aggregate == pytest.approx(0.75 * 8 + 0.25 * 4)
    assert j.lower_bound == pytest.approx(0.75 * 7 + 0.25 * 3) and j.upper_bound == pytest.approx(0.75 * 9 + 0.25 * 5)
    assert j.eligible is True and j.penalties == 0


def test_failed_gate_disqualifies_and_unverified_penalises():
    f = judgement("v1", 8, 8, gate=GateOutcome.FAIL)
    assert f.eligible is False and f.failed_gates == ["crit_gate"]
    u = judgement("v1", 8, 8, gate=GateOutcome.UNVERIFIED)
    assert u.eligible is True and u.unverified_gates == ["crit_gate"] and u.penalties == 1.0 and u.aggregate == pytest.approx(7.0)
    strict = finalize_judgement(Judgement.model_validate(u.model_dump() | {"aggregate": None}), policy(), JudgeConfig(unverified_gate_policy="fail"))
    assert strict.eligible is False


def test_judgement_must_cover_policy_and_cite():
    with pytest.raises(ValidationError):
        CriterionScore(criterion_id="crit_a", score=5)  # no evidence, no assumption
    j = Judgement(id="jdg_x", option_version_id="v1", comparison_key=key(), participant_id="p_judge_1", round=1,
                  criterion_scores=[CriterionScore(criterion_id="crit_a", score=5, evidence_ids=["ev_1"])], **AUTH)
    with pytest.raises(ValueError):
        finalize_judgement(j, policy(), JudgeConfig())


def test_model_cannot_supply_aggregate():
    with pytest.raises(ValidationError):
        JudgeResponse.model_validate({"gate_results": [], "criterion_scores": [{"criterion_id": "crit_a", "score": 5, "evidence_ids": ["e"]}], "aggregate": 9.9})


def test_promotion_rule_outcomes():
    cfg = JudgeConfig()
    inc = comb(judgement("inc", 6, 6, Confidence.HIGH))          # 6.0 [5.5, 6.5]
    assert promotion(inc, comb(judgement("c1", 8, 8, Confidence.HIGH)), cfg)[0] == PromotionOutcome.PROMOTED       # 8 [7.5, 8.5]
    assert promotion(inc, comb(judgement("c2", 6, 7, Confidence.HIGH)), cfg)[0] == PromotionOutcome.RETAINED_TIE   # 6.25
    assert promotion(inc, comb(judgement("c3", 5, 5, Confidence.HIGH)), cfg)[0] == PromotionOutcome.RETAINED_LOSS  # 5.0
    out, note = promotion(inc, comb(judgement("c4", 7, 6, Confidence.LOW)), cfg)                                   # 6.75 [5.25, 8.25]
    assert out == PromotionOutcome.INCONCLUSIVE and "bounds overlap" in note
    assert promotion(inc, None, cfg)[0] == PromotionOutcome.NO_CHALLENGER
    assert promotion(comb(judgement("inc2", 6, 6, gate=GateOutcome.FAIL)), comb(judgement("c5", 5, 5)), cfg)[0] == PromotionOutcome.INCUMBENT_INELIGIBLE
    assert promotion(inc, comb(judgement("c6", 9, 9, gate=GateOutcome.FAIL)), cfg)[0] == PromotionOutcome.RETAINED_LOSS


def test_mixed_keys_are_non_comparable_and_missing_is_explicit():
    cfg = JudgeConfig()
    inc = comb(judgement("inc", 6, 6, snap="snap-1"))
    chal = comb(judgement("c", 9, 9, snap="snap-2"))
    out, note = promotion(inc, chal, cfg)
    assert out == PromotionOutcome.NON_COMPARABLE and "keys differ" in note
    missing = combine([], policy(), cfg, "c", key("snap-2").as_tuple())
    assert missing.status == "missing" and missing.aggregate is None
    assert promotion(inc, missing, cfg)[0] == PromotionOutcome.NON_COMPARABLE
    assert rank([inc, missing]) == [("inc", 6.0)]


def test_swapped_order_disagreement_is_inconclusive_and_agreement_breaks_tie():
    cfg = JudgeConfig()
    inc = comb(judgement("inc", 6, 6, Confidence.HIGH))
    chal = comb(judgement("c", 7, 6, Confidence.LOW))
    assert is_close(inc, chal, cfg)
    assert promotion(inc, chal, cfg, pairwise="disagree")[0] == PromotionOutcome.INCONCLUSIVE
    assert promotion(inc, chal, cfg, pairwise="challenger")[0] == PromotionOutcome.PROMOTED
    assert promotion(inc, chal, cfg, pairwise="incumbent")[0] == PromotionOutcome.RETAINED_TIE


def test_jury_disagreement_widens_bounds_and_is_measured():
    j1 = judgement("v", 8, 8, Confidence.HIGH, pid="p_judge_1")
    j2 = judgement("v", 4, 8, Confidence.HIGH, pid="p_judge_2")
    c = comb(j1, j2)
    assert c.n_judges == 2 and c.aggregate == pytest.approx(0.75 * 6 + 0.25 * 8)
    assert c.lower == pytest.approx(0.75 * 4 + 0.25 * 7.5)   # half-width max(0.5, spread/2 = 2)
    assert c.spread == pytest.approx((0.4 + 0.0) / 2)
    single = comb(j1)
    assert single.lower > c.lower and single.spread == 0.0


def test_sensitivity_reports_flips_and_robustness():
    cfg = JudgeConfig(weight_perturbation=0.5)
    a = comb(judgement("a", 9, 2, Confidence.HIGH, scen={"scn_x": 3}))   # 7.25
    b = comb(judgement("b", 6, 9, Confidence.HIGH, scen={"scn_x": 8}))   # 6.75
    flips, robustness = sensitivity(policy(), [a, b], cfg)
    assert any("scenario scn_x" in f for f in flips)
    assert robustness is not None and 0 <= robustness < 1
    assert sensitivity(policy(), [a], cfg) == ([], None)


def test_sensitivity_ties_are_not_flips():
    cfg = JudgeConfig(weight_perturbation=0.5)
    a = comb(judgement("a", 8, 8, Confidence.HIGH, scen={"scn_x": 8}))
    b = comb(judgement("b", 6, 6, Confidence.HIGH, scen={"scn_x": 8}))   # ties with a on the scenario
    flips, robustness = sensitivity(policy(), [a, b], cfg)
    assert flips == [] and robustness == 1.0


def test_method_recorded():
    j = judgement("v", 5, 5)
    assert j.method.value == "structured_scores"


def test_engine_normalises_claim_citations(tmp_path):
    """A judge citing a claim id where evidence is expected gets the claim's evidence (or the option's assumptions)."""
    from conftest import make_root, run_fixture
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, "main_run.json", run_id="cit")
    d = engine.store.data
    # clm_c1 cites ev_u1; clm_c2 has no evidence but its option carries asm_c1
    assert engine._normalise_citations(["clm_c1"], [], "optv_C_v1") == {"evidence_ids": ["ev_u1"], "assumption_ids": []}
    assert engine._normalise_citations(["clm_c2"], [], "optv_C_v1") == {"evidence_ids": [], "assumption_ids": ["asm_c1"]}
    assert engine._normalise_citations(["asm_c1", "ev_u2"], [], "optv_C_v1") == {"evidence_ids": ["ev_u2"], "assumption_ids": ["asm_c1"]}


def test_judge_may_state_assumptions_inline_or_by_name(tmp_path):
    """Spec: each judgement cites evidence or states its assumptions. A judge may declare assumptions in the
    response, or merely name one; both are recorded as judge-stated assumptions instead of being rejected."""
    from conftest import FIXTURES, LENSES, QUESTION, make_root
    from llm_council.config import load_effective_config
    from llm_council.engine import Engine, ReplyMeta
    from llm_council.providers.base import parse_reply_json
    from llm_council.providers.fixture import FixtureProvider
    from llm_council.state import Store
    import json
    root = make_root(tmp_path)
    eff = load_effective_config(root, overrides={"lenses": {"selection": "explicit", "explicit": LENSES.split(",")}})
    store = Store.create(root / ".council" / "runs", "jsa", QUESTION)
    store.data.effective_config = eff.config.model_dump(mode="json")
    engine = Engine(store, eff.config)
    fx = FixtureProvider(FIXTURES / "main_run.json", strict_consumption=False)
    result = engine.result()
    while result.request.kind != "judge":
        result = engine.step(parse_reply_json(fx.answer(result.request).text), ReplyMeta(provider="chat"))
    j = json.loads(fx.answer(result.request).text)
    j["assumptions"] = [{"id": "asm_judge_declared", "text": "the judge assumes flat CPMs"}]
    j["criterion_scores"][0]["assumption_ids"] = ["asm_judge_declared", "asm_named_only"]
    j["gate_results"][0]["assumption_ids"] = ["asm_named_only"]
    result = engine.step(j, ReplyMeta(provider="chat"))
    d = store.data
    assert "asm_judge_declared" in d.assumptions and d.assumptions["asm_judge_declared"].author_role.value == "judge"
    assert "asm_named_only" in d.assumptions and "Judge-stated" in d.assumptions["asm_named_only"].text
    jd = [x for x in d.judgements.values() if x.status.value == "complete"][-1]
    assert "asm_named_only" in jd.criterion_scores[0].assumption_ids
    assert not any(e["kind"] == "response_rejected" for e in [json.loads(l) for l in (store.run_dir / "events.jsonl").read_text().splitlines()])
