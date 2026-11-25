"""The benchmark checkers must not pass vacuously (field names, substrings inside words, empty titles)."""
from __future__ import annotations

import json
import sys

from conftest import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "benchmarks"))
import run_campaign as rc  # noqa: E402

SPEC = json.loads((PROJECT_ROOT / "benchmarks" / "cases.json").read_text())
CASES = {c["id"]: c for c in SPEC["cases"]}
LIMITS = SPEC["resource_limits"]


def _run(**kw) -> dict:
    base = {"state": "COMPLETE", "elapsed_seconds": 100.0, "budget": {"model_calls_used": 10, "tokens_measured": 1000},
            "briefs": [], "challenges": [], "option_titles": {}, "judgement_gate_fails": [], "decision": {"kind": "firm", "signals": {}, "stop_reason": "stable"}}
    base.update(kw)
    return base


def test_premise_check_ignores_field_names_and_needs_the_planted_claim():
    case = CASES["false_premise"]
    # a brief whose only text is unrelated: the key name 'inferred_assumptions' must not count
    r = _run(briefs=[{"decision_statement": "x", "inferred_assumptions": ["budget is quarterly"], "evidence_gaps": [], "decision_kind": "decision"}])
    assert rc.check_expected(case, r)["premise_flagged"] is False
    r = _run(briefs=[{"decision_statement": "x", "inferred_assumptions": ["The 'always lower CAC' claim is treated as an unverified hypothesis"],
                      "evidence_gaps": [], "decision_kind": "decision"}])
    assert rc.check_expected(case, r)["premise_flagged"] is True
    r = _run(challenges=[{"id": "c", "mechanism": "the premise that video beats search is not established", "status": "open", "could_change": "action"}])
    assert rc.check_expected(case, r)["premise_flagged"] is True


def test_recommended_match_is_whole_phrase_and_empty_title_fails():
    case = CASES["obj_vendor_ev"]
    assert rc.check_expected(case, _run(decision={"kind": "firm", "recommended_title": "Select Vendor A (138k total)", "signals": {}}))["recommended_matches"] is True
    assert rc.check_expected(case, _run(decision={"kind": "firm", "recommended_title": "Select vendor abc", "signals": {}}))["recommended_matches"] is False
    assert rc.check_expected(case, _run(decision={"kind": "firm", "recommended_title": "Collect more data (SLA)", "signals": {}}))["recommended_matches"] is False
    assert rc.check_expected(case, _run(decision={"kind": "no_eligible_option", "recommended_title": None, "signals": {}}))["recommended_matches"] is False
    gate = CASES["gate_budget_fail"]
    out = rc.check_expected(gate, _run(decision={"kind": "firm", "recommended_title": "Run the 65k TV spot", "signals": {}},
                                       option_titles={"v1": "65k EUR TV spot"}, judgement_gate_fails=[{"version": "v1", "failed_gates": ["crit_gate_budget"]}]))
    assert out["recommended_avoids"] is False and out["gate_failed_on_planted_option"] is True


def test_campaign_limits_and_primary_measure():
    case = CASES["trivial_overhead"]
    ok = rc.check_expected(case, _run(budget={"model_calls_used": 6, "tokens_measured": 1}, decision={"kind": "firm", "stop_reason": "trivial_question", "signals": {}}), LIMITS)
    assert ok["within_call_cap"] and ok["within_campaign_limits"] and rc.primary_passed(case, ok) is True
    over = rc.check_expected(case, _run(budget={"model_calls_used": 41, "tokens_measured": 1}, decision={"kind": "firm", "stop_reason": "budget_calls", "signals": {}}), LIMITS)
    assert over["within_campaign_limits"] is False and rc.primary_passed(case, over) is False
    assert rc.primary_passed(CASES["open_channel_mix"], rc.check_expected(CASES["open_channel_mix"], _run(), LIMITS)) is None


def test_call_cap_never_raises_a_preset_cap():
    quick = next(s for s in SPEC["systems"] if s["id"] == "council_quick")
    first = next(s for s in SPEC["systems"] if s["id"] == "first_pass")
    assert rc.system_call_cap(quick, LIMITS) == 24          # quick preset caps at 24 < 40
    assert rc.system_call_cap(first, LIMITS) == 40          # project cap 60 is ceilinged by the campaign
    assert rc.system_call_cap(first, {"max_calls_per_run": 12}) == 12


def test_evaluator_summary_is_capped_on_whole_lines_and_keeps_the_outcome():
    dissent = "\n".join(f"- Challenge `chl_{i}` [open, material, could change ranking] on `optv_other_{i}`: " + "x" * 900 for i in range(40))
    rec_line = "- Challenge `chl_rec` [open, material, could change action] on `optv_rec`: objection on the recommended option"
    report = ("# Strategy Tribunal — decision record — run `r`\n\n## Outcome: conditional\n**Recommended action:** do X\n**Stopping reason:** budget\n\n"
              "## Strongest alternatives\n- `optv_a` alt a\n\n## Decisive evidence\n- ev\n\n## Material dissent and unresolved objections\n"
              + dissent + "\n" + rec_line + "\n\n## Trade-offs\n- t\n\n## Round-by-round decision quality\n| r |\n\n## Reopen or reverse when\n- if\n\n"
              "## What the council failed to establish\n- gap\n\n## Budget\n- b\n")
    run = {"report": report, "decision": {"recommended_version_id": "optv_rec"}}
    s = rc.summarise_for_eval(run)
    assert len(s) <= rc.EVAL_TOTAL_CAP
    assert s.startswith("## Outcome") and "## Trade-offs" in s and "## Reopen" in s and "## What the council failed" in s
    assert "## Budget" not in s and "## Round-by-round" not in s and "Stopping reason" not in s
    assert "objection on the recommended option" in s          # recommended-option objection survives the dissent cap
    assert "further item(s) omitted for length" in s
    assert "optv_" not in s and "chl_" not in s                   # identities blinded
    assert all(len(l) <= rc.EVAL_LINE_CAP + 2 for l in s.splitlines())
