"""Lens catalogue (reasoning methods) and selection.

Each lens is a distinct reasoning method used by a strategist to generate
option versions. Selection depends on stakes, reversibility, domain and
evidence gaps. At least one selected lens must challenge the apparent lean.
The Six Hats bundle is observer-only: hats hold no option and never address
each other; their outputs are collected before review.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ontology import DecisionBrief, Domain, Reversibility, Stakes


@dataclass(frozen=True)
class Lens:
    id: str
    name: str
    method: str
    instruction: str
    tags: frozenset[str] = field(default_factory=frozenset)
    observer_only: bool = False


_SAY_SO = (
    "If this method finds nothing material, say so explicitly instead of inventing content. "
    "Do not defer to the answer the framing seems to expect."
)

LENSES: dict[str, Lens] = {
    "direct": Lens(
        id="direct",
        name="Direct answer and status quo",
        method="baseline",
        instruction=(
            "Produce the round-zero baseline: (1) the status quo option (do nothing / keep the current plan) "
            "and (2) the most direct defensible answer to the decision as a single option. State how each was produced, "
            "which resources were used and which inputs were missing."
        ),
        tags=frozenset({"baseline", "status_quo"}),
    ),
    "first_principles": Lens(
        id="first_principles",
        name="First principles (decomposition)",
        method="decomposition",
        instruction=(
            "Decompose the decision into its load-bearing components and constraints. Separate real constraints from "
            "assumed ones. Rebuild an option from the components that must be true for the objectives to be met. " + _SAY_SO
        ),
        tags=frozenset({"structural"}),
    ),
    "inversion": Lens(
        id="inversion",
        name="Inversion / pre-mortem",
        method="inversion",
        instruction=(
            "Assume the decision has failed badly twelve months from now. Work backwards to the three most likely failure "
            "mechanisms with leading indicators, including for 'do nothing'. Propose the option that removes the dominant "
            "failure mechanism, and name the evidence that would show it is working. " + _SAY_SO
        ),
        tags=frozenset({"failure_first", "challenges_lean"}),
    ),
    "staging": Lens(
        id="staging",
        name="Staged commitment (reversibility)",
        method="dependency_analysis",
        instruction=(
            "Classify the reversibility of each commitment. Design a staged option that buys information cheaply before "
            "the costly or one-way steps, with explicit gates (metric, threshold, date) for scaling up, holding or stopping. "
            "Map the dependencies between stages. " + _SAY_SO
        ),
        tags=frozenset({"staged", "execution"}),
    ),
    "information_option": Lens(
        id="information_option",
        name="Targeted information gathering",
        method="value_of_information",
        instruction=(
            "Identify the single uncertainty whose resolution would most change the choice. Propose a targeted "
            "information-gathering option: what to measure, how, by when, at what cost, and the decision rule that follows. "
            "State what is lost by waiting. " + _SAY_SO
        ),
        tags=frozenset({"information", "challenges_lean"}),
    ),
    "asymmetric_upside": Lens(
        id="asymmetric_upside",
        name="Asymmetric upside",
        method="analogy",
        instruction=(
            "Look for a move with capped downside and uncapped upside, using analogies from other markets or domains tested "
            "for structural fit. Size the opportunity and name the conditions under which it disappears. " + _SAY_SO
        ),
        tags=frozenset({"upside", "analogy"}),
    ),
    "outside_view": Lens(
        id="outside_view",
        name="Outside view (base rates)",
        method="reference_class",
        instruction=(
            "Name the reference class of similar decisions and the base rate of success or typical outcome. Adjust the "
            "most optimistic plan to the base rate and propose the option a disinterested outsider would choose. " + _SAY_SO
        ),
        tags=frozenset({"outside_view", "challenges_lean"}),
    ),
    "execution": Lens(
        id="execution",
        name="Execution reality",
        method="dependency_graph",
        instruction=(
            "Lay out what must happen on the first Monday, who owns each task, and the dependency graph with its critical "
            "path. Propose the option that is executable with the stated resources. If a plan is executable as stated, say so. "
            + _SAY_SO
        ),
        tags=frozenset({"execution"}),
    ),
    "second_order": Lens(
        id="second_order",
        name="Second-order consequences",
        method="consequence_chain",
        instruction=(
            "For the leading course of action ask 'and then what?' at least twice, including how competitors, customers and "
            "internal teams react. Propose the option that remains attractive after the second-order effects. " + _SAY_SO
        ),
        tags=frozenset({"market"}),
    ),
    "expected_value": Lens(
        id="expected_value",
        name="Expected value under scenarios",
        method="quantitative",
        instruction=(
            "Assign explicit probabilities (summing to 1) to the registered scenarios and estimate outcomes per option. "
            "Flag ruinous tails separately from the mean. Propose the option with the best risk-adjusted value and state the "
            "priors used. " + _SAY_SO
        ),
        tags=frozenset({"quantitative"}),
    ),
    "time_horizons": Lens(
        id="time_horizons",
        name="Time horizons (10 minutes / 10 months / 10 years)",
        method="temporal",
        instruction=(
            "Evaluate how the decision looks at three horizons and where they disagree. Propose the option that is defensible "
            "at the horizon the stakeholders actually care about. " + _SAY_SO
        ),
        tags=frozenset({"values"}),
    ),
    "regret": Lens(
        id="regret",
        name="Regret minimisation",
        method="counterfactual",
        instruction=(
            "Compare the regret of acting and failing with the regret of not acting and missing out, weighting inaction regret "
            "honestly. Do not confuse regret minimisation with maximum safety. " + _SAY_SO
        ),
        tags=frozenset({"values", "challenges_lean"}),
    ),
    "tempo": Lens(
        id="tempo",
        name="Tempo (observe-orient-decide-act)",
        method="tempo",
        instruction=(
            "Under time pressure, propose the fastest cheap action that improves orientation, and the explicit re-decision "
            "point. Avoid heavyweight analysis the timeline does not allow. " + _SAY_SO
        ),
        tags=frozenset({"time_pressure"}),
    ),
    "internal_external": Lens(
        id="internal_external",
        name="Internal strengths and weaknesses vs external opportunities and threats",
        method="positioning",
        instruction=(
            "Separate strictly internal strengths and weaknesses from external opportunities and threats, then cross them "
            "(strength x opportunity, weakness x threat). Propose the option that exploits the strongest crossover. " + _SAY_SO
        ),
        tags=frozenset({"positioning"}),
    ),
    "multidisciplinary": Lens(
        id="multidisciplinary",
        name="Multidisciplinary models",
        method="latticework",
        instruction=(
            "Apply at least three disciplinary lenses (for example economics, psychology, operations, statistics). Treat a "
            "conclusion that survives three disciplines as robust. Propose the option they jointly support. " + _SAY_SO
        ),
        tags=frozenset({"novel"}),
    ),
    "widen_reality_test": Lens(
        id="widen_reality_test",
        name="Widen options and reality-test assumptions",
        method="widen_test",
        instruction=(
            "Add at least two options not yet considered, design a disconfirming test for each key assumption, and define "
            "tripwires (metric, threshold, date) that would trigger a reversal. " + _SAY_SO
        ),
        tags=frozenset({"widen", "challenges_lean"}),
    ),
    "balanced_ledger": Lens(
        id="balanced_ledger",
        name="Certainty-tagged ledger",
        method="ledger",
        instruction=(
            "List the pros and cons of each candidate, tagging each item as certain, likely or speculative, and ranking by "
            "magnitude. Do not pad either side for balance. Propose the option whose certain items dominate. " + _SAY_SO
        ),
        tags=frozenset({"low_stakes"}),
    ),
    # Observer-only hats (adapted Six Thinking Hats). They produce claims, evidence
    # requests and challenges about the option set rather than owning options.
    "hat_facts": Lens("hat_facts", "Facts hat (observer)", "facts", "List only facts and data gaps relevant to the option set. No opinions.", frozenset({"hats"}), True),
    "hat_risks": Lens("hat_risks", "Risks hat (observer)", "risks", "List concrete failure mechanisms for each option with severity.", frozenset({"hats"}), True),
    "hat_creative": Lens("hat_creative", "Creative hat (observer)", "creative", "Propose one genuinely new option outside the current set.", frozenset({"hats"}), True),
    "hat_feelings": Lens("hat_feelings", "Feelings hat (observer)", "intuition", "State the stakeholder emotions and intuitions each option triggers, one per option.", frozenset({"hats"}), True),
    "hat_value": Lens("hat_value", "Value hat (observer)", "benefits", "State the strongest realistic benefit of each option with the condition for it to materialise.", frozenset({"hats"}), True),
    "hat_process": Lens("hat_process", "Process hat (observer)", "process", "Say whether the decision has drifted from 'whether' to 'how' and what the next useful check is.", frozenset({"hats"}), True),
}

HATS_BUNDLE = ["hat_facts", "hat_risks", "hat_creative", "hat_feelings", "hat_value", "hat_process"]


def select_lenses(brief: DecisionBrief, *, mode: str, explicit: list[str], min_n: int, max_n: int,
                  include_staged: bool, include_information: bool) -> list[str]:
    """Deterministic lens selection."""
    if mode == "explicit":
        expanded: list[str] = []
        for l in explicit:
            expanded.extend(HATS_BUNDLE if l == "hats" else [l])
        unknown = [l for l in expanded if l not in LENSES]
        if unknown:
            raise ValueError(f"unknown lenses: {unknown}")
        return list(dict.fromkeys(expanded))

    chosen: list[str] = ["first_principles"]
    if brief.stakes in (Stakes.MEDIUM, Stakes.HIGH, Stakes.CRITICAL):
        chosen.append("inversion")
    if include_staged and brief.reversibility in (Reversibility.COSTLY, Reversibility.ONE_WAY):
        chosen.append("staging")
    if include_information and (brief.evidence_gaps or brief.domain in (Domain.COMPLEX, Domain.CHAOTIC)):
        chosen.append("information_option")
    if brief.stakes in (Stakes.HIGH, Stakes.CRITICAL):
        chosen.append("outside_view")
    if brief.domain in (Domain.CLEAR, Domain.COMPLICATED) and brief.stakes != Stakes.LOW:
        chosen.append("expected_value")
    if brief.stakes == Stakes.LOW:
        chosen.append("balanced_ledger")
    chosen.append("asymmetric_upside")
    chosen.append("execution")
    chosen.append("second_order")
    chosen.append("widen_reality_test")

    chosen = list(dict.fromkeys(chosen))
    # Ensure at least one lens challenges the apparent lean.
    if not any("challenges_lean" in LENSES[l].tags for l in chosen[:max_n]):
        chosen.insert(1, "outside_view")
    chosen = chosen[:max_n]
    while len(chosen) < min_n:
        for extra in ("outside_view", "regret", "time_horizons", "internal_external", "multidisciplinary"):
            if extra not in chosen:
                chosen.append(extra)
                break
        else:
            break
    return chosen
