"""Builds the deterministic fixtures used by the Run 1 checks.

The fixture supplies only raw role outputs (what a model would say). Everything
decision-relevant (aggregates, bounds, promotion, regression rejection,
rescoring under a new evidence snapshot, stability, stopping, decision kind) is
computed by the controller and asserted by the tests.

Run ``python tests/fixtures/build_fixtures.py`` to regenerate the JSON files.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

HERE = Path(__file__).parent

QUESTION = "Should we shift 30% of our Q1 paid-search budget into short-form video?"
LENSES = "staging,information_option,asymmetric_upside"


def ev(id_: str, statement: str, kind: str, ref: str, status: str, challenge_id: str | None = None) -> dict:
    d = {"id": id_, "statement": statement, "source": {"kind": kind, "ref": ref}, "verification_status": status}
    if challenge_id:
        d["challenge_id"] = challenge_id
    return d


def score(cid: str, s: int, conf: str, evidence: list[str] | None = None, assumptions: list[str] | None = None, why: str = "") -> dict:
    d = {"criterion_id": cid, "score": s, "confidence": conf, "rationale": why or f"{cid} = {s}"}
    if evidence:
        d["evidence_ids"] = evidence
    if assumptions:
        d["assumption_ids"] = assumptions
    return d


def gate(outcome: str, evidence: list[str] | None = None, why: str = "") -> dict:
    d = {"criterion_id": "crit_gate_budget", "outcome": outcome, "rationale": why or f"budget gate {outcome}"}
    if evidence:
        d["evidence_ids"] = evidence
    return d


def judge(version_id: str, snapshot: str, gate_result: dict, scores: list[dict], scenario: dict | None = None,
          judge_no: int | None = None, round_no: int | None = None) -> dict:
    """``judge_no`` pins the entry to one jury member (``p_judge_<n>``); ``round_no`` pins it to one round, which
    is how a rescore of the same version under the same evidence snapshot (e.g. after a reframe) is told apart."""
    content = {"gate_results": [gate_result], "criterion_scores": scores}
    if scenario:
        content["scenario_scores"] = scenario
    match: dict = {"kind": "judge", "version_id": version_id, "snapshot": snapshot}
    if judge_no is not None:
        match["judge"] = judge_no
    if round_no is not None:
        match["round"] = round_no
    return {"match": match, "content": content}


def entry(match: dict, content: dict, once: bool = True) -> dict:
    d = {"match": match, "content": content}
    if not once:
        d["once"] = False
    return d


FRAME = {
    "decision_statement": "Decide how much of the fixed Q1 paid budget to move from paid search into short-form video, and under which conditions.",
    "objectives": ["Grow incremental reach without losing measured efficiency", "Keep Q1 within the fixed budget"],
    "stakeholders": ["growth team", "finance", "creative team"],
    "hard_constraints": [{"text": "Q1 total paid media budget must not exceed 400k EUR", "source": "user_stated"}],
    "preferences": ["prefer measurable moves over bets"],
    "time_horizon": "Q1 (13 weeks), budget locked by week 2",
    "stakes": "high",
    "reversibility": "costly",
    "domain": "complicated",
    "evidence_gaps": ["incrementality of short-form video is unknown", "creative production capacity in January is unknown"],
    "interpretations": [{"text": "'shift 30%' means a one-off reallocation for the whole quarter", "implied_action": "decide a quarter-long split"}],
    "inferred_assumptions": ["The team can run paid video campaigns in-house"],
    "decision_kind": "decision",
    "user_facts": [
        ev("ev_u1", "Q1 paid media budget is fixed at 400k EUR", "user", "question", "user_supplied"),
        ev("ev_u2", "Paid search delivered ROAS 2.1 last quarter", "user", "question", "user_supplied"),
    ],
}

POLICY = {
    "criteria": [
        {"id": "crit_gate_budget", "name": "Stays within the Q1 budget ceiling", "kind": "gate", "weight": 0,
         "description": "Fails if the option can breach 400k EUR under plausible cost spikes"},
        {"id": "crit_reach", "name": "Incremental reach and efficiency", "kind": "score", "weight": 4,
         "anchor_0": "no incremental reach", "anchor_5": "some reach at worse efficiency", "anchor_10": "large incremental reach at parity ROAS"},
        {"id": "crit_measurability", "name": "Measurability of the result", "kind": "score", "weight": 3,
         "anchor_0": "unmeasurable", "anchor_5": "directional read", "anchor_10": "clean incrementality readout before budget lock"},
        {"id": "crit_execution", "name": "Execution risk (10 = lowest risk)", "kind": "score", "weight": 2,
         "anchor_0": "cannot be executed in Q1", "anchor_5": "executable with new vendors", "anchor_10": "executable with current team"},
        {"id": "crit_brand", "name": "Brand fit", "kind": "score", "weight": 1,
         "anchor_0": "conflicts with brand", "anchor_5": "neutral", "anchor_10": "strengthens brand"},
    ],
    "scenarios": [
        {"id": "scn_cpm_spike", "name": "Video CPM spike in January", "likelihood": "medium", "priority": True},
        {"id": "scn_search_saturation", "name": "Paid search saturates in Q2", "likelihood": "medium"},
    ],
}

BASELINE = {
    "options": [
        {"id": "optv_A_v1", "option_id": "opt_A", "title": "Keep the Q1 budget in paid search",
         "summary": "Status quo: hold the 400k EUR in paid search for Q1 and revisit in Q2.", "mechanism": "Preserves the measured ROAS 2.1 channel.",
         "claims": [{"id": "clm_a1", "text": "Search ROAS 2.1 is a measured baseline", "kind": "fact", "evidence_ids": ["ev_u2"]}],
         "assumptions": [], "generation_note": {"how": "status quo", "resources": "model only", "missing_inputs": []}, "is_status_quo": True},
        {"id": "optv_B_v1", "option_id": "opt_B", "title": "Shift 30% to short-form video in January",
         "summary": "Reallocate 120k EUR to short-form video from week 1 and run it for the whole quarter.", "mechanism": "Buys reach search cannot deliver.",
         "claims": [{"id": "clm_b1", "text": "Short-form video reaches audiences search cannot", "kind": "inference"}],
         "assumptions": [{"id": "asm_b1", "text": "Creative can be produced in January", "influential": True, "if_false_effect": "spend starts late and Q1 readout is lost"}],
         "generation_note": {"how": "direct answer to the question", "resources": "model only", "missing_inputs": ["video CPM forecast"]}},
    ],
    "evidence": [],
}

GEN_STAGING = {
    "options": [{
        "id": "optv_C_v1", "option_id": "opt_C", "title": "Staged 10% pilot with scale gates",
        "summary": "Move 10% (40k EUR) into short-form video for six weeks; scale to 30% only if incremental ROAS >= 1.2x the search baseline.",
        "mechanism": "Buys information cheaply before the costly commitment; the gate protects the budget ceiling.",
        "claims": [{"id": "clm_c1", "text": "A 10% pilot keeps Q1 within budget", "kind": "fact", "evidence_ids": ["ev_u1"]},
                   {"id": "clm_c2", "text": "Scaling only after a readout caps downside at 40k EUR", "kind": "prediction"}],
        "assumptions": [{"id": "asm_c1", "text": "Incrementality can be measured within six weeks", "influential": True,
                         "if_false_effect": "the pilot cannot produce a readout before the Q1 lock"}],
        "generation_note": {"how": "staging lens", "resources": "model only", "missing_inputs": []},
    }],
}

GEN_INFO = {
    "options": [{
        "id": "optv_D_v1", "option_id": "opt_D", "title": "Run a four-week incrementality study before reallocating",
        "summary": "Hold the budget, run a small geo-split video test, decide the reallocation at week 5.",
        "mechanism": "Resolves the decisive uncertainty before committing money.",
        "claims": [{"id": "clm_d1", "text": "A geo-split test answers the incrementality question", "kind": "inference"}],
        "assumptions": [{"id": "asm_d1", "text": "A four-week study delays any reallocation by a month", "influential": False}],
        "generation_note": {"how": "information option lens", "resources": "model only", "missing_inputs": []},
    }],
}

GEN_UPSIDE = {
    "options": [{
        "id": "optv_E_v1", "option_id": "opt_E", "title": "Shift 30% with creator partnerships",
        "summary": "Reallocate 120k EUR to creator-led short-form video to capture outsized organic reach.",
        "mechanism": "Creator content can earn organic distribution beyond paid impressions.",
        "claims": [{"id": "clm_e1", "text": "Creator content earns organic reach beyond paid impressions", "kind": "prediction"}],
        "assumptions": [{"id": "asm_e1", "text": "Creator deals can be signed within three weeks", "influential": True,
                         "if_false_effect": "spend slips into February"}],
        "generation_note": {"how": "asymmetric upside lens", "resources": "model only", "missing_inputs": ["creator rate card"]},
    }],
}

REVIEW_R1_1 = {
    "challenges": [
        {"id": "chl_b_gate", "target_ref": "optv_B_v1", "mechanism": "A full 30% shift can breach the 400k ceiling if video CPMs spike and search is topped up to protect revenue",
         "severity": "critical", "challenge_class": "evidentiary", "could_change": "eligibility",
         "resolution_condition": "Show the 30% shift stays within 400k EUR under a video CPM spike", "requires_verification": False},
        {"id": "chl_shared_capacity", "target_ref": "__all__", "scope": "shared_blind_spot",
         "mechanism": "Every option that spends on video assumes January creative-production capacity that nobody has confirmed",
         "severity": "material", "challenge_class": "execution", "could_change": "action",
         "resolution_condition": "Confirm January creative-production capacity", "requires_verification": True},
    ],
    "agreement_assessment": "Agreement is partial and comes from different mechanisms, not shared framing.",
}

REVIEW_R1_2 = {
    "challenges": [
        {"id": "chl_e_speed", "target_ref": "optv_E_v1", "mechanism": "Creator deals rarely close in three weeks; spend would slip past the budget lock",
         "severity": "material", "challenge_class": "execution", "could_change": "ranking",
         "resolution_condition": "Signed creator agreements before January 15", "requires_verification": False},
    ],
    "dissent": [{"position": "The status quo forfeits learning", "against_ref": "optv_A_v1",
                 "reason": "Holding everything in search leaves no video capability if search saturates",
                 "what_you_lose": "If search saturates in Q2 there is no tested video channel to move to"}],
}

VERIFY_CAPACITY_UNAVAILABLE = {"evidence": [
    ev("ev_cap_unknown", "No creative-production capacity plan for January is available in the provided material", "document", "none found", "unavailable", "chl_shared_capacity")]}

RESPOND_B_WITHDRAW = {"responses": [
    {"challenge_id": "chl_b_gate", "kind": "withdraw", "text": "Withdrawing the full 30% shift: budget compliance under a CPM spike cannot be shown."}]}

RESPOND_E_REVISE = {"responses": [{
    "challenge_id": "chl_e_speed", "kind": "revise", "text": "Revising to a smaller shift with a pre-signed creator roster.",
    "revision": {"id": "optv_E_v2", "title": "Shift 20% with a pre-signed creator roster",
                 "summary": "Reallocate 80k EUR to creator-led video using creators already under framework agreements.",
                 "mechanism": "Removes the signing delay while keeping organic upside.",
                 "claims": [{"id": "clm_e2", "text": "Framework agreements remove the signing delay", "kind": "inference"}],
                 "assumptions": [{"id": "asm_e2", "text": "At least three framework creators are available in January", "influential": True, "if_false_effect": "spend slips"}],
                 "generation_note": {"how": "revision after chl_e_speed", "resources": "model only", "missing_inputs": []},
                 "change_reason": "Addresses chl_e_speed by using pre-signed creators and a smaller shift"}}]}

REVIEW_R2_1 = {
    "challenges": [
        {"id": "chl_c_measure", "target_ref": "optv_C_v1", "mechanism": "Incrementality of a 10% pilot is not measurable without a holdout design; the scale gate would fire on noise",
         "severity": "material", "challenge_class": "evidentiary", "could_change": "ranking",
         "resolution_condition": "Benchmark showing geo-holdout pilots at 10% budget share produce a readable incrementality signal within six weeks",
         "requires_verification": True},
    ],
}
REVIEW_EMPTY = {"challenges": [], "agreement_assessment": "Agreement is genuine: the options differ in mechanism and the leader survives on measurability."}

VERIFY_BENCH = {"evidence": [
    ev("ev_bench", "Industry benchmark: geo-holdout pilots at >= 10% budget share produce a readable incrementality signal in four to six weeks", "url", "benchmark-report-2025", "verified", "chl_c_measure")]}

RESPOND_C_REVISE = {"responses": [{
    "challenge_id": "chl_c_measure", "kind": "revise", "text": "Adding a geo-holdout and weekly readouts so the scale gate fires on a clean signal.",
    "revision": {"id": "optv_C_v2", "title": "Staged 10% pilot with geo-holdout and weekly readouts",
                 "summary": "Move 10% into short-form video in two test regions with matched holdout regions for six weeks; weekly readouts; scale to 30% only if incremental ROAS >= 1.2x.",
                 "mechanism": "The holdout isolates incrementality from attribution noise.",
                 "claims": [{"id": "clm_c3", "text": "Geo-holdout pilots at 10% share give a readable signal within six weeks", "kind": "fact", "evidence_ids": ["ev_bench"]}],
                 "assumptions": [{"id": "asm_c2", "text": "Two matched region pairs exist", "influential": False}],
                 "generation_note": {"how": "revision after chl_c_measure", "resources": "model only", "missing_inputs": []},
                 "change_reason": "Addresses chl_c_measure with a holdout design"}}]}

RESPOND_C_REBUT = {"responses": [{
    "challenge_id": "chl_c_measure", "kind": "rebut", "text": "The verified benchmark shows a 10% geo-holdout pilot is readable within six weeks, which is inside the Q1 window.",
    "evidence_ids": ["ev_bench"]}]}

CHALLENGE = {
    "losing_scenario": "January creative-production capacity is fully booked, so the pilot cannot launch before week 6 and no readout exists before the Q1 budget lock.",
    "strongest_alternative_version_id": "optv_A_v1",
    "distinguishing_evidence": "Confirmed creative-production capacity for January (production calendar)",
    "could_alter_outcome": True,
    "related_challenge_ids": ["chl_shared_capacity"],
}

REPLY_UNRESOLVED = {"kind": "rebut", "text": "Capacity is likely available but no plan could be found.", "evidence_ids": ["ev_cap_unknown"]}
REPLY_RESOLVED = {"kind": "rebut", "text": "The January production calendar confirms capacity for two video creatives.",
                  "evidence": [ev("ev_cap_ok", "January production calendar confirms capacity for two short-form video creatives", "document",
                                  "production_calendar_jan.pdf", "verified")],
                  "evidence_ids": ["ev_cap_ok"]}

# Judgements -----------------------------------------------------------------
# Snapshot ids: ev_u1 -> snap-1, ev_u2 -> snap-2 (framing). ev_bench (round 2) -> snap-3.
S2, S3, S4 = "snap-2", "snap-3", "snap-4"

J_A = lambda snap: judge("optv_A_v1", snap, gate("pass", ["ev_u1"], "No reallocation; ceiling untouched"), [
    score("crit_reach", 3, "medium", ["ev_u2"], why="No incremental reach beyond search"),
    score("crit_measurability", 8, "high", ["ev_u2"], why="Search ROAS is measured"),
    score("crit_execution", 9, "high", ["ev_u1"], why="Nothing changes"),
    score("crit_brand", 6, "medium", ["ev_u2"], why="Neutral"),
], {"scn_cpm_spike": 7, "scn_search_saturation": 3})

J_B = judge("optv_B_v1", S2, gate("unverified", [], "A 30% shift could breach the ceiling under a CPM spike; no forecast supplied"), [
    score("crit_reach", 7, "medium", assumptions=["asm_b1"], why="Large reach if creative lands in January"),
    score("crit_measurability", 4, "medium", assumptions=["asm_b1"], why="No holdout; attribution only"),
    score("crit_execution", 5, "low", assumptions=["asm_b1"], why="Creative capacity unconfirmed"),
    score("crit_brand", 6, "medium", assumptions=["asm_b1"]),
])

J_C1_S2 = judge("optv_C_v1", S2, gate("pass", ["ev_u1"], "10% pilot stays inside 400k"), [
    score("crit_reach", 7, "high", assumptions=["asm_c1"], why="Pilot plus scale path"),
    score("crit_measurability", 8, "high", assumptions=["asm_c1"], why="Gate defined on incremental ROAS"),
    score("crit_execution", 8, "high", ["ev_u1"], why="Small spend, current team"),
    score("crit_brand", 6, "medium", assumptions=["asm_c1"]),
], {"scn_cpm_spike": 7, "scn_search_saturation": 8})

J_C1_S3 = lambda snap: judge("optv_C_v1", snap, gate("pass", ["ev_u1"], "10% pilot stays inside 400k"), [
    score("crit_reach", 7, "high", ["ev_bench"], why="Pilot plus scale path"),
    score("crit_measurability", 9, "high", ["ev_bench"], why="Benchmark confirms readability within six weeks"),
    score("crit_execution", 8, "high", ["ev_u1"], why="Small spend, current team"),
    score("crit_brand", 6, "medium", assumptions=["asm_c1"]),
], {"scn_cpm_spike": 7, "scn_search_saturation": 8})

J_C2_S3 = lambda snap: judge("optv_C_v2", snap, gate("pass", ["ev_u1"], "10% pilot stays inside 400k"), [
    score("crit_reach", 7, "high", ["ev_bench"]),
    score("crit_measurability", 9, "high", ["ev_bench"], why="Holdout design"),
    score("crit_execution", 5, "medium", ["ev_u1"], why="Holdout regions and weekly readouts add coordination load the team has not run before"),
    score("crit_brand", 6, "medium", assumptions=["asm_c2"]),
], {"scn_cpm_spike": 7, "scn_search_saturation": 8})

J_D = lambda snap: judge("optv_D_v1", snap, gate("pass", ["ev_u1"], "No reallocation in the study period"), [
    score("crit_reach", 4, "high", assumptions=["asm_d1"], why="Reach only after week 5"),
    score("crit_measurability", 9, "high", assumptions=["asm_d1"], why="Designed to measure"),
    score("crit_execution", 9, "high", ["ev_u1"]),
    score("crit_brand", 6, "medium", assumptions=["asm_d1"]),
], {"scn_cpm_spike": 8, "scn_search_saturation": 5})

J_E2 = lambda snap: judge("optv_E_v2", snap, gate("unverified", [], "20% shift; ceiling compliance under CPM spike not shown"), [
    score("crit_reach", 7, "medium", assumptions=["asm_e2"]),
    score("crit_measurability", 5, "medium", assumptions=["asm_e2"], why="Organic reach is hard to attribute"),
    score("crit_execution", 5, "low", assumptions=["asm_e2"]),
    score("crit_brand", 7, "medium", assumptions=["asm_e2"]),
], {"scn_cpm_spike": 4, "scn_search_saturation": 7})


def main_run(resolved: bool = False) -> dict:
    responses = [
        entry({"kind": "frame"}, FRAME),
        entry({"kind": "policy"}, POLICY),
        entry({"kind": "baseline"}, BASELINE),
        J_A(S2), J_B,
        entry({"kind": "generate", "lens": "staging"}, GEN_STAGING),
        entry({"kind": "generate", "lens": "information_option"}, GEN_INFO),
        entry({"kind": "generate", "lens": "asymmetric_upside"}, GEN_UPSIDE),
        entry({"kind": "review", "round": 1, "reviewer": 1}, REVIEW_R1_1),
        entry({"kind": "review", "round": 1, "reviewer": 2}, REVIEW_R1_2),
        entry({"kind": "verify", "challenge_id": "chl_shared_capacity"}, VERIFY_CAPACITY_UNAVAILABLE),
        entry({"kind": "respond", "round": 1, "version_id": "optv_B_v1"}, RESPOND_B_WITHDRAW),
        entry({"kind": "respond", "round": 1, "version_id": "optv_E_v1"}, RESPOND_E_REVISE),
        J_C1_S2, J_D(S2), J_E2(S2),
        entry({"kind": "review", "round": 2, "reviewer": 1}, REVIEW_R2_1),
        entry({"kind": "review", "round": 2, "reviewer": 2}, REVIEW_EMPTY),
        entry({"kind": "verify", "challenge_id": "chl_c_measure"}, VERIFY_BENCH),
        entry({"kind": "respond", "round": 2, "version_id": "optv_C_v1"}, RESPOND_C_REVISE),
        J_A(S3), J_C1_S3(S3), J_C2_S3(S3), J_D(S3), J_E2(S3),
        entry({"kind": "review", "round": 3, "reviewer": 1}, REVIEW_EMPTY),
        entry({"kind": "review", "round": 3, "reviewer": 2}, REVIEW_EMPTY),
        entry({"kind": "respond", "round": 3, "version_id": "optv_C_v1"}, RESPOND_C_REBUT),
        entry({"kind": "review", "round": 4, "reviewer": 1}, REVIEW_EMPTY),
        entry({"kind": "review", "round": 4, "reviewer": 2}, REVIEW_EMPTY),
        entry({"kind": "challenge"}, CHALLENGE),
        entry({"kind": "challenge_reply"}, REPLY_RESOLVED if resolved else REPLY_UNRESOLVED),
    ]
    if resolved:
        # the reply adds verified evidence -> snapshot 4 -> the controller rescores every candidate before reporting
        responses += [J_A(S4), J_C1_S3(S4), J_C2_S3(S4), J_D(S4), J_E2(S4)]
    return {"meta": {"question": QUESTION, "lenses": LENSES, "variant": "resolved" if resolved else "unresolved"}, "responses": responses}


def schema_rejection() -> dict:
    """First frame attempt is malformed (missing fields, extra field); second is valid. First policy attempt
    is unparseable text; second valid. Then the run proceeds as a trivial decision to keep it short."""
    bad_frame = {"decision_statement": "too short?", "objectives": [], "stakes": "enormous", "unexpected": 1}
    trivial_frame = dict(FRAME, decision_kind="trivial", stakes="low", reversibility="reversible")
    return {"meta": {"question": QUESTION}, "responses": [
        {"match": {"kind": "frame", "attempt": 1}, "content": bad_frame},
        {"match": {"kind": "frame", "attempt": 2}, "content": trivial_frame},
        {"match": {"kind": "policy", "attempt": 1}, "raw": "Sure! Here is the policy: criteria = reach, cost"},
        {"match": {"kind": "policy", "attempt": 2}, "content": POLICY},
        entry({"kind": "baseline"}, BASELINE),
        J_A(S2), J_B,
    ]}


def retries_exhausted() -> dict:
    return {"meta": {"question": QUESTION}, "responses": [
        {"match": {"kind": "frame"}, "raw": "I cannot answer in JSON.", "once": False},
    ]}


def validation_fallback() -> dict:
    """Frame fails validation twice on the primary route, then the fallback model (attempt 3) answers validly; the rest
    is the first-pass flow."""
    fp = first_pass()
    rest = [r for r in fp["responses"] if r["match"].get("kind") != "frame"]
    return {"meta": {"question": QUESTION, "lenses": LENSES}, "responses": [
        {"match": {"kind": "frame", "attempt": 1}, "raw": "not json at all"},
        {"match": {"kind": "frame", "attempt": 2}, "raw": "{\"still\": \"wrong\"}"},
        {"match": {"kind": "frame", "attempt": 3}, "content": FRAME},
        *rest,
    ]}


def first_pass() -> dict:
    return {"meta": {"question": QUESTION, "lenses": LENSES}, "responses": [
        entry({"kind": "frame"}, FRAME), entry({"kind": "policy"}, POLICY), entry({"kind": "baseline"}, BASELINE),
        J_A(S2), J_B,
        entry({"kind": "generate", "lens": "staging"}, GEN_STAGING),
        entry({"kind": "generate", "lens": "information_option"}, GEN_INFO),
        entry({"kind": "generate", "lens": "asymmetric_upside"}, GEN_UPSIDE),
        J_C1_S2, J_D(S2),
        judge("optv_E_v1", S2, gate("unverified", [], "30% shift; compliance not shown"), [
            score("crit_reach", 7, "medium", assumptions=["asm_e1"]), score("crit_measurability", 4, "medium", assumptions=["asm_e1"]),
            score("crit_execution", 4, "low", assumptions=["asm_e1"]), score("crit_brand", 7, "medium", assumptions=["asm_e1"])]),
    ]}


# Run 2 fixtures: reframe + reinstate, pairwise tiebreak + jury ----------------
# Both run with a single explicit lens (staging) so the candidate set is A (status quo), B and C.

A_SCORES = [
    score("crit_reach", 3, "medium", ["ev_u2"], why="No incremental reach beyond search"),
    score("crit_measurability", 8, "high", ["ev_u2"], why="Search ROAS is measured"),
    score("crit_execution", 9, "high", ["ev_u1"], why="Nothing changes"),
    score("crit_brand", 6, "medium", ["ev_u2"], why="Neutral"),
]  # aggregate 6.0, bounds [5.25, 6.75]
A_GATE = lambda: gate("pass", ["ev_u1"], "No reallocation; ceiling untouched")
B_SCORES = [
    score("crit_reach", 7, "medium", assumptions=["asm_b1"], why="Large reach if creative lands in January"),
    score("crit_measurability", 4, "medium", assumptions=["asm_b1"], why="No holdout; attribution only"),
    score("crit_execution", 5, "low", assumptions=["asm_b1"], why="Creative capacity unconfirmed"),
    score("crit_brand", 6, "medium", assumptions=["asm_b1"]),
]  # 5.6 - 1.0 unverified-gate penalty = 4.6
B_GATE = lambda: gate("unverified", [], "A 30% shift could breach the ceiling under a CPM spike; no forecast supplied")


def j_a(version_id: str, round_no: int, judge_no: int | None = None) -> dict:
    return judge(version_id, S2, A_GATE(), copy.deepcopy(A_SCORES), {"scn_cpm_spike": 7, "scn_search_saturation": 3},
                 judge_no=judge_no, round_no=round_no)


def j_b(round_no: int, judge_no: int | None = None) -> dict:
    return judge("optv_B_v1", S2, B_GATE(), copy.deepcopy(B_SCORES), judge_no=judge_no, round_no=round_no)


REFRAME_1 = {"reason": "The question asks whether to shift, but every candidate differs only in how and when the shift is staged",
             "decision_statement": "Decide how to stage a move of the Q1 paid budget from search into short-form video under the fixed 400k EUR ceiling."}
REFRAME_2 = {"reason": "Second reframe attempt: the real question is which channel mix maximises learning",
             "decision_statement": "Decide which Q1 channel mix produces the most decision-relevant learning within the 400k EUR ceiling."}

REVIEW_RR_1 = {
    "challenges": [
        {"id": "chl_a_stale", "target_ref": "optv_A_v1",
         "mechanism": "The status quo assumes search ROAS 2.1 holds through Q1, but saturation is already visible in the last quarter's marginal returns",
         "severity": "critical", "challenge_class": "evidentiary", "could_change": "eligibility",
         "resolution_condition": "Show marginal search ROAS held above 2.0 in the last four weeks", "requires_verification": False},
    ],
    "agreement_assessment": "Agreement is partial.",
    "reframe": REFRAME_1,
}
RESPOND_A_WITHDRAW = {"responses": [
    {"challenge_id": "chl_a_stale", "kind": "withdraw",
     "text": "Withdrawing the pure status quo: search saturation cannot be ruled out with the material provided."}]}

REVIEW_RR_2 = {
    "challenges": [
        {"id": "chl_a_withdrawn", "target_ref": "optv_A_v1",
         "mechanism": "Withdrawing the status quo leaves no eligible fallback inside the ceiling if video CPMs spike; the saturation objection was asserted, never evidenced",
         "severity": "material", "challenge_class": "evidentiary", "could_change": "ranking",
         "resolution_condition": "Either evidence of search saturation or a reinstated fallback", "requires_verification": False},
    ],
    "reframe": REFRAME_2,
}
RESPOND_A_REINSTATE = {"responses": [
    {"challenge_id": "chl_a_withdrawn", "kind": "reinstate",
     "text": "Reinstating the status quo: the saturation objection was never evidenced and the council needs a fallback that stays inside the ceiling."}]}

# C under the staging lens, scored clearly below A so the withdrawn incumbent stays the incumbent (aggregate 5.4).
J_C_LOW = lambda round_no: judge("optv_C_v1", S2, gate("pass", ["ev_u1"], "10% pilot stays inside 400k"), [
    score("crit_reach", 4, "medium", assumptions=["asm_c1"], why="Small pilot, reach only if scaled"),
    score("crit_measurability", 6, "medium", assumptions=["asm_c1"], why="Gate defined but no holdout"),
    score("crit_execution", 7, "high", ["ev_u1"], why="Small spend, current team"),
    score("crit_brand", 6, "medium", assumptions=["asm_c1"]),
], {"scn_cpm_spike": 7, "scn_search_saturation": 6}, round_no=round_no)

# Controller-assigned ids for versions the strategist does not name: the withdrawn copy of A and its reinstatement.
A_WITHDRAWN_ID, A_REINSTATED_ID = "optv_0001", "optv_0002"


def reframe_reinstate() -> dict:
    """Round 1: a reviewer challenges the incumbent (status quo) and proposes a reframe; the owner withdraws. The
    controller creates brief v2 and rescores every candidate under the new key. Round 2: a reviewer objects to the
    withdrawal and proposes a second reframe (capped by max_reframes); the owner reinstates the option with a reason.
    Config: limits.min_rounds=2, max_rounds=2, max_leader_challenges=0; review.panel_size=1; lens staging only."""
    return {"meta": {"question": QUESTION, "lenses": "staging"}, "responses": [
        entry({"kind": "frame"}, FRAME), entry({"kind": "policy"}, POLICY), entry({"kind": "baseline"}, BASELINE),
        j_a("optv_A_v1", 0), j_b(0),
        entry({"kind": "generate", "lens": "staging"}, GEN_STAGING),
        entry({"kind": "review", "round": 1, "reviewer": 1}, REVIEW_RR_1),
        entry({"kind": "respond", "round": 1, "version_id": "optv_A_v1"}, RESPOND_A_WITHDRAW),
        # brief v2 after the reframe: every candidate (incumbent A_v1, B, C) is scored again under the new key
        j_a("optv_A_v1", 1), j_b(1), J_C_LOW(1),
        entry({"kind": "review", "round": 2, "reviewer": 1}, REVIEW_RR_2),
        entry({"kind": "respond", "round": 2, "version_id": "optv_A_v1"}, RESPOND_A_REINSTATE),
        j_a(A_REINSTATED_ID, 2),
    ]}


# Jury of two on C: judge 1 and judge 2 disagree on reach (8 vs 6, both confident). The spread/2 = 1.0 exceeds the
# high-confidence half-width 0.5, so the combined bounds widen to [6.0, 7.8] (a single judge would give a width of 1.4).
# Mean aggregate 6.9 against the incumbent A at 6.0 with bounds [5.25, 6.75]: a material delta with overlapping
# bounds -> pairwise tiebreak.
def j_c_jury(judge_no: int) -> dict:
    reach = 8 if judge_no == 1 else 6
    return judge("optv_C_v1", S2, gate("pass", ["ev_u1"], "10% pilot stays inside 400k"), [
        score("crit_reach", reach, "high", assumptions=["asm_c1"], why=f"Judge {judge_no}: pilot plus scale path"),
        score("crit_measurability", 7, "medium", assumptions=["asm_c1"], why="Gate defined on incremental ROAS"),
        score("crit_execution", 7, "high", ["ev_u1"], why="Small spend, current team"),
        score("crit_brand", 6, "medium", assumptions=["asm_c1"]),
    ], {"scn_cpm_spike": 7, "scn_search_saturation": 8}, judge_no=judge_no, round_no=1)


COMPARE_A = {"preferred": "second", "rationale": "The pilot buys information the status quo cannot; the scale gate protects the ceiling."}
COMPARE_B = {"preferred": "first", "rationale": "Same verdict with the order swapped: the staged pilot is preferred."}


def tiebreak_jury() -> dict:
    """judge.jury_size=2 with the first_pass preset (no review panel, one round): two judges score every version;
    their disagreement on C widens its bounds so that C vs the incumbent A is a close call, which triggers two
    counterbalanced `compare` requests; both prefer C -> promoted."""
    return {"meta": {"question": QUESTION, "lenses": "staging", "preset": "first_pass", "judge": {"jury_size": 2}}, "responses": [
        entry({"kind": "frame"}, FRAME), entry({"kind": "policy"}, POLICY), entry({"kind": "baseline"}, BASELINE),
        j_a("optv_A_v1", 0, judge_no=1), j_a("optv_A_v1", 0, judge_no=2), j_b(0, judge_no=1), j_b(0, judge_no=2),
        entry({"kind": "generate", "lens": "staging"}, GEN_STAGING),
        j_c_jury(1), j_c_jury(2),
        entry({"kind": "compare", "slot": "a", "first": "optv_A_v1", "second": "optv_C_v1"}, COMPARE_A),
        entry({"kind": "compare", "slot": "b", "first": "optv_C_v1", "second": "optv_A_v1"}, COMPARE_B),
    ]}


def write_all() -> None:
    (HERE / "main_run.json").write_text(json.dumps(main_run(False), indent=1))
    (HERE / "main_run_resolved.json").write_text(json.dumps(main_run(True), indent=1))
    (HERE / "schema_rejection.json").write_text(json.dumps(schema_rejection(), indent=1))
    (HERE / "retries_exhausted.json").write_text(json.dumps(retries_exhausted(), indent=1))
    (HERE / "first_pass.json").write_text(json.dumps(first_pass(), indent=1))
    (HERE / "validation_fallback.json").write_text(json.dumps(validation_fallback(), indent=1))
    (HERE / "reframe_reinstate.json").write_text(json.dumps(reframe_reinstate(), indent=1))
    (HERE / "tiebreak_jury.json").write_text(json.dumps(tiebreak_jury(), indent=1))


if __name__ == "__main__":
    write_all()
    print("fixtures written to", HERE)
