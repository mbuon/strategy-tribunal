"""Global judge arithmetic: scoring contract, bounds, eligibility, combination
across a jury, promotion rule, ranking and sensitivity. Pure functions; the
controller calls them. Models never write aggregates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .config import JudgeConfig
from .ontology import (
    Confidence,
    CriterionKind,
    EvaluationPolicy,
    GateOutcome,
    Judgement,
    JudgementStatus,
    PromotionOutcome,
)


@dataclass
class Combined:
    version_id: str
    key: tuple
    status: str  # complete | missing
    aggregate: Optional[float] = None
    lower: Optional[float] = None
    upper: Optional[float] = None
    eligible: Optional[bool] = None
    spread: float = 0.0  # mean normalised disagreement across judges (0..1)
    n_judges: int = 0
    failed_gates: list[str] = field(default_factory=list)
    unverified_gates: list[str] = field(default_factory=list)
    criterion_means: dict[str, float] = field(default_factory=dict)
    scenario_means: dict[str, float] = field(default_factory=dict)


def _hw(conf: Confidence, cfg: JudgeConfig) -> float:
    return {Confidence.HIGH: cfg.half_widths.high, Confidence.MEDIUM: cfg.half_widths.medium,
            Confidence.LOW: cfg.half_widths.low}[conf]


def validate_judgement_against_policy(j: Judgement, policy: EvaluationPolicy) -> None:
    """Every gate and every score criterion must be present exactly once."""
    gate_ids = {c.id for c in policy.gate_criteria}
    score_ids = {c.id for c in policy.score_criteria}
    got_gates = [g.criterion_id for g in j.gate_results]
    got_scores = [s.criterion_id for s in j.criterion_scores]
    if set(got_gates) != gate_ids or len(got_gates) != len(gate_ids):
        raise ValueError(f"gate_results must cover exactly {sorted(gate_ids)}, got {got_gates}")
    if set(got_scores) != score_ids or len(got_scores) != len(score_ids):
        raise ValueError(f"criterion_scores must cover exactly {sorted(score_ids)}, got {got_scores}")


def finalize_judgement(j: Judgement, policy: EvaluationPolicy, cfg: JudgeConfig) -> Judgement:
    """Fill controller-computed fields (aggregate, bounds, eligibility, penalties)."""
    if j.status == JudgementStatus.MISSING:
        return j
    validate_judgement_against_policy(j, policy)
    weights = policy.normalised_weights()
    failed = [g.criterion_id for g in j.gate_results if g.outcome == GateOutcome.FAIL]
    unverified = [g.criterion_id for g in j.gate_results if g.outcome == GateOutcome.UNVERIFIED]
    eligible = not failed
    penalties = 0.0
    if unverified:
        if cfg.unverified_gate_policy == "fail":
            eligible = False
        elif cfg.unverified_gate_policy == "penalty":
            penalties = cfg.unverified_gate_penalty * len(unverified)
    agg = 0.0
    low = 0.0
    high = 0.0
    for s in j.criterion_scores:
        w = weights[s.criterion_id]
        h = _hw(s.confidence, cfg)
        agg += w * s.score
        low += w * max(0.0, s.score - h)
        high += w * min(10.0, s.score + h)
    agg = max(0.0, agg - penalties)
    low = max(0.0, low - 2 * penalties)
    high = max(0.0, min(10.0, high - penalties))
    return j.model_copy(update={
        "aggregate": round(agg, 4), "lower_bound": round(low, 4), "upper_bound": round(high, 4),
        "eligible": eligible, "penalties": penalties, "unverified_gates": unverified, "failed_gates": failed,
    })


def combine(judgements: list[Judgement], policy: EvaluationPolicy, cfg: JudgeConfig, version_id: str,
            key: tuple) -> Combined:
    complete = [j for j in judgements if j.status == JudgementStatus.COMPLETE and j.comparison_key.as_tuple() == key
                and j.option_version_id == version_id]
    if not complete:
        return Combined(version_id=version_id, key=key, status="missing")
    weights = policy.normalised_weights()
    crit_ids = list(weights)
    means: dict[str, float] = {}
    hws: dict[str, float] = {}
    spreads: list[float] = []
    for cid in crit_ids:
        scores = []
        confs = []
        for j in complete:
            for s in j.criterion_scores:
                if s.criterion_id == cid:
                    scores.append(s.score)
                    confs.append(s.confidence)
        mean = sum(scores) / len(scores)
        spread = (max(scores) - min(scores)) if len(scores) > 1 else 0.0
        spreads.append(spread / 10.0)
        means[cid] = mean
        hws[cid] = max(max(_hw(c, cfg) for c in confs), spread / 2.0)
    failed = sorted({g for j in complete for g in j.failed_gates})
    unverified = sorted({g for j in complete for g in j.unverified_gates})
    eligible = all(bool(j.eligible) for j in complete)
    penalties = max(j.penalties for j in complete)
    agg = sum(weights[c] * means[c] for c in crit_ids) - penalties
    low = sum(weights[c] * max(0.0, means[c] - hws[c]) for c in crit_ids) - 2 * penalties
    high = sum(weights[c] * min(10.0, means[c] + hws[c]) for c in crit_ids) - penalties
    scen: dict[str, float] = {}
    for sid in {s for j in complete for s in j.scenario_scores}:
        vals = [j.scenario_scores[sid] for j in complete if sid in j.scenario_scores]
        scen[sid] = sum(vals) / len(vals)
    return Combined(
        version_id=version_id, key=key, status="complete",
        aggregate=round(max(0.0, agg), 4), lower=round(max(0.0, low), 4), upper=round(max(0.0, min(10.0, high)), 4),
        eligible=eligible, spread=round(sum(spreads) / len(spreads), 4) if spreads else 0.0,
        n_judges=len(complete), failed_gates=failed, unverified_gates=unverified,
        criterion_means=means, scenario_means=scen,
    )


def is_close(a: Combined, b: Combined, cfg: JudgeConfig) -> bool:
    """Bounds overlap and the mean difference is at least material."""
    if a.status != "complete" or b.status != "complete":
        return False
    overlap = not (a.lower > b.upper or b.lower > a.upper)
    return overlap and abs(a.aggregate - b.aggregate) >= cfg.materiality_threshold


def promotion(incumbent: Optional[Combined], challenger: Optional[Combined], cfg: JudgeConfig,
              pairwise: Optional[str] = None) -> tuple[PromotionOutcome, str]:
    """Apply the promotion rule on matched inputs.

    ``pairwise`` is the outcome of a counterbalanced pairwise tiebreak when one
    was run: "challenger", "incumbent", "tie" or "disagree".
    """
    if challenger is None:
        return PromotionOutcome.NO_CHALLENGER, "no eligible challenger under the current comparison key"
    if incumbent is None or incumbent.status != "complete":
        return PromotionOutcome.NON_COMPARABLE, "incumbent has no judgement under the current comparison key"
    if challenger.status != "complete":
        return PromotionOutcome.NON_COMPARABLE, "challenger has no complete judgement under the current comparison key"
    if incumbent.key != challenger.key:
        return PromotionOutcome.NON_COMPARABLE, "comparison keys differ (mixed brief/rubric/evidence/judge configuration)"
    if not incumbent.eligible:
        return PromotionOutcome.INCUMBENT_INELIGIBLE, f"incumbent failed gates {incumbent.failed_gates}"
    if not challenger.eligible:
        return PromotionOutcome.RETAINED_LOSS, f"challenger ineligible (failed gates {challenger.failed_gates})"
    delta = challenger.aggregate - incumbent.aggregate
    if challenger.lower > incumbent.upper + cfg.promotion_margin:
        return PromotionOutcome.PROMOTED, f"challenger lower bound {challenger.lower} > incumbent upper bound {incumbent.upper} + margin {cfg.promotion_margin}"
    if abs(delta) < cfg.materiality_threshold:
        return PromotionOutcome.RETAINED_TIE, f"|delta| {abs(delta):.3f} < materiality {cfg.materiality_threshold}"
    if delta <= -cfg.materiality_threshold:
        return PromotionOutcome.RETAINED_LOSS, f"challenger lower by {abs(delta):.3f} (>= materiality)"
    # delta >= materiality but bounds overlap
    if pairwise == "challenger":
        return PromotionOutcome.PROMOTED, "bounds overlap; counterbalanced pairwise comparison preferred the challenger twice"
    if pairwise == "incumbent":
        return PromotionOutcome.RETAINED_TIE, "bounds overlap; counterbalanced pairwise comparison preferred the incumbent twice"
    if pairwise == "disagree":
        return PromotionOutcome.INCONCLUSIVE, "bounds overlap and the swapped-order pairwise verdicts disagree"
    return PromotionOutcome.INCONCLUSIVE, f"delta +{delta:.3f} is material but bounds overlap ([{challenger.lower}, {challenger.upper}] vs [{incumbent.lower}, {incumbent.upper}])"


def rank(combineds: list[Combined]) -> list[tuple[str, float]]:
    ok = [c for c in combineds if c.status == "complete" and c.eligible]
    return [(c.version_id, c.aggregate) for c in sorted(ok, key=lambda c: (-c.aggregate, c.version_id))]


def sensitivity(policy: EvaluationPolicy, combineds: list[Combined], cfg: JudgeConfig) -> tuple[list[str], Optional[float]]:
    """Perturb weights and rank per scenario; return flips and robustness (1 - flips/perturbations)."""
    ok = [c for c in combineds if c.status == "complete" and c.eligible]
    if len(ok) < 2:
        return [], None
    weights = policy.normalised_weights()
    base_top = rank(ok)[0][0]
    flips: list[str] = []
    perturbations = 0
    for cid in weights:
        for sign in (+1, -1):
            perturbations += 1
            w = dict(weights)
            w[cid] = w[cid] * (1 + sign * cfg.weight_perturbation)
            tot = sum(w.values())
            w = {k: v / tot for k, v in w.items()}
            scores = {comb.version_id: sum(w[c] * comb.criterion_means[c] for c in w) for comb in ok}
            winner = _strict_winner(scores, base_top)
            if winner is not None:
                flips.append(f"weight {cid} {'+' if sign > 0 else '-'}{int(cfg.weight_perturbation * 100)}% -> top becomes {winner}")
    for scn in policy.scenarios:
        if all(scn.id in c.scenario_means for c in ok):
            perturbations += 1
            scores = {c.version_id: c.scenario_means[scn.id] for c in ok}
            winner = _strict_winner(scores, base_top)
            if winner is not None:
                flips.append(f"scenario {scn.id} ({scn.name}) -> top becomes {winner}")
    robustness = round(1.0 - len(flips) / perturbations, 4) if perturbations else None
    return flips, robustness


def _strict_winner(scores: dict[str, float], base_top: str) -> Optional[str]:
    """Return the version that strictly beats the base top under the perturbation, else None.
    Ties never count as flips."""
    best = max(scores.values())
    if best <= scores[base_top] + 1e-9:
        return None
    return sorted(v for v, s in scores.items() if abs(s - best) < 1e-9)[0]


def gate_ids(policy: EvaluationPolicy) -> list[str]:
    return [c.id for c in policy.criteria if c.kind == CriterionKind.GATE]
