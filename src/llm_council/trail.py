"""The reasoning workflow, reconstructed from the committed records.

Two workflows run in every council:

* the **orchestration workflow** — the controller's state machine (phases, requests, validation, budgets, stops);
  it is deterministic Python and never reasons about the question;
* the **reasoning workflow** — what the models did in their roles: how the question was framed, which gates and
  criteria were registered, which options were proposed through which lenses, which objections were raised and how
  the owners answered, how the judge scored, whether a challenger displaced the incumbent, what the leader
  challenge argued, and what was finally decided.

``reasoning_trail`` returns the second one as an ordered list of steps (round, phase, actor role, who answered,
what they produced, record ids), built only from the records in ``state.json``.
"""

from __future__ import annotations

from typing import Any, Optional


def _who(d: Any, participant_id: Optional[str]) -> tuple[str, str, str]:
    p = d.participants.get(participant_id or "")
    if p is None:
        return ("controller", "controller", "controller (Python, no model)")
    model = p.model_reported or p.model_requested or (d.chat_model if p.provider == "chat" else None) or ("conversation model (identity not declared)" if p.provider == "chat" else "?")
    return (p.role.value, p.provider, f"{p.provider} · {model}")


def _step(d: Any, *, round_no: int, phase: str, kind: str, participant: Optional[str], what: str, ids: list[str], at: str = "") -> dict[str, Any]:
    role, provider, who = _who(d, participant)
    return {"round": round_no, "phase": phase, "kind": kind, "role": role if participant else "controller", "participant": participant or "controller",
            "provider": provider, "who": who, "what": what, "ids": ids, "at": at}


def reasoning_trail(store) -> list[dict[str, Any]]:
    d = store.data
    steps: list[dict[str, Any]] = []
    ov = d.option_versions

    def title(vid: Optional[str]) -> str:
        return ov[vid].title if vid and vid in ov else (vid or "—")

    # framing (one step per brief version: a reframe adds a version)
    for b in d.briefs.values():
        steps.append(_step(d, round_no=0 if b.version == 1 else max(1, d.round), phase="FRAMING", kind="frame", participant=b.author_participant_id,
                           what=f"brief v{b.version}: {b.decision_statement} [stakes {b.stakes.value}, reversibility {b.reversibility.value}, kind {b.decision_kind.value}]"
                                + (f"; {len(b.inferred_assumptions)} inferred assumption(s), {len(b.evidence_gaps)} evidence gap(s)" if b.inferred_assumptions or b.evidence_gaps else ""),
                           ids=[b.id], at=b.created_at))
    # policy
    for pol in d.policies.values():
        gates = [c.name for c in pol.gate_criteria]
        scores = [f"{c.name} (w {c.weight:g})" for c in pol.score_criteria]
        steps.append(_step(d, round_no=0, phase="POLICY", kind="policy", participant=pol.author_participant_id,
                           what=f"rubric v{pol.rubric_version}: gates {gates or ['none']}; criteria {scores}; {len(pol.scenarios)} scenario(s); materiality {pol.materiality_threshold:g}"
                                + (f"; weight overrides applied {pol.weight_overrides_applied}" if pol.weight_overrides_applied else ""),
                           ids=[pol.id], at=pol.created_at))
    # options (baseline round 0, lenses later) — group by round and lens
    by_group: dict[tuple[int, Optional[str], str, bool], list[Any]] = {}
    for v in ov.values():
        by_group.setdefault((v.round, v.lens_id, v.author_participant_id, v.parent_version_id is not None), []).append(v)
    for (r, lens, pid, revised), vs in sorted(by_group.items(), key=lambda kv: (kv[0][0], min(v.created_at for v in kv[1]))):
        if revised:
            what = "revised " + "; ".join(f"“{v.title}” v{v.version} from {title(v.parent_version_id)}" + (f" — {v.change_reason}" if v.change_reason else "") for v in vs)
            phase, kind = "RESPONDING", "revisions"
        else:
            what = "proposed " + "; ".join(f"“{v.title}”" + (" (status quo)" if "status quo" in v.title.lower() else "") for v in vs)
            phase, kind = ("BASELINE" if lens == "direct" and r == 0 else "GENERATING"), "options"
        merged = [v for v in vs if v.status.value == "merged"]
        if merged:
            what += f"; {len(merged)} merged as duplicate"
        steps.append(_step(d, round_no=r, phase=phase, kind=kind, participant=pid, what=(f"lens {lens}: " if lens else "") + what,
                           ids=[v.id for v in vs], at=min(v.created_at for v in vs)))
    # challenges per reviewer per round
    by_rev: dict[tuple[int, str], list[Any]] = {}
    for c in d.challenges.values():
        by_rev.setdefault((c.round, c.author_participant_id), []).append(c)
    for (r, pid), cs in sorted(by_rev.items(), key=lambda kv: (kv[0][0], min(c.created_at for c in kv[1]))):
        items = "; ".join(f"{c.severity.value} on {title(c.target_ref) if c.target_ref in ov else c.target_ref} ({c.challenge_class.value}, could change {c.could_change.value}): {c.mechanism[:110]}" for c in cs)
        steps.append(_step(d, round_no=r, phase="REVIEWING" if pid.startswith("p_reviewer") else ("CHALLENGING" if pid == "p_challenger" else "REVIEWING"),
                           kind="challenges", participant=pid, what=f"{len(cs)} objection(s): {items}", ids=[c.id for c in cs], at=min(c.created_at for c in cs)))
    for ds in d.dissents.values():
        steps.append(_step(d, round_no=ds.round, phase="REVIEWING", kind="dissent", participant=ds.participant_id,
                           what=f"dissent against {title(ds.against_ref) if ds.against_ref in ov else ds.against_ref}: {ds.position} — {ds.reason[:120]}", ids=[ds.id], at=ds.created_at))
    # verification evidence
    ver = [e for e in d.evidence.values() if e.challenge_id]
    by_ver: dict[tuple[int, str], list[Any]] = {}
    for e in ver:
        by_ver.setdefault((e.round, e.author_participant_id), []).append(e)
    for (r, pid), es in sorted(by_ver.items()):
        steps.append(_step(d, round_no=r, phase="VERIFYING", kind="verification", participant=pid,
                           what="; ".join(f"{e.verification_status.value}: {e.statement[:100]} (for {e.challenge_id})" for e in es), ids=[e.id for e in es], at=min(e.created_at for e in es)))
    # responses
    by_resp: dict[tuple[int, str], list[Any]] = {}
    for rsp in d.responses.values():
        by_resp.setdefault((rsp.round, rsp.author_participant_id), []).append(rsp)
    for (r, pid), rs in sorted(by_resp.items(), key=lambda kv: (kv[0][0], min(x.created_at for x in kv[1]))):
        items = "; ".join(f"{x.kind.value} {x.challenge_id}" + (f" → {title(x.new_version_id)}" if x.new_version_id else "") + f": {x.text[:90]}" for x in rs)
        steps.append(_step(d, round_no=r, phase="RESPONDING", kind="responses", participant=pid, what=items, ids=[x.id for x in rs], at=min(x.created_at for x in rs)))
    # judgements per judge per round
    by_j: dict[tuple[int, str], list[Any]] = {}
    for j in d.judgements.values():
        by_j.setdefault((j.round, j.participant_id), []).append(j)
    for (r, pid), js in sorted(by_j.items(), key=lambda kv: (kv[0][0], min(j.created_at for j in kv[1]))):
        scored = "; ".join(f"{title(j.option_version_id)} = {j.aggregate:.2f}" + (f" (gate failed: {', '.join(j.failed_gates)})" if getattr(j, 'failed_gates', None) else "") if j.aggregate is not None else f"{title(j.option_version_id)} = {j.status.value}" for j in js)
        steps.append(_step(d, round_no=r, phase="JUDGING", kind="judgements", participant=pid, what=f"scored {len(js)} version(s): {scored}", ids=[j.id for j in js], at=min(j.created_at for j in js)))
    for cmp in d.comparisons.values():
        pref = {"first": title(cmp.first_version_id), "second": title(cmp.second_version_id), "tie": "tie"}[cmp.preferred]
        steps.append(_step(d, round_no=cmp.round, phase="JUDGING", kind="compare", participant=cmp.author_participant_id,
                           what=f"pairwise {title(cmp.first_version_id)} vs {title(cmp.second_version_id)} → {pref}", ids=[cmp.id], at=cmp.created_at))
    # controller decisions per round
    for rs in d.round_summaries.values():
        inc, prior = title(rs.incumbent_version_id), title(rs.prior_incumbent_version_id)
        delta = f"{rs.delta_vs_prior_incumbent.value:+.2f}" if rs.delta_vs_prior_incumbent.comparable and rs.delta_vs_prior_incumbent.value is not None else "n/a"
        what = {"baseline": f"baseline incumbent set: {inc}", "promoted": f"{title(rs.challenger_version_id)} promoted over {prior} ({delta})",
                "retained_tie": f"{inc} kept — tie within materiality with {title(rs.challenger_version_id)}", "retained_loss": f"{inc} kept — {title(rs.challenger_version_id)} lost ({delta})",
                "inconclusive": f"{inc} kept — inconclusive comparison", "rejected_regression": f"revision rejected, {inc} kept"}.get(rs.promotion_outcome.value, rs.promotion_outcome.value)
        steps.append(_step(d, round_no=rs.round, phase="REVISING", kind="adjudication", participant=None,
                           what=what + (f"; {rs.open_critical_count} critical objection(s) open" if rs.open_critical_count else "") + (f"; {rs.note}" if rs.note else ""), ids=[rs.id], at=rs.created_at))
    # leader challenge
    for lc in d.leader_challenges.values():
        steps.append(_step(d, round_no=lc.round, phase="CHALLENGING", kind="leader_challenge", participant=lc.author_participant_id,
                           what=f"against {title(lc.leader_version_id)}: loses if {lc.losing_scenario[:120]}; strongest alternative {title(lc.strongest_alternative_version_id)}; distinguishing evidence: {lc.distinguishing_evidence[:100]}; status {lc.status.value}",
                           ids=[lc.id], at=lc.created_at))
    # decision
    if d.decision is not None:
        dec = d.decision
        steps.append(_step(d, round_no=d.round, phase="REPORTING", kind="decision", participant=None,
                           what=f"{dec.kind.value}: {title(dec.recommended_version_id)}; confidence {dec.confidence.level.value}; stop {dec.stop_reason.value}; next action: {dec.next_action[:120]}",
                           ids=[dec.id], at=dec.created_at))
    steps.sort(key=lambda s: (s["round"], s["at"]))
    return steps
