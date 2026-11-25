"""Round summaries, the machine-readable Decision and the markdown report.

Everything here is computed by the controller from committed records. No model
call is involved, so the same state always yields the same report.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .judge import Combined, rank, sensitivity
from .ontology import (
    ComparisonKey,
    Confidence,
    ConfidenceReport,
    CouldChange,
    Decision,
    DecisionOutcomeKind,
    Delta,
    PromotionOutcome,
    Role,
    RoundHistoryItem,
    RoundSummary,
    Signals,
    StopReason,
)

if TYPE_CHECKING:
    from .engine import Engine

CONTROLLER = {"author_participant_id": "controller", "author_role": Role.CONTROLLER}


def _delta(a: Optional[Combined], b: Optional[Combined], label_a: str, label_b: str) -> Delta:
    if a is None or b is None or a.status != "complete" or b.status != "complete":
        return Delta(value=None, comparable=False, note=f"{label_a} or {label_b} has no judgement under the current comparison key")
    if a.key != b.key:
        return Delta(value=None, comparable=False, note="non-comparable: judged under different keys; earlier result preserved")
    return Delta(value=round(a.aggregate - b.aggregate, 4), comparable=True, note="matched inputs")


def build_round_summary(engine: "Engine", *, key: ComparisonKey, outcome: PromotionOutcome, note: str,
                        prior_incumbent: Optional[str], challenger_id: Optional[str], combs: dict[str, Combined]) -> RoundSummary:
    store = engine.store
    d = store.data
    r = d.round
    inc_id = d.incumbent_version_id
    inc = combs.get(inc_id) if inc_id else None
    if inc_id and inc is None:
        inc = engine.combined(inc_id, key)
    winner = inc
    prior = combs.get(prior_incumbent) if prior_incumbent else None
    if prior_incumbent and prior is None:
        prior = engine.combined(prior_incumbent, key)

    # delta vs parent: for the challenger version (or the winner when it is new)
    focus_id = challenger_id or inc_id
    dvp = Delta(note="no challenger")
    if focus_id:
        fv = d.option_versions[focus_id]
        if fv.parent_version_id:
            parent_c = engine.combined(fv.parent_version_id, key)
            dvp = _delta(combs.get(focus_id) or engine.combined(focus_id, key), parent_c, focus_id, fv.parent_version_id)
        else:
            dvp = Delta(note="option has no parent version")
    dvi = _delta(winner, prior, "round winner", "prior incumbent") if prior_incumbent else Delta(note="no prior incumbent (round 0)")
    # net vs round 0 incumbent
    round0 = next((h["version_id"] for h in d.incumbent_history if h["round"] == 0), None)
    nvr0 = _delta(winner, engine.combined(round0, key) if round0 else None, "winner", "round-0 incumbent") if round0 else Delta(note="no round-0 incumbent")

    open_ch = store.open_challenges()
    resolved_this_round = [c.id for c in d.challenges.values() if c.status.value == "resolved" and
                           any(rp.challenge_id == c.id and rp.round == r for rp in d.responses.values())]
    new_versions = [v.id for v in d.option_versions.values() if v.round == r and r > 0]
    new_evidence = [e.id for e in d.evidence.values() if e.round == r and r > 0 and e.verification_status.value != "unavailable"]
    comparable = outcome not in (PromotionOutcome.NON_COMPARABLE,) and (dvi.comparable or r == 0 or outcome in (PromotionOutcome.NO_CHALLENGER,))
    blocking = engine.blocking_challenges()
    productive = bool(new_versions or resolved_this_round or new_evidence or outcome in (PromotionOutcome.PROMOTED, PromotionOutcome.INCUMBENT_INELIGIBLE))
    materiality = engine.cfg.judge.materiality_threshold
    small_gain = dvi.comparable and dvi.value is not None and abs(dvi.value) < materiality
    if r > 0 and comparable and small_gain and not blocking:
        streak = d.stable_streak + 1
    else:
        streak = 0
    ranking = rank(list(combs.values()))
    non_comp = [vid for vid, c in combs.items() if c.status != "complete"]
    summary = RoundSummary(
        id=store.new_id("RoundSummary"), round=r, incumbent_version_id=inc_id, prior_incumbent_version_id=prior_incumbent,
        challenger_version_id=challenger_id, promotion_outcome=outcome, delta_vs_parent=dvp, delta_vs_prior_incumbent=dvi,
        net_vs_round0=nvr0, comparison_key=key, comparable=comparable, open_challenge_ids=[c.id for c in open_ch],
        open_critical_count=sum(1 for c in open_ch if c.severity.value == "critical"),
        resolved_challenge_ids=resolved_this_round, new_version_ids=new_versions, new_evidence_ids=new_evidence,
        dissent_ids=[x.id for x in d.dissents.values() if x.round == r], ranking=ranking, non_comparable_version_ids=non_comp,
        budget=d.budget.snapshot(engine.cfg.limits), productive=productive, stable_streak=streak, note=note, **CONTROLLER,
    )
    return summary


_COULD_RANK = {"action": 0, "eligibility": 1, "ranking": 2, "none": 3}
_SEVERITY_RANK = {"critical": 0, "material": 1, "minor": 2}


def challenge_priority(c: Any, inc_id: Optional[str], inc_claim_ids: set[str]) -> tuple[int, int, int]:
    """Order open objections by their relevance to the recommendation.

    Objections on the recommended option (or one of its claims) come first, then shared blind spots (``__all__``),
    then objections on other options; within a tier, what the objection could change (action > eligibility > ranking)
    and its severity (critical > material > minor) decide. The report's next action, decisive-uncertainty list and
    confidence basis follow this order, so a minor housekeeping objection on a third option can no longer become the
    "next action" (Run 2 benchmark finding)."""
    tgt = getattr(c, "target_ref", None)
    tier = 0 if (inc_id is not None and (tgt == inc_id or tgt in inc_claim_ids)) else (1 if tgt == "__all__" else 2)
    could = getattr(getattr(c, "could_change", None), "value", getattr(c, "could_change", "none"))
    sev = getattr(getattr(c, "severity", None), "value", getattr(c, "severity", "minor"))
    return (tier, _COULD_RANK.get(str(could), 3), _SEVERITY_RANK.get(str(sev), 2))


def build_decision(engine: "Engine") -> Decision:
    store = engine.store
    d = store.data
    cfg = engine.cfg
    last_summary = list(d.round_summaries.values())[-1] if d.round_summaries else None
    key = last_summary.comparison_key if last_summary is not None and last_summary.comparison_key else engine.key()
    if key.as_tuple() != engine.key().as_tuple():
        d.unfinished_checks.append(
            f"evidence snapshot changed after the final judging ({key.evidence_snapshot_id} -> {engine.key().evidence_snapshot_id}); "
            "options were not rescored under the new snapshot")
    inc_id = d.incumbent_version_id
    cands = engine.candidates()
    combs = [engine.combined(v.id, key) for v in cands]
    ranking = rank(combs)
    policy = store.current_policy()
    flips, robustness = sensitivity(policy, combs, cfg.judge) if policy else ([], None)
    inc_claim_ids = {c.id for c in d.claims.values() if c.option_version_id == inc_id} if inc_id else set()
    open_blocking = sorted(engine.blocking_challenges(), key=lambda c: challenge_priority(c, inc_id, inc_claim_ids))
    unresolved_ids = [c.id for c in d.challenges.values() if c.status.value in ("open", "unresolved_final")]
    lc_unresolved = [lc for lc in d.leader_challenges.values() if lc.status.value in ("open", "unresolved_final") and lc.could_alter_outcome]
    inc_v = d.option_versions.get(inc_id) if inc_id else None
    last = last_summary

    # Open action-level objections against the recommended option (or shared across all options) that were never
    # examined (no owner response, no verification) cannot make the recommendation firm, even when they do not block
    # further rounds because the budget is gone.
    inc_targets = {inc_id} | {c.id for c in d.claims.values() if c.option_version_id == inc_id} if inc_id else set()
    unexamined_action = [c for c in d.challenges.values() if c.status.value == "open" and c.could_change == CouldChange.ACTION
                         and (c.target_ref in inc_targets or c.target_ref == "__all__")
                         and not any(r.challenge_id == c.id for r in d.responses.values())
                         and not c.verification_attempted
                         and not any(e.challenge_id == c.id and e.verification_status.value in ("verified", "user_supplied") for e in d.evidence.values())]
    unexamined_action.sort(key=lambda c: challenge_priority(c, inc_id, inc_claim_ids))
    # decision kind
    if inc_id is None:
        kind = DecisionOutcomeKind.NO_ELIGIBLE_OPTION
    elif inc_v is not None and inc_v.lens_id == "information_option":
        kind = DecisionOutcomeKind.INFORMATION_REQUEST
    elif lc_unresolved or any(c.could_change == CouldChange.ACTION for c in open_blocking) or unexamined_action:
        kind = DecisionOutcomeKind.CONDITIONAL
    elif (last is not None and last.promotion_outcome == PromotionOutcome.INCONCLUSIVE) or \
            (len(ranking) >= 2 and ranking[0][1] - ranking[1][1] < cfg.judge.materiality_threshold):
        kind = DecisionOutcomeKind.SHORTLIST
    else:
        kind = DecisionOutcomeKind.FIRM

    # signals
    cited: list[str] = []
    for j in d.judgements.values():
        if j.option_version_id == inc_id and j.comparison_key.as_tuple() == key.as_tuple():
            for s in j.criterion_scores:
                cited.extend(s.evidence_ids)
            for g in j.gate_results:
                cited.extend(g.evidence_ids)
    cited_unique = list(dict.fromkeys(cited))
    quality = None
    if cited_unique:
        good = sum(1 for e in cited_unique if d.evidence[e].verification_status.value in ("verified", "user_supplied"))
        quality = round(good / len(cited_unique), 4)
    inc_c = next((c for c in combs if c.version_id == inc_id), None)
    if inc_c is not None and inc_c.n_judges > 1:
        agreement = round(1.0 - inc_c.spread, 4)
        agreement_note = f"mean normalised score spread across {inc_c.n_judges} judges"
    else:
        agreement = None
        agreement_note = "single judge; agreement not measurable"
    decisive_uncertainty = [f"{c.id}: {c.resolution_condition or c.mechanism}" for c in open_blocking] + \
                           [f"{c.id} (unexamined): {c.resolution_condition or c.mechanism}" for c in unexamined_action if c not in open_blocking] + \
                           [f"{lc.id}: {lc.distinguishing_evidence}" for lc in lc_unresolved]
    signals = Signals(evidence_quality=quality, judge_agreement=agreement, judge_agreement_note=agreement_note,
                      ranking_robustness=robustness, ranking_flips=flips, decisive_uncertainty=decisive_uncertainty)

    # confidence
    clear_promotion = last is not None and last.promotion_outcome in (PromotionOutcome.PROMOTED, PromotionOutcome.RETAINED_TIE,
                                                                     PromotionOutcome.RETAINED_LOSS, PromotionOutcome.NO_CHALLENGER)
    open_critical = any(c.severity.value == "critical" for c in open_blocking) or bool(lc_unresolved) or bool(unexamined_action)
    robust = robustness is None or robustness >= 0.8
    checks = [kind in (DecisionOutcomeKind.FIRM, DecisionOutcomeKind.INFORMATION_REQUEST) and clear_promotion, not open_critical, robust]
    if all(checks):
        level = Confidence.HIGH
    elif sum(1 for c in checks if not c) == 1:
        level = Confidence.MEDIUM
    else:
        level = Confidence.LOW
    if level == Confidence.HIGH and any("not rescored" in u or "not (re)scored" in u for u in d.unfinished_checks):
        level = Confidence.MEDIUM  # an outstanding rescoring check caps confidence
    basis_parts = []
    if last is not None:
        basis_parts.append(f"last round outcome {last.promotion_outcome.value}")
    basis_parts.append("no open critical objection" if not open_critical else f"{len(open_blocking) + len(lc_unresolved)} open objection(s) with a credible path to change the outcome")
    basis_parts.append(f"ranking robustness {robustness}" if robustness is not None else "robustness not measurable (fewer than two eligible options)")
    raise_if = [lc.distinguishing_evidence for lc in lc_unresolved] + [c.resolution_condition for c in open_blocking if c.resolution_condition]
    lower_if = [f"{lc.losing_scenario}" for lc in lc_unresolved] + flips
    confidence = ConfidenceReport(level=level, basis="; ".join(basis_parts), raise_if=raise_if, lower_if=lower_if)

    # alternatives, dissent, trade-offs
    alternatives = [vid for vid, _ in ranking if vid != inc_id][:3]
    for v in cands:
        if v.id != inc_id and v.id not in alternatives and v.status.value != "merged":
            alternatives.append(v.id)
    withdrawn = [v.id for v in d.option_versions.values() if v.status.value == "withdrawn"]
    alternatives = alternatives[:5]
    dissent_ids = list(d.dissents)
    trade_offs = [x.what_you_lose for x in d.dissents.values() if x.what_you_lose]
    for c in d.challenges.values():
        if c.status.value == "resolved" and "conceded" in c.resolution_note:
            trade_offs.append(f"Conceded: {c.mechanism}")
    if inc_v is not None and len(ranking) >= 2:
        runner = d.option_versions[ranking[1][0]] if ranking[1][0] in d.option_versions else None
        if runner:
            trade_offs.append(f"Choosing '{inc_v.title}' over '{runner.title}' gives up: {runner.mechanism or runner.summary[:120]}")

    # next action and reversal conditions
    if kind == DecisionOutcomeKind.CONDITIONAL and lc_unresolved:
        next_action = f"Resolve the decisive uncertainty first: {lc_unresolved[0].distinguishing_evidence}"
    elif kind == DecisionOutcomeKind.CONDITIONAL and (open_blocking or unexamined_action):
        first = (open_blocking or unexamined_action)[0]
        next_action = f"Resolve: {first.resolution_condition or first.mechanism}"
    elif kind == DecisionOutcomeKind.INFORMATION_REQUEST and inc_v is not None:
        next_action = f"Run the information-gathering step: {inc_v.summary[:200]}"
    elif kind == DecisionOutcomeKind.SHORTLIST and len(ranking) >= 2:
        next_action = f"Decide between {ranking[0][0]} and {ranking[1][0]}: obtain {signals.decisive_uncertainty[0] if signals.decisive_uncertainty else 'the evidence that separates them'}"
    elif kind == DecisionOutcomeKind.NO_ELIGIBLE_OPTION:
        next_action = "No option passes the hard gates; relax a constraint or widen the option set, then rerun."
    elif inc_v is not None:
        next_action = f"Start '{inc_v.title}': {inc_v.mechanism or inc_v.summary[:160]}"
    else:
        next_action = "n/a"
    reversal = [f"If: {lc.losing_scenario} -> prefer {lc.strongest_alternative_version_id}" for lc in d.leader_challenges.values()]
    reversal += [f"If '{c.resolution_condition}' fails for {c.target_ref}" for c in d.challenges.values() if c.status.value in ("open", "unresolved_final") and c.resolution_condition and c.target_ref == inc_id]
    reversal += [f"If assumption fails ({a.text}): {a.if_false_effect}" for a in d.assumptions.values() if a.influential and a.option_version_id == inc_id and a.if_false_effect]

    history = [RoundHistoryItem(round=s.round, incumbent_version_id=s.incumbent_version_id, promotion_outcome=s.promotion_outcome,
                                incumbent_score=next((agg for vid, agg in s.ranking if vid == s.incumbent_version_id), None),
                                delta_vs_prior_incumbent=s.delta_vs_prior_incumbent, net_vs_round0=s.net_vs_round0,
                                comparable=s.comparable, open_critical_count=s.open_critical_count)
               for s in sorted(d.round_summaries.values(), key=lambda s: s.round)]
    failed_to_establish = [e.statement for e in d.evidence.values() if e.verification_status.value == "unavailable"]
    if inc_c is not None and inc_c.unverified_gates:
        failed_to_establish.append(f"gates unverified for the recommended option: {inc_c.unverified_gates}")
    limitations = list(d.limitations)
    if any(p.isolation.value == "shared" for p in d.participants.values()):
        limitations.append("Shared context: all roles served through one conversation; pseudonymisation was not applied because it would not withhold information; no blind review is claimed.")
    providers = sorted({p.provider for p in d.participants.values()})
    if d.discussion and (d.effective_config.get("discussion") or {}).get("include", "current_round_and_summaries") != "none":
        limitations.append("Discussion transcript shared with every role (each request carries the other roles' contributions), so no role answered blind to the others.")
    if d.documents:
        limitations.append(f"User documents: {len(d.documents)} file(s) registered as user-supplied evidence (ev_doc_*); excerpts capped per request, full copies under inputs/.")
    limitations.append(f"Providers used: {', '.join(providers) or 'none'}; tokens are {'measured' if d.budget.tokens_measured and not d.budget.tokens_estimated else 'estimated (len/4)' if d.budget.tokens_estimated and not d.budget.tokens_measured else 'partly measured, partly estimated'}; cost {d.budget.cost_status}.")
    if withdrawn:
        limitations.append(f"Withdrawn options: {withdrawn}")
    return Decision(
        id=store.new_id("Decision"), kind=kind, recommended_version_id=inc_id, alternatives=alternatives,
        decisive_evidence_ids=cited_unique[:10], material_dissent_ids=dissent_ids, unresolved_challenge_ids=unresolved_ids,
        trade_offs=trade_offs, confidence=confidence, signals=signals, stop_reason=d.stop_reason or StopReason.FAILED,
        unfinished_checks=list(dict.fromkeys(d.unfinished_checks)), next_action=next_action, reversal_conditions=reversal,
        round_history=history, limitations=limitations, failed_to_establish=failed_to_establish,
        completed_phases=list(d.completed_phases), budget=d.budget.snapshot(cfg.limits), **CONTROLLER,
    )


def _fmt(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:+.2f}" if isinstance(x, float) and x != 0 else ("0.00" if x == 0 else str(x))


MIN_REPORT_WORDS = 600


def _words(text: str) -> int:
    return len(text.split())


def plain_words_lines(engine: "Engine", dec: Decision, key: ComparisonKey) -> list[str]:
    """Plain-language summary: the decision, what to do, why it won, honest caveats.

    Everything here restates committed records (recommended option, judges' combined scores,
    stop reason, unfinished checks, reversal conditions) — no new facts, so it stays truthful
    on reruns and under every preset."""
    store = engine.store
    d = store.data
    inc = d.option_versions.get(dec.recommended_version_id) if dec.recommended_version_id else None
    if inc is None:
        return ["No option passed the hard gates, so there is no recommendation — only the evidence, "
                "the failed gates, and what to change before rerunning, below."]
    kind_word = {
        "firm": "The council's firm recommendation is",
        "conditional": "The council's conditional recommendation is (it holds only if the caveats below are resolved)",
        "shortlist": "The council could not pick a single winner; its leaning is",
        "information_request": "The council's first step is information-gathering, not action",
        "no_eligible_option": "The council found",
    }.get(dec.kind.value, "The council's call is")
    out = [f"{kind_word}: **{inc.title}** (confidence: {dec.confidence.level.value}).",
           "",
           f"What that means in practice: {inc.mechanism or inc.summary}"]
    alt_combs = {vid: engine.combined(vid, key) for vid in dec.alternatives if vid in d.option_versions}
    me = engine.combined(inc.id, key)
    scored = {vid: c for vid, c in alt_combs.items() if c.status == "complete"}
    if me.status == "complete" and scored:
        best_vid, best = max(scored.items(), key=lambda t: t[1].aggregate)
        best_v = d.option_versions[best_vid]
        out += ["",
                f"Why this one: it scored {me.aggregate:.2f}, ahead of the strongest alternative "
                f"'{best_v.title}' at {best.aggregate:.2f}. The criterion-by-criterion scores behind those "
                f"numbers are under Round-by-round decision quality."]
    elif me.status == "complete" or scored:
        out += ["",
                "Why this one: it was the only option fully judged under the final comparison. The others "
                "below were proposed but never scored against it, so treat them as refinements to consider, "
                "not rejected ideas."]
    else:
        out += ["",
                "Why this one: there is no complete judging under the final comparison — the recommendation "
                "rests on the round process recorded below, and the confidence level reflects exactly that."]
    caveats: list[str] = []
    unjudged = [d.option_versions[vid].title for vid, c in alt_combs.items() if c.status != "complete"]
    if unjudged:
        caveats.append(f"{' / '.join(unjudged)} {'was' if len(unjudged) == 1 else 'were'} proposed but never "
                       f"scored under the final comparison.")
    if d.stop_reason.value != "stable":
        caveats.append(f"The run stopped on '{d.stop_reason.value}' rather than converging.")
    if dec.unfinished_checks:
        caveats.append(f"{len(dec.unfinished_checks)} unfinished check(s) are listed under Unfinished checks.")
    out += ["", "The honest caveats: " + (" ".join(caveats) if caveats else "none — the run converged with no outstanding checks.")]
    if dec.reversal_conditions:
        out += ["", f"The clearest tripwire: {dec.reversal_conditions[0]}"]
    return out


def fixture_replay_note(d: Any) -> Optional[str]:
    """Set when any participant was served by the fixture provider: the content is a recorded test transcript."""
    if any(p.provider == "fixture" for p in d.participants.values()):
        fp = (d.effective_config or {}).get("fixture_path") or "a fixture file"
        return (f"TEST REPLAY — the answers in this run come from the recorded fixture `{fp}`, not from a model. "
                "They do not respond to the question above; the run only demonstrates the controller.")
    return None


def chat_label(d: Any) -> str:
    return d.chat_model or "conversation model (identity not declared)"


def answer_details(store) -> dict[str, dict[str, Any]]:
    """Per request id: who answered and at what cost — provider, model, tokens (+kind), latency, effort, outcome.

    Taken from the ``response_committed`` / ``response_rejected`` event payloads; for runs recorded before those
    payloads carried the detail, the values are derived from the files: latency = response file time − request file
    time, tokens ≈ response size / 4 (labelled ``estimated``), provider/model from the participant record."""
    import json as _json
    d = store.data
    out: dict[str, dict[str, Any]] = {}
    path = store.run_dir / "events.jsonl"
    if not path.exists():
        return out
    by_req: dict[str, dict[str, Any]] = {}
    for line in path.read_text().splitlines():
        try:
            e = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        p = e.get("payload") or {}
        rid = p.get("request_id")
        if not rid:
            continue
        if e.get("kind") == "request_issued":
            by_req[rid] = {"participant": p.get("participant"), "provider": p.get("provider"), "round": e.get("round"), "phase": e.get("state_after"),
                           "role": p.get("role"), "attempt": p.get("attempt"), "issued_at": e.get("created_at")}
        elif e.get("kind") in ("response_committed", "response_rejected", "request_failed"):
            base = by_req.get(rid, {})
            part = d.participants.get(base.get("participant") or "")
            det = {"outcome": e["kind"], "error": p.get("error"), "provider": p.get("provider") or (part.provider if part else base.get("provider")),
                   "model": p.get("model") or (part.model_reported or part.model_requested if part else None), "tokens": p.get("tokens"),
                   "tokens_kind": p.get("tokens_kind"), "tokens_detail": p.get("tokens_detail") or {}, "latency_seconds": p.get("latency_seconds"),
                   "effort": p.get("effort") or (part.effort if part else None), "answered_at": e.get("created_at")}
            if det["provider"] == "chat" and not det["model"]:
                det["model"] = chat_label(d)
            rq, rp = store.run_dir / "requests" / f"{rid}.json", store.run_dir / "responses" / f"{rid}.json"
            if det["tokens"] is None and rp.exists():
                det["tokens"], det["tokens_kind"] = max(1, rp.stat().st_size // 4), "estimated"
            if det["latency_seconds"] is None and rq.exists() and rp.exists():
                det["latency_seconds"] = round(max(0.0, rp.stat().st_mtime - rq.stat().st_mtime), 1)
            out[rid] = {**base, **det}
    return out


def backfill_participant_usage(store) -> None:
    """Runs recorded before per-answer accounting existed have ``calls == 0`` on every participant: derive calls,
    tokens and latency from the event log and the request/response files so reports stay truthful."""
    d = store.data
    if not d.participants or any(p.tokens or p.latency_seconds for p in d.participants.values()):
        return
    for p in d.participants.values():      # recount from the log (an earlier backfill may have set calls only)
        p.calls = 0
    for rid, det in answer_details(store).items():
        pid = det.get("participant")
        if pid in d.participants and det.get("outcome") in ("response_committed", "response_rejected"):
            p = d.participants[pid]
            p.calls += 1
            p.tokens += int(det.get("tokens") or 0)
            p.latency_seconds += float(det.get("latency_seconds") or 0.0)
            p.effort = p.effort or det.get("effort")


def render_report(engine: "Engine", dec: Decision) -> str:
    backfill_participant_usage(engine.store)
    store = engine.store
    d = store.data
    brief = store.current_brief()
    inc = d.option_versions.get(dec.recommended_version_id) if dec.recommended_version_id else None
    lines: list[str] = []
    lines.append(f"# Strategy Tribunal — decision record — run `{d.run_id}`")
    lines.append("")
    note = fixture_replay_note(d)
    if note:
        lines.append(f"> **⚠ {note}**")
        lines.append("")
    lines.append(f"**Question:** {d.question}")
    if brief:
        lines.append(f"**Decision framed:** {brief.decision_statement} (stakes {brief.stakes.value}, reversibility {brief.reversibility.value}, domain {brief.domain.value})")
    lines.append("")
    lines.append(f"## Outcome: {dec.kind.value.replace('_', ' ')}")
    if inc:
        lines.append(f"**Recommended action:** {inc.title} — {inc.summary}")
    else:
        lines.append("**No eligible option.**")
    lines.append(f"**Stopping reason:** {dec.stop_reason.value}")
    lines.append(f"**Confidence:** {dec.confidence.level.value} — {dec.confidence.basis}")
    lines.append(f"**Next action:** {dec.next_action}")
    lines.append("")
    last_summary = list(d.round_summaries.values())[-1] if d.round_summaries else None
    dec_key = last_summary.comparison_key if last_summary is not None and last_summary.comparison_key else engine.key()
    lines.append("## In plain words")
    lines.extend(plain_words_lines(engine, dec, dec_key))
    lines.append("")
    lines.append("## Strongest alternatives")
    for vid in dec.alternatives:
        v = d.option_versions[vid]
        c = engine.combined(vid, dec_key)
        score = f"{c.aggregate:.2f} [{c.lower:.2f}, {c.upper:.2f}]" if c.status == "complete" else "not judged under current key"
        lines.append(f"- `{vid}` {v.title} ({v.status.value}) — {score}")
    lines.append("")
    lines.append("## Decisive evidence")
    for e in dec.decisive_evidence_ids:
        ev = d.evidence[e]
        lines.append(f"- `{e}` [{ev.verification_status.value}] {ev.statement} (source: {ev.source.kind.value} {ev.source.ref})")
    if not dec.decisive_evidence_ids:
        lines.append("- none cited")
    lines.append("")
    lines.append("## Material dissent and unresolved objections")
    for did in dec.material_dissent_ids:
        x = d.dissents[did]
        lines.append(f"- Dissent `{did}` against `{x.against_ref}`: {x.position} — {x.reason}" + (f" What you lose: {x.what_you_lose}" if x.what_you_lose else ""))
    for cid in dec.unresolved_challenge_ids:
        c = d.challenges[cid]
        lines.append(f"- Challenge `{cid}` [{c.status.value}, {c.severity.value}, could change {c.could_change.value}] on `{c.target_ref}`: {c.mechanism}")
    if not dec.material_dissent_ids and not dec.unresolved_challenge_ids:
        lines.append("- none")
    lines.append("")
    lines.append("## Trade-offs")
    for t in dec.trade_offs or ["none recorded"]:
        lines.append(f"- {t}")
    lines.append("")
    lines.append("## Round-by-round decision quality")
    lines.append("| round | incumbent | outcome | score | Δ vs prior incumbent | net vs round 0 | comparable | open critical |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for h in dec.round_history:
        lines.append(f"| {h.round} | `{h.incumbent_version_id}` | {h.promotion_outcome.value} | {('%.2f' % h.incumbent_score) if h.incumbent_score is not None else 'n/a'} | "
                     f"{_fmt(h.delta_vs_prior_incumbent.value)}{'' if h.delta_vs_prior_incumbent.comparable else ' (non-comparable)'} | "
                     f"{_fmt(h.net_vs_round0.value)}{'' if h.net_vs_round0.comparable else ' (non-comparable)'} | {h.comparable} | {h.open_critical_count} |")
    lines.append("")
    lines.append("## Signals (reported separately)")
    s = dec.signals
    lines.append(f"- Evidence quality: {s.evidence_quality}")
    lines.append(f"- Judge agreement: {s.judge_agreement} ({s.judge_agreement_note})")
    lines.append(f"- Ranking robustness: {s.ranking_robustness}; flips: {s.ranking_flips or 'none'}")
    lines.append(f"- Decisive uncertainty: {s.decisive_uncertainty or 'none'}")
    lines.append(f"- Confidence raises if: {dec.confidence.raise_if or 'n/a'}; lowers if: {dec.confidence.lower_if or 'n/a'}")
    lines.append("")
    lines.append("## Reopen or reverse when")
    for r in dec.reversal_conditions or ["no reversal conditions recorded"]:
        lines.append(f"- {r}")
    lines.append("")
    lines.append("## What the council failed to establish")
    for f in dec.failed_to_establish or ["nothing outstanding"]:
        lines.append(f"- {f}")
    lines.append("")
    lines.append("## Unfinished checks")
    for u in dec.unfinished_checks or ["none"]:
        lines.append(f"- {u}")
    lines.append("")
    lines.append("## Reasoning workflow (what the models did, by round)")
    from .trail import reasoning_trail
    for s in reasoning_trail(store):
        by = "controller" if s["participant"] == "controller" else f"{s['role']} · {s['who']}"
        lines.append(f"- r{s['round']} {s['phase']} · **{s['kind']}** · {by}: {s['what']}")
    lines.append("")
    lines.append("## Who answered (orchestration view)")
    lines.append("| participant | role | lens | answered by | isolation | calls | tokens | avg latency | effort |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for p in d.participants.values():
        who = f"{p.provider} · {p.model_reported or p.model_requested or (chat_label(d) if p.provider == 'chat' else '?')}"
        avg = f"{p.latency_seconds / p.calls:.1f} s" if p.calls and p.latency_seconds else "n/a"
        lines.append(f"| `{p.id}` | {p.role.value} | {p.lens_id or ''} | {who} | {p.isolation.value} | {p.calls} | {p.tokens:,} | {avg} | {p.effort or ''} |")
    if d.chat_model:
        lines.append(f"\nConversation model declared for chat-routed roles: `{d.chat_model}`.")
    else:
        lines.append("\nChat-routed roles were answered by the conversation model; its identity was not declared (`--chat-model`).")
    lines.append("")
    lines.append("## Lineage of the recommended option")
    if inc:
        chain = []
        cur = inc
        while cur is not None:
            chain.append(cur)
            cur = d.option_versions.get(cur.parent_version_id) if cur.parent_version_id else None
        for v in reversed(chain):
            lines.append(f"- `{v.id}` v{v.version} (round {v.round}, lens {v.lens_id}): {v.change_reason or 'initial'}")
    lines.append("")
    lines.append("## Budget")
    b = dec.budget
    lines.append(f"- Model calls: {b.model_calls_used}/{b.model_calls_limit} (measured)")
    lines.append(f"- Tokens: measured {b.tokens_measured}, estimated {b.tokens_estimated} (limit {b.tokens_limit})")
    lines.append(f"- Elapsed: {b.elapsed_seconds}s / {b.elapsed_limit}s (measured)")
    lines.append(f"- Cost: {b.cost_usd if b.cost_usd is not None else 'unavailable'} ({b.cost_status})")
    lines.append("")
    lines.append("## Limitations")
    for l in dec.limitations:
        lines.append(f"- {l}")
    lines.append("")
    if _words("\n".join(lines)) < MIN_REPORT_WORDS:
        lines.append("## Appendix: options in full (so this report stands alone)")
        seen: set[str] = set()
        for vid in ([dec.recommended_version_id] if dec.recommended_version_id else []) + dec.alternatives:
            v = d.option_versions.get(vid) if vid else None
            if v is None or vid in seen:
                continue
            seen.add(vid)
            lines.append(f"### {v.title} (`{vid}`, {v.status.value})")
            lines.append(v.summary)
            if v.mechanism:
                lines.append(f"How it works: {v.mechanism}")
            lines.append("")
        for a in d.assumptions.values():
            lines.append(f"- Assumption ({'influential' if a.influential else 'background'}): {a.text}"
                         + (f" If false: {a.if_false_effect}" if a.if_false_effect else ""))
        if _words("\n".join(lines)) < MIN_REPORT_WORDS:
            for c in d.challenges.values():
                lines.append(f"- Challenge `{c.id}` [{c.status.value}, {c.severity.value}]: {c.mechanism} "
                             f"Resolution: {c.resolution_condition or 'none recorded'}")
        lines.append("")
    lines.append(f"Completed phases: {', '.join(dec.completed_phases)}")
    lines.append("")
    lines.append("Machine-readable record: `decision.json` next to this report.")
    fu = followup_prompt(engine, dec)
    if fu:
        lines.append("")
        lines.append("## Follow-up prompt (copy into the chat to continue)")
        lines.append("")
        lines.append("```text")
        lines.append(fu)
        lines.append("```")
    return "\n".join(lines)


def followup_prompt(engine: "Engine", dec: Decision) -> str:
    """A self-contained prompt to paste into the chat once the report is out: the question, what the council decided
    and why, what is still open, and the ask (plan the next action). Empty when the run produced no recommendation."""
    d = engine.store.data
    inc = d.option_versions.get(dec.recommended_version_id) if dec.recommended_version_id else None
    if inc is None and dec.kind.value not in ("information_request", "shortlist"):
        return ""
    brief = engine.store.current_brief()
    ov = d.option_versions

    def t(vid):
        return ov[vid].title if vid in ov else vid

    out: list[str] = []
    out.append("Continue from the council decision below. Act as the owner of the next step.")
    out.append("")
    out.append(f"Context. Question put to the council: {d.question}")
    if brief:
        out.append(f"Decision framed: {brief.decision_statement}")
        if brief.hard_constraints:
            out.append("Hard constraints: " + "; ".join(c.text for c in brief.hard_constraints[:6]))
    out.append("")
    out.append(f"Council outcome: {dec.kind.value.replace('_', ' ')}, confidence {dec.confidence.level.value} ({dec.confidence.basis}). Stopped because: {dec.stop_reason.value}.")
    if inc:
        out.append(f"Recommended action: {inc.title} — {inc.summary}")
        if inc.mechanism:
            out.append(f"Why it should work: {inc.mechanism}")
    if dec.alternatives:
        out.append("Strongest alternatives considered: " + "; ".join(t(a) for a in dec.alternatives[:4]))
    if dec.trade_offs:
        out.append("Trade-offs accepted: " + "; ".join(dec.trade_offs[:4]))
    out.append(f"Next action the council named: {dec.next_action}")
    if dec.reversal_conditions:
        out.append("Reverse or reopen if: " + " | ".join(dec.reversal_conditions[:4]))
    open_ch = [d.challenges[c] for c in dec.unresolved_challenge_ids if c in d.challenges]
    if open_ch:
        out.append("Objections still open: " + " | ".join(f"{c.id} [{c.severity.value}] {c.mechanism[:160]} (resolve by: {c.resolution_condition or 'not stated'})" for c in open_ch[:5]))
    if dec.unfinished_checks:
        out.append("Unfinished checks: " + " | ".join(dec.unfinished_checks[:5]))
    inf = [a for a in d.assumptions.values() if a.influential]
    if inf:
        out.append("Influential assumptions to validate: " + " | ".join(f"{a.id}: {a.text[:140]}" for a in inf[:5]))
    out.append("")
    out.append(f"Records: run folder {engine.store.run_dir} (report.md, decision.json, discussion.md, requests/, responses/). Read them if you need detail.")
    out.append("")
    out.append("Your task now:")
    out.append("1. Restate the recommended action in one paragraph and confirm it still fits the constraints above; flag anything that changed since the council ran.")
    out.append("2. Turn 'Next action' into a concrete plan: steps in order, owner for each, what each step produces, dates or durations, and the metric and threshold that says it worked.")
    out.append("3. For every open objection, unfinished check and influential assumption: the cheapest test that settles it, and what we do if it fails.")
    out.append("4. Name the first thing to do tomorrow morning and what you need from me to start.")
    out.append("5. If you disagree with the council, say so and why, using its own evidence ids.")
    out.append("Answer in the language of the question.")
    return "\n".join(out)


def chat_summary(engine: "Engine", dec: Decision) -> str:
    d = engine.store.data
    inc = d.option_versions.get(dec.recommended_version_id) if dec.recommended_version_id else None
    head = f"{dec.kind.value.upper()}: {inc.title if inc else 'no eligible option'}"
    note = fixture_replay_note(d)
    if note:
        head = f"⚠ {note}\n{head}"
    return (f"{head}\nConfidence {dec.confidence.level.value}; stop reason {dec.stop_reason.value}; rounds {max((h.round for h in dec.round_history), default=0)}.\n"
            f"Next action: {dec.next_action}\nUnresolved: {len(dec.unresolved_challenge_ids)}; alternatives: {', '.join(dec.alternatives[:3]) or 'none'}.")
