"""Phase request payloads, response models (what a responder may propose) and
appliers that turn validated responses into committed records.

Responders never commit anything: an applier validates every reference, assigns
ids, and commits inside a store transaction. Any failure rolls the whole
response back.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import Field, field_validator

from .lenses import LENSES
from .ontology import (
    Assumption,
    Challenge,
    ChallengeClass,
    ChallengeScope,
    ChallengeStatus,
    Claim,
    ClaimKind,
    Constraint,
    CouldChange,
    Criterion,
    CriterionKind,
    CriterionScore,
    DecisionBrief,
    DecisionKind,
    Dissent,
    Domain,
    EvaluationPolicy,
    EventKind,
    Evidence,
    EvidenceSource,
    GateResult,
    GenerationNote,
    Interpretation,
    LeaderChallenge,
    Likelihood,
    OptionStatus,
    OptionVersion,
    Response,
    ResponseKind,
    Reversibility,
    Role,
    Scenario,
    Severity,
    Stakes,
    StrictModel,
    VerificationStatus,
    QUALIFYING_EVIDENCE,
)
from .state import PendingRequest, RejectedUpdate, Store

_ID_RE = re.compile(r"^[a-z]+_[A-Za-z0-9_\-]{1,64}$")


# ---------------------------------------------------------------------------
# Response models (drafts)
# ---------------------------------------------------------------------------


BUILDS_ON = Field(default=[], description="D-numbers of the discussion contributions this reply relies on, e.g. [\"D3\", \"D5\"]. "
                                           "Put D-references here only, never inside statement or text fields.")


class EvidenceDraft(StrictModel):
    id: Optional[str] = Field(default=None, description="New evidence id you choose, prefix ev_ (e.g. ev_cpm_jan); omit to let the controller assign one.")
    statement: str = Field(description="The fact as one checkable sentence.")
    source: EvidenceSource = Field(description="Where it comes from: kind user | document | url | model_knowledge | computation, and ref (path, URL, title or formula).")
    verification_status: VerificationStatus = Field(description="user_supplied (stated by the user), verified (checked against a source), inferred (your reasoning), disputed, unavailable (no source reachable).")
    challenge_id: Optional[str] = Field(default=None, description="Challenge this evidence answers, when it was produced for one.")


_CLAIM_KIND_SYNONYMS = {
    "fact": "fact", "data": "fact", "observation": "fact", "measured": "fact",
    "prediction": "prediction", "forecast": "prediction", "estimate": "prediction", "projection": "prediction", "expectation": "prediction",
    "inference": "inference", "computation": "inference", "calculation": "inference", "analysis": "inference", "assumption": "inference",
    "hypothesis": "inference", "argument": "inference", "reasoning": "inference",
}


class ClaimDraft(StrictModel):
    id: Optional[str] = Field(default=None, description="Claim id, prefix clm_; omit to let the controller assign one.")
    text: str = Field(description="What the option asserts will be true, one sentence.")
    kind: ClaimKind = Field(default=ClaimKind.INFERENCE, description="fact (observed), inference (reasoned from evidence) or prediction (about the future).")
    evidence_ids: list[str] = Field(default=[], description="Evidence ids (ev_*) that support the claim; from the payload or created in this reply.")

    @field_validator("kind", mode="before")
    @classmethod
    def _coerce_kind(cls, v):
        """Models write claim kinds such as 'computation' or 'estimate'; map them onto the three protocol kinds
        (unknown words become 'inference', the most cautious label)."""
        if isinstance(v, str):
            return _CLAIM_KIND_SYNONYMS.get(v.strip().lower(), "inference")
        return v


class AssumptionDraft(StrictModel):
    id: Optional[str] = Field(default=None, description="Assumption id, prefix asm_; omit to let the controller assign one.")
    text: str = Field(description="What is taken as true without evidence.")
    influential: bool = Field(default=False, description="True when the option's case collapses if the assumption is false.")
    if_false_effect: str = Field(default="", description="What changes if the assumption turns out false.")


class OptionDraft(StrictModel):
    id: Optional[str] = Field(default=None, description="Option version id (optv_*) when revising an existing version; omit for a new option.")
    option_id: Optional[str] = Field(default=None, description="Stable id of the option across versions, prefix opt_ (e.g. opt_pilot).")
    title: str = Field(min_length=3, description="Short distinctive name; the dashboard and the ranking use it.")
    summary: str = Field(min_length=10, description="What the option does, in 1-3 sentences.")
    mechanism: str = Field(default="", description="Why it would work: the causal path from action to objective.")
    claims: list[ClaimDraft] = Field(default=[], description="What the option asserts, each tied to evidence where possible.")
    assumptions: list[AssumptionDraft] = Field(default=[], description="What it takes for granted; mark the influential ones.")
    generation_note: GenerationNote = Field(description="How the option was produced: method (how), resources used, inputs that were missing.")
    is_status_quo: bool = Field(default=False, description="True for the do-nothing / keep-the-plan option.")
    change_reason: str = Field(default="", description="For a revision: what changed and why.")


class FrameResponse(StrictModel):
    decision_statement: str = Field(min_length=10, description="The concrete decision to make, one sentence starting with 'Decide …'.")
    objectives: list[str] = Field(min_length=1, description="What a good outcome achieves, in priority order.")
    stakeholders: list[str] = Field(default=[], description="Who is affected or decides.")
    hard_constraints: list[Constraint] = Field(default=[], description="Musts; source user_stated (verbatim from the question) or inferred.")
    preferences: list[str] = Field(default=[], description="Soft wishes that trade off against each other.")
    time_horizon: str = Field(description="When the outcome is judged (e.g. 'Q1 2027', 'six weeks').")
    stakes: Stakes = Field(description="low | medium | high | critical: how much is at risk.")
    reversibility: Reversibility = Field(description="reversible | costly | one_way: how hard it is to undo.")
    domain: Domain = Field(default=Domain.COMPLICATED, description="clear | complicated | complex | chaotic (Cynefin).")
    evidence_gaps: list[str] = Field(default=[], description="Facts the council would need and does not have.")
    interpretations: list[Interpretation] = Field(default=[], description="Readings of the question that lead to different actions.")
    inferred_assumptions: list[str] = Field(default=[], description="What you assumed to frame it, labelled 'asm_<slug>: …'.")
    decision_kind: DecisionKind = Field(default=DecisionKind.DECISION, description="decision | trivial (one obvious answer) | conditional_candidate.")
    user_facts: list[EvidenceDraft] = Field(default=[], description="Facts stated in the question, as user_supplied evidence.")
    user_named_options: list[str] = Field(default=[], description="Options the user named explicitly, verbatim.")
    builds_on: list[str] = BUILDS_ON


class CriterionDraft(StrictModel):
    id: Optional[str] = Field(default=None, description="Criterion id, prefix crit_ (e.g. crit_reach); judges cite it.")
    name: str = Field(description="Short name.")
    kind: CriterionKind = Field(description="gate (must pass, no weight) or score (0-10, weighted).")
    description: str = Field(default="", description="What exactly is assessed.")
    weight: float = Field(default=0.0, ge=0.0, description="Relative weight for score criteria; the controller normalises. 0 for gates.")
    anchor_0: str = Field(default="", description="What a 0 looks like.")
    anchor_5: str = Field(default="", description="What a 5 looks like.")
    anchor_10: str = Field(default="", description="What a 10 looks like.")


class ScenarioDraft(StrictModel):
    id: Optional[str] = Field(default=None, description="Scenario id, prefix scn_.")
    name: str = Field(description="Short name of the future state.")
    description: str = Field(default="", description="What happens in it.")
    likelihood: Likelihood = Field(default=Likelihood.MEDIUM, description="low | medium | high.")
    priority: bool = Field(default=False, description="True for the scenarios the decision must hold up in.")


class PolicyResponse(StrictModel):
    criteria: list[CriterionDraft] = Field(min_length=1, description="Gates and score criteria; the whole run is judged with these.")
    scenarios: list[ScenarioDraft] = Field(default=[], description="Futures under which options are compared.")
    builds_on: list[str] = BUILDS_ON


class BaselineResponse(StrictModel):
    options: list[OptionDraft] = Field(min_length=1, max_length=8, description="Status quo, the direct answer, and one per user-named option.")
    evidence: list[EvidenceDraft] = Field(default=[], description="New evidence the options cite.")
    builds_on: list[str] = BUILDS_ON


class GenerateResponse(StrictModel):
    options: list[OptionDraft] = Field(max_length=2, description="At most two materially distinct new options from your lens.")
    evidence: list[EvidenceDraft] = Field(default=[], description="New evidence the options cite.")
    nothing_material: bool = Field(default=False, description="True when the lens adds no option distinct from the existing ones (then options is empty).")
    note: str = Field(default="", description="What the lens found, in 1-3 sentences.")
    builds_on: list[str] = BUILDS_ON


class ChallengeDraft(StrictModel):
    id: Optional[str] = Field(default=None, description="Challenge id, prefix chl_; omit to let the controller assign one.")
    target_ref: str = Field(description="An id from the payload's valid_target_ids: an option version (optv_* or OPT-n), a claim (clm_*) or an assumption (asm_*, which targets the option holding it); '__all__' only with scope shared_blind_spot.")
    mechanism: str = Field(min_length=5, description="How the target fails: the causal path, not a label.")
    severity: Severity = Field(description="minor (cosmetic) | material (changes a score) | critical (makes the option ineligible or the action wrong).")
    challenge_class: ChallengeClass = Field(description="factual (a stated fact is wrong) | evidentiary (the evidence does not support the claim) | value (wrong objective or trade-off) | scenario (fails in a plausible future) | execution (cannot be delivered as described).")
    could_change: CouldChange = Field(description="What the challenge could alter if upheld: eligibility (gate), ranking (scores), action (what to do), or none.")
    evidence_ids: list[str] = Field(default=[], description="Evidence ids that support the challenge; unknown ids are ignored.")
    resolution_condition: str = Field(default="", description="What would settle it: the check, data or decision that resolves the challenge.")
    requires_verification: bool = Field(default=False, description="True when a verifier should check a source before the owner answers.")
    scope: ChallengeScope = Field(default=ChallengeScope.TARGETED, description="targeted (one option or claim) or shared_blind_spot (what every option misses; target '__all__').")


class DissentDraft(StrictModel):
    position: str = Field(description="What you would decide instead.")
    against_ref: str = Field(description="Option version id you dissent against, or '__decision__' for the emerging direction.")
    reason: str = Field(description="Why.")
    what_you_lose: str = Field(default="", description="What the council forfeits by not following the dissent.")


class ReframeDraft(StrictModel):
    reason: str = Field(description="Why the brief frames the wrong decision.")
    decision_statement: str = Field(min_length=10, description="The decision statement the council should use instead.")


class ReviewResponse(StrictModel):
    challenges: list[ChallengeDraft] = Field(default=[], max_length=12, description="Objections ordered by impact; at most 6 is the useful size.")
    evidence: list[EvidenceDraft] = Field(default=[], description="New evidence the challenges cite (set challenge_id to the challenge it supports).")
    dissent: list[DissentDraft] = Field(default=[], description="Recorded disagreement with the emerging direction.")
    agreement_assessment: str = Field(default="", description="Whether the apparent agreement between options is genuine or shared framing, and why.")
    reframe: Optional[ReframeDraft] = Field(default=None, description="Only when the brief frames the wrong decision.")
    builds_on: list[str] = BUILDS_ON


class VerifyResponse(StrictModel):
    evidence: list[EvidenceDraft] = Field(min_length=1, description="One record per source consulted, with verified | disputed | unavailable.")
    builds_on: list[str] = BUILDS_ON


class ResponseDraft(StrictModel):
    challenge_id: str = Field(description="The open challenge (chl_*) this answers.")
    kind: ResponseKind = Field(description="rebut (with qualifying evidence) | concede | revise (supply revision) | request_verification | withdraw | reinstate.")
    text: str = Field(min_length=3, description="The answer, 2-4 sentences.")
    evidence_ids: list[str] = Field(default=[], description="For a rebuttal: verified or user_supplied evidence ids.")
    revision: Optional[OptionDraft] = Field(default=None, description="For kind revise: the full revised option with change_reason.")


class RespondResponse(StrictModel):
    responses: list[ResponseDraft] = Field(default=[], description="One response per open challenge on your option.")
    evidence: list[EvidenceDraft] = Field(default=[], description="New evidence the responses cite.")
    builds_on: list[str] = BUILDS_ON


class JudgeResponse(StrictModel):
    gate_results: list[GateResult] = Field(default=[], description="One per required gate id: pass | fail | unverified, with rationale and evidence ids.")
    criterion_scores: list[CriterionScore] = Field(min_length=1, description="One per required score id: integer 0-10 against the anchors, confidence, and at least one evidence or assumption id.")
    scenario_scores: dict[str, int] = Field(default={}, description="Optional: scenario id → 0-10 for this option.")
    # A judge may state its own assumptions (the protocol requires each score to cite evidence or state assumptions).
    assumptions: list[AssumptionDraft] = Field(default=[], description="Assumptions you made to score; cite their ids in assumption_ids.")
    builds_on: list[str] = BUILDS_ON


class CompareResponse(StrictModel):
    preferred: Literal["first", "second", "tie"] = Field(description="Which of the two versions is preferred overall.")
    rationale: str = Field(default="", description="Why, against the policy criteria, 2-4 sentences.")
    builds_on: list[str] = BUILDS_ON


class LeaderChallengeResponse(StrictModel):
    losing_scenario: str = Field(min_length=10, description="A concrete, plausible scenario in which the leader loses.")
    strongest_alternative_version_id: str = Field(description="Existing option version id that wins in that scenario.")
    distinguishing_evidence: str = Field(min_length=5, description="What evidence would tell the two apart.")
    could_alter_outcome: bool = Field(description="True when the case, if upheld, changes the recommended action.")
    related_challenge_ids: list[str] = Field(default=[], description="Open challenges (chl_*) the case builds on.")
    builds_on: list[str] = BUILDS_ON


class ChallengeReplyResponse(StrictModel):
    kind: Literal["rebut", "concede", "request_verification"] = Field(description="How the leader's owner answers the challenge.")
    text: str = Field(min_length=3, description="The answer, 2-5 sentences.")
    evidence_ids: list[str] = Field(default=[], description="For a rebuttal: verified or user_supplied evidence ids.")
    evidence: list[EvidenceDraft] = Field(default=[], description="New evidence for the rebuttal.")
    builds_on: list[str] = BUILDS_ON


RESPONSE_MODELS: dict[str, type[StrictModel]] = {
    "frame": FrameResponse,
    "policy": PolicyResponse,
    "baseline": BaselineResponse,
    "generate": GenerateResponse,
    "review": ReviewResponse,
    "verify": VerifyResponse,
    "respond": RespondResponse,
    "judge": JudgeResponse,
    "compare": CompareResponse,
    "challenge": LeaderChallengeResponse,
    "challenge_reply": ChallengeReplyResponse,
}


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------


def brief_payload(store: Store) -> dict[str, Any]:
    b = store.current_brief()
    if b is None:
        return {}
    return b.model_dump(mode="json", exclude={"created_at", "author_participant_id", "author_role", "protocol_version"})


def policy_payload(store: Store) -> dict[str, Any]:
    p = store.current_policy()
    if p is None:
        return {}
    return {
        "rubric_version": p.rubric_version,
        "criteria": [c.model_dump(mode="json") for c in p.criteria],
        "scenarios": [s.model_dump(mode="json") for s in p.scenarios],
        "materiality_threshold": p.materiality_threshold,
        "unverified_gate_policy": p.unverified_gate_policy,
    }


def evidence_payload(store: Store) -> list[dict[str, Any]]:
    return [
        {"id": e.id, "statement": e.statement, "source": e.source.model_dump(mode="json"),
         "verification_status": e.verification_status.value, "snapshot_id": e.snapshot_id}
        for e in store.data.evidence.values()
    ]


def option_payload(store: Store, v: OptionVersion, *, label: Optional[str] = None, withhold_author: bool = False) -> dict[str, Any]:
    d = store.data
    out: dict[str, Any] = {
        "id": label or v.id,
        "title": v.title,
        "summary": v.summary,
        "mechanism": v.mechanism,
        "status": v.status.value,
        "claims": [
            {"id": d.claims[c].id, "text": d.claims[c].text, "kind": d.claims[c].kind.value, "evidence_ids": d.claims[c].evidence_ids}
            for c in v.claim_ids if c in d.claims
        ],
        "assumptions": [
            {"id": d.assumptions[a].id, "text": d.assumptions[a].text, "influential": d.assumptions[a].influential}
            for a in v.assumption_ids if a in d.assumptions
        ],
    }
    if not withhold_author:
        out["lens_id"] = v.lens_id
        out["version"] = v.version
        out["parent_version_id"] = v.parent_version_id
        out["change_reason"] = v.change_reason
    return out


def challenge_payload(store: Store, c: Challenge, alias: dict[str, str]) -> dict[str, Any]:
    inv = {v: k for k, v in alias.items()}
    return {
        "id": c.id, "target_ref": inv.get(c.target_ref, c.target_ref), "mechanism": c.mechanism,
        "severity": c.severity.value, "class": c.challenge_class.value, "could_change": c.could_change.value,
        "evidence_ids": c.evidence_ids, "resolution_condition": c.resolution_condition,
        "requires_verification": c.requires_verification, "scope": c.scope.value, "status": c.status.value,
        "responses": [
            {"id": r.id, "kind": r.kind.value, "text": r.text, "evidence_ids": r.evidence_ids, "new_version_id": r.new_version_id}
            for r in store.data.responses.values() if r.challenge_id == c.id
        ],
    }


# ---------------------------------------------------------------------------
# Appliers
# ---------------------------------------------------------------------------


class Applier:
    """Turns validated responses into committed records for one request."""

    def __init__(self, store: Store, req: PendingRequest):
        self.store = store
        self.req = req
        self.new_ids: set[str] = set()
        self.remap: dict[str, str] = {}  # model-chosen ids that were renamed by the controller
        self.notes: list[str] = []  # what was dropped or ignored while committing a partially valid reply

    # -- helpers -------------------------------------------------------------

    def resolve(self, ref: str) -> str:
        """Resolve a reference through pseudonyms (isolated route) and controller renames."""
        ref = self.req.alias_map.get(ref, ref)
        return self.remap.get(ref, ref)

    def resolve_all(self, refs: list[str]) -> list[str]:
        return [self.resolve(r) for r in refs]

    def _assign_id(self, record_type: str, given: Optional[str], slug: Optional[str] = None) -> str:
        from .ontology import ID_PREFIX
        prefix = ID_PREFIX[record_type]
        if given:
            if _ID_RE.match(given) and given.startswith(prefix):
                if self.store.id_exists(given) or given in self.new_ids:
                    raise RejectedUpdate(f"id {given!r} already exists")
                self.new_ids.add(given)
                return given
            # Malformed or wrong-prefix id (models often write "E1" or "ev1"): rename deterministically and
            # remap references within this response. External output is data, so we normalise, not reject.
            if given in self.remap:
                return self.remap[given]
            new = f"{prefix}{_slug(given)}"
            while self.store.id_exists(new) or new in self.new_ids:
                new = self.store.new_id(record_type)
            self.new_ids.add(new)
            self.remap[given] = new
            return new
        rid = self.store.new_id(record_type, slug)
        while self.store.id_exists(rid) or rid in self.new_ids:
            rid = self.store.new_id(record_type)
        self.new_ids.add(rid)
        return rid

    def _author(self) -> dict[str, Any]:
        return {"author_participant_id": self.req.participant_id, "author_role": Role(self.req.role)}

    def _commit_evidence(self, drafts: list[EvidenceDraft], *, default_challenge: Optional[str] = None) -> list[str]:
        ids = []
        for e in drafts:
            if e.id and e.id in self.store.data.evidence:
                ids.append(e.id)  # an existing evidence record restated by the model: reference, not duplicate
                continue
            eid = self._assign_id("Evidence", e.id)
            ch = self.resolve(e.challenge_id) if e.challenge_id else default_challenge
            if ch is not None and ch not in self.store.data.challenges:
                raise RejectedUpdate(f"evidence references unknown challenge {ch}")
            self.store.commit(Evidence(id=eid, statement=e.statement, source=e.source,
                                       verification_status=e.verification_status, challenge_id=ch,
                                       round=self.store.data.round, **self._author()))
            ids.append(eid)
        return ids

    def _commit_option(self, draft: OptionDraft, *, lens_id: Optional[str], round_no: int,
                       parent: Optional[OptionVersion] = None) -> OptionVersion:
        d = self.store.data
        if parent is not None:
            option_id = parent.option_id
            version = parent.version + 1
            parent_id = parent.id
        else:
            option_id = draft.option_id or self.store.new_id("Option")
            if not _ID_RE.match(option_id) or not option_id.startswith("opt_"):
                option_id = f"opt_{_slug(option_id)}"
            if any(v.option_id == option_id for v in d.option_versions.values()):
                # Another lens already used this option id: keep the new option as a distinct candidate under a fresh
                # id; the controller's title-based merge decides whether it is a duplicate.
                base, n = option_id, 2
                while any(v.option_id == f"{base}_{n}" for v in d.option_versions.values()):
                    n += 1
                option_id = f"{base}_{n}"
            version = 1
            parent_id = None
        vid = self._assign_id("OptionVersion", draft.id)
        for ev_ref in [self.resolve(e) for c in draft.claims for e in c.evidence_ids]:
            if ev_ref not in d.evidence:
                raise RejectedUpdate(f"claim cites unknown evidence {ev_ref}")
        claim_ids = [self._assign_id("Claim", c.id if not (c.id and self.store.id_exists(c.id)) else None) for c in draft.claims]
        existing_asm = [a.id for a in draft.assumptions if a.id and a.id in d.assumptions]
        new_asm_drafts = [a for a in draft.assumptions if not (a.id and a.id in d.assumptions)]
        asm_ids = existing_asm + [self._assign_id("Assumption", a.id) for a in new_asm_drafts]
        ov = OptionVersion(
            id=vid, option_id=option_id, version=version, title=draft.title, summary=draft.summary,
            mechanism=draft.mechanism, lens_id=lens_id, parent_version_id=parent_id,
            status=OptionStatus.ACTIVE, change_reason=draft.change_reason,
            claim_ids=claim_ids, assumption_ids=asm_ids, generation_note=draft.generation_note, round=round_no,
            **self._author(),
        )
        self.store.commit(ov)
        for cid, c in zip(claim_ids, draft.claims):
            self.store.commit(Claim(id=cid, text=c.text, option_version_id=vid, kind=c.kind,
                                    evidence_ids=self.resolve_all(c.evidence_ids), **self._author()))
        for aid, a in zip(asm_ids[len(existing_asm):], new_asm_drafts):
            self.store.commit(Assumption(id=aid, text=a.text, option_version_id=vid, influential=a.influential,
                                         if_false_effect=a.if_false_effect, **self._author()))
        return ov

    # -- phase appliers --------------------------------------------------------

    def apply_frame(self, r: FrameResponse) -> DecisionBrief:
        d = self.store.data
        prev = self.store.current_brief()
        bid = self._assign_id("DecisionBrief", None)
        brief = DecisionBrief(
            id=bid, version=(prev.version + 1 if prev else 1), question_raw=d.question,
            decision_statement=r.decision_statement, objectives=r.objectives, stakeholders=r.stakeholders,
            hard_constraints=r.hard_constraints, preferences=r.preferences, time_horizon=r.time_horizon,
            stakes=r.stakes, reversibility=r.reversibility, domain=r.domain, evidence_gaps=r.evidence_gaps,
            interpretations=r.interpretations, inferred_assumptions=r.inferred_assumptions,
            decision_kind=r.decision_kind, supersedes_id=(prev.id if prev else None),
            user_named_options=r.user_named_options, **self._author(),
        )
        self.store.commit(brief)
        # Facts the framer extracts from the question are user-supplied; a framer that labels one of them
        # differently (e.g. 'inferred') is kept at the label it gave, since that is the more cautious record.
        self._commit_evidence(r.user_facts)
        return brief

    def apply_policy(self, r: PolicyResponse, *, materiality: float, margin: float, unverified_policy: str,
                     judge_hash: str, weight_overrides: Optional[dict[str, float]] = None) -> EvaluationPolicy:
        brief = self.store.current_brief()
        if brief is None:
            raise RejectedUpdate("no brief")
        overrides = dict(weight_overrides or {})
        # configured rubric weights (settings layer) win over the policy setter's proposal; matched by id or slugged name
        override_by_key = {(k if k.startswith("crit_") else _slug(k)): (k, w) for k, w in overrides.items()}
        applied: list[str] = []
        crits: list[Criterion] = []
        seen: set[str] = set()
        for c in r.criteria:
            cid = c.id or f"crit_{_slug(c.name)}"
            if not _ID_RE.match(cid) or not cid.startswith("crit_"):
                cid = f"crit_{_slug(c.id or c.name)}"
            if cid in seen:
                raise RejectedUpdate(f"duplicate criterion id {cid}")
            seen.add(cid)
            weight = c.weight
            hit = override_by_key.get(cid) or override_by_key.get(_slug(c.name))
            if hit is not None and c.kind == CriterionKind.SCORE:
                weight = hit[1]
                applied.append(hit[0])
            if c.kind == CriterionKind.SCORE and weight <= 0:
                raise RejectedUpdate(f"score criterion {cid} needs a positive weight")
            crits.append(Criterion(id=cid, name=c.name, kind=c.kind, description=c.description, weight=weight,
                                   anchor_0=c.anchor_0, anchor_5=c.anchor_5, anchor_10=c.anchor_10))
        unapplied = [k for k in overrides if k not in applied]
        if overrides:
            self.store.event(EventKind.POLICY_WEIGHTS_OVERRIDDEN, {"applied": applied, "unapplied": unapplied})
        scns: list[Scenario] = []
        for s in r.scenarios:
            sid = s.id or f"scn_{_slug(s.name)}"
            if not _ID_RE.match(sid) or not sid.startswith("scn_"):
                sid = f"scn_{_slug(s.id or s.name)}"
            scns.append(Scenario(id=sid, name=s.name, description=s.description, likelihood=s.likelihood, priority=s.priority))
        prev = self.store.current_policy()
        pid = self._assign_id("EvaluationPolicy", None)
        pol = EvaluationPolicy(
            id=pid, brief_id=brief.id, brief_version=brief.version,
            rubric_version=(prev.rubric_version + 1 if prev and prev.brief_version == brief.version else 1),
            criteria=crits, scenarios=scns, materiality_threshold=materiality, promotion_margin=margin,
            unverified_gate_policy=unverified_policy, judge_config_hash=judge_hash,
            weight_overrides_applied=applied, weight_overrides_unapplied=unapplied, **self._author(),
        )
        self.store.commit(pol)
        return pol

    def apply_options(self, drafts: list[OptionDraft], evidence: list[EvidenceDraft], *, lens_id: Optional[str],
                      round_no: int) -> list[OptionVersion]:
        self._commit_evidence(evidence)
        out = []
        for od in drafts:
            ov = self._commit_option(od, lens_id=lens_id, round_no=round_no)
            out.append(ov)
        return out

    def apply_review(self, r: ReviewResponse, *, round_no: int) -> tuple[list[Challenge], list[Dissent]]:
        d = self.store.data
        # Evidence may point at a challenge created in the same response; commit it unlinked first and
        # attach the challenge id once the challenge exists.
        draft_challenge_ids = {c.id for c in r.challenges if c.id}
        deferred: list[tuple[str, str]] = []
        plain: list[EvidenceDraft] = []
        for e in r.evidence:
            if e.challenge_id and e.challenge_id not in d.challenges:
                plain.append(e.model_copy(update={"challenge_id": None}))
                deferred.append((e.id or "", e.challenge_id))
            else:
                plain.append(e)
        committed_ev = self._commit_evidence(plain)
        ev_by_given = {e.id: cid for e, cid in zip(plain, committed_ev) if e.id}
        challenges: list[Challenge] = []
        dropped: list[str] = []
        for c in r.challenges:
            target = "__all__" if c.scope == ChallengeScope.SHARED_BLIND_SPOT and c.target_ref in ("__all__", "") else self.resolve(c.target_ref)
            mechanism = c.mechanism
            if target != "__all__" and target not in d.option_versions and target not in d.claims:
                # An assumption is a legal target: the challenge lands on the option version that holds it.
                owner = next((v.id for v in d.option_versions.values() if target in v.assumption_ids), None)
                if owner is None:
                    dropped.append(f"challenge on {c.target_ref!r} dropped: not an option, claim or assumption of this run")
                    continue
                mechanism = f"[assumption {target}] {c.mechanism}"
                target = owner
            resolved = self.resolve_all(c.evidence_ids)
            ev_ids = [e for e in resolved if e in d.evidence]
            unknown = [e for e in resolved if e not in d.evidence]
            cid = self._assign_id("Challenge", c.id)
            if unknown:
                self.notes.append(f"{cid}: unknown evidence ids ignored: {', '.join(unknown)}")
            ch = Challenge(
                id=cid, target_ref=target, mechanism=mechanism, severity=c.severity, challenge_class=c.challenge_class,
                could_change=c.could_change, evidence_ids=ev_ids, resolution_condition=c.resolution_condition,
                requires_verification=c.requires_verification, scope=c.scope, status=ChallengeStatus.OPEN,
                round=round_no, **self._author(),
            )
            self.store.commit(ch)
            self.store.event(EventKind.CHALLENGE_OPENED, {"challenge_id": cid, "target": target, "severity": c.severity.value,
                                                          "could_change": c.could_change.value})
            challenges.append(ch)
        if r.challenges and not challenges:
            raise RejectedUpdate("every challenge was dropped: " + "; ".join(dropped))
        self.notes.extend(dropped)
        for given_ev, given_ch in deferred:
            ev_id = ev_by_given.get(given_ev)
            ch_id = self.resolve(given_ch)
            if ev_id and ch_id in d.challenges:
                d.evidence[ev_id].challenge_id = ch_id
            elif ev_id:
                self.notes.append(f"evidence {given_ev} kept unlinked: challenge {given_ch} does not exist")
        dissents: list[Dissent] = []
        for ds in r.dissent:
            against = self.resolve(ds.against_ref)
            if not self.store.id_exists(against) and against != "__decision__":
                self.notes.append(f"dissent against unknown ref {ds.against_ref!r} dropped")
                continue
            did = self._assign_id("Dissent", None)
            dis = Dissent(id=did, participant_id=self.req.participant_id, position=ds.position, against_ref=against,
                          reason=ds.reason, what_you_lose=ds.what_you_lose, round=round_no, **self._author())
            self.store.commit(dis)
            dissents.append(dis)
        return challenges, dissents

    def apply_verify(self, r: VerifyResponse, *, challenge_id: str) -> list[str]:
        ids = self._commit_evidence(r.evidence, default_challenge=challenge_id)
        ch = self.store.data.challenges[challenge_id]
        ch.verification_attempted = True
        return ids

    def apply_respond(self, r: RespondResponse, *, round_no: int, allowed_challenge_ids: set[str],
                      target_version: OptionVersion, lens_id: Optional[str]) -> list[Response]:
        d = self.store.data
        self._commit_evidence(r.evidence)
        out: list[Response] = []
        for rd in r.responses:
            if rd.challenge_id not in allowed_challenge_ids:
                raise RejectedUpdate(f"response addresses challenge {rd.challenge_id} that is not open on this option")
            ch = d.challenges[rd.challenge_id]
            rd_evidence = self.resolve_all(rd.evidence_ids)
            for e in rd_evidence:
                if e not in d.evidence:
                    raise RejectedUpdate(f"response cites unknown evidence {e}")
            new_version_id = None
            if rd.kind == ResponseKind.REVISE:
                if rd.revision is None:
                    raise RejectedUpdate("revise responses must include the full 'revision' option")
                latest = self.store.latest_version(target_version.option_id) or target_version
                nv = self._commit_option(rd.revision, lens_id=lens_id, round_no=round_no, parent=latest)
                new_version_id = nv.id
            rid = self._assign_id("Response", None)
            resp = Response(id=rid, challenge_id=rd.challenge_id, kind=rd.kind, text=rd.text, evidence_ids=rd_evidence,
                            new_version_id=new_version_id, round=round_no, **self._author())
            self.store.commit(resp)
            out.append(resp)
            # Controller resolution rules
            if rd.kind == ResponseKind.REBUT:
                if any(d.evidence[e].verification_status in QUALIFYING_EVIDENCE for e in rd_evidence):
                    ch.status = ChallengeStatus.RESOLVED
                    ch.resolution_note = f"rebutted with qualifying evidence by {rid}"
                    self.store.event(EventKind.CHALLENGE_RESOLVED, {"challenge_id": ch.id, "by": rid, "how": "rebut"})
                else:
                    ch.resolution_note = f"rebuttal {rid} lacks verified or user-supplied evidence; challenge stays open"
            elif rd.kind == ResponseKind.CONCEDE:
                ch.resolution_note = f"conceded by {rid}"
            elif rd.kind == ResponseKind.WITHDRAW:
                latest = self.store.latest_version(target_version.option_id) or target_version
                wid = self._assign_id("OptionVersion", None)
                withdrawn = latest.model_copy(update={
                    "id": wid, "version": latest.version + 1, "parent_version_id": latest.id,
                    "status": OptionStatus.WITHDRAWN, "change_reason": f"withdrawn: {rd.text}", "round": round_no,
                    "claim_ids": [], "assumption_ids": [], "created_at": latest.created_at,
                    **self._author(),
                })
                self.store.commit(withdrawn)
                ch.status = ChallengeStatus.RESOLVED
                ch.resolution_note = f"option withdrawn by {rid}"
                self.store.event(EventKind.CHALLENGE_RESOLVED, {"challenge_id": ch.id, "by": rid, "how": "withdraw"})
            elif rd.kind == ResponseKind.REINSTATE:
                latest = self.store.latest_version(target_version.option_id) or target_version
                if latest.status != OptionStatus.WITHDRAWN:
                    raise RejectedUpdate("only withdrawn options can be reinstated")
                rid2 = self._assign_id("OptionVersion", None)
                source = d.option_versions[latest.parent_version_id] if latest.parent_version_id else latest
                reinstated = source.model_copy(update={
                    "id": rid2, "version": latest.version + 1, "parent_version_id": latest.id,
                    "status": OptionStatus.REINSTATED, "change_reason": f"reinstated: {rd.text}", "round": round_no,
                    **self._author(),
                })
                self.store.commit(reinstated)
            elif rd.kind == ResponseKind.REVISE:
                ch.resolution_note = f"revision {new_version_id} proposed by {rid}; resolves for the new version once judged"
        return out

    def apply_leader_challenge(self, r: LeaderChallengeResponse, *, leader_version_id: str, round_no: int) -> LeaderChallenge:
        d = self.store.data
        alt = self.resolve(r.strongest_alternative_version_id)
        if alt not in d.option_versions:
            raise RejectedUpdate(f"strongest_alternative_version_id {r.strongest_alternative_version_id!r} unknown")
        if alt == leader_version_id:
            raise RejectedUpdate("strongest alternative must differ from the leader")
        for c in r.related_challenge_ids:
            if c not in d.challenges:
                raise RejectedUpdate(f"unknown related challenge {c}")
        # Mirror as a Challenge record so the standard response/resolution path applies.
        cid = self._assign_id("Challenge", None)
        ch = Challenge(
            id=cid, target_ref=leader_version_id, mechanism=f"Leader challenge: {r.losing_scenario}",
            severity=Severity.CRITICAL, challenge_class=ChallengeClass.SCENARIO,
            could_change=CouldChange.ACTION if r.could_alter_outcome else CouldChange.RANKING,
            resolution_condition=r.distinguishing_evidence, requires_verification=False,
            scope=ChallengeScope.TARGETED, status=ChallengeStatus.OPEN, round=round_no, **self._author(),
        )
        self.store.commit(ch)
        self.store.event(EventKind.CHALLENGE_OPENED, {"challenge_id": cid, "target": leader_version_id, "leader_challenge": True})
        lid = self._assign_id("LeaderChallenge", None)
        lc = LeaderChallenge(
            id=lid, leader_version_id=leader_version_id, losing_scenario=r.losing_scenario,
            strongest_alternative_version_id=alt, distinguishing_evidence=r.distinguishing_evidence,
            could_alter_outcome=r.could_alter_outcome, status=ChallengeStatus.OPEN,
            related_challenge_ids=[cid] + list(r.related_challenge_ids), round=round_no, **self._author(),
        )
        self.store.commit(lc)
        return lc

    def apply_challenge_reply(self, r: ChallengeReplyResponse, *, leader_challenge_id: str, round_no: int) -> Response:
        d = self.store.data
        lc = d.leader_challenges[leader_challenge_id]
        mirror_id = lc.related_challenge_ids[0]
        ch = d.challenges[mirror_id]
        self._commit_evidence(r.evidence, default_challenge=mirror_id)
        ev_ids = self.resolve_all(r.evidence_ids)
        for e in ev_ids:
            if e not in d.evidence:
                raise RejectedUpdate(f"reply cites unknown evidence {e}")
        rid = self._assign_id("Response", None)
        resp = Response(id=rid, challenge_id=mirror_id, kind=ResponseKind(r.kind), text=r.text,
                        evidence_ids=ev_ids, round=round_no, **self._author())
        self.store.commit(resp)
        lc.response_id = rid
        if r.kind == "rebut" and any(d.evidence[e].verification_status in QUALIFYING_EVIDENCE for e in ev_ids):
            ch.status = ChallengeStatus.RESOLVED
            lc.status = ChallengeStatus.RESOLVED
            ch.resolution_note = f"leader challenge rebutted with qualifying evidence by {rid}"
            self.store.event(EventKind.CHALLENGE_RESOLVED, {"challenge_id": mirror_id, "by": rid, "how": "rebut"})
            # Related challenges the leader challenge was built on are settled by the same evidence.
            for rel in lc.related_challenge_ids[1:]:
                rc = d.challenges.get(rel)
                if rc is not None and rc.status == ChallengeStatus.OPEN:
                    rc.status = ChallengeStatus.RESOLVED
                    rc.resolution_note = f"settled by the evidence that resolved leader challenge {lc.id} ({rid})"
                    self.store.event(EventKind.CHALLENGE_RESOLVED, {"challenge_id": rel, "by": rid, "how": "leader_challenge_resolution"})
        else:
            ch.resolution_note = f"leader challenge reply {rid} ({r.kind}) did not resolve it"
        return resp


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:40] or "x"


def lens_instruction(lens_id: Optional[str]) -> Optional[str]:
    if lens_id and lens_id in LENSES:
        return LENSES[lens_id].instruction
    return None
