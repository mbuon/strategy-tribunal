"""Protocol v1.0 ontology: validated records, enumerations, relations, role
permissions and state names.

Records are immutable once committed. Decision-relevant changes create a new
version linked by a ``supersedes`` relation. All records carry a stable id with
a type prefix and the protocol version.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import PROTOCOL_VERSION


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Role(str, Enum):
    CONTROLLER = "controller"
    FRAMER = "framer"
    POLICY_SETTER = "policy_setter"
    STRATEGIST = "strategist"
    REVIEWER = "reviewer"
    VERIFIER = "verifier"
    JUDGE = "judge"
    CHALLENGER = "challenger"
    USER = "user"


class RunState(str, Enum):
    INIT = "INIT"
    FRAMING = "FRAMING"
    POLICY = "POLICY"
    BASELINE = "BASELINE"
    GENERATING = "GENERATING"
    REVIEWING = "REVIEWING"
    VERIFYING = "VERIFYING"
    RESPONDING = "RESPONDING"
    REVISING = "REVISING"
    JUDGING = "JUDGING"
    CHALLENGING = "CHALLENGING"
    REPORTING = "REPORTING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = {RunState.COMPLETE, RunState.FAILED, RunState.CANCELLED}


class RequestKind(str, Enum):
    FRAME = "frame"
    POLICY = "policy"
    BASELINE = "baseline"
    GENERATE = "generate"
    REVIEW = "review"
    VERIFY = "verify"
    RESPOND = "respond"
    JUDGE = "judge"
    COMPARE = "compare"
    CHALLENGE = "challenge"
    CHALLENGE_REPLY = "challenge_reply"


class Isolation(str, Enum):
    SHARED = "shared"
    ISOLATED = "isolated"


class Stakes(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Reversibility(str, Enum):
    REVERSIBLE = "reversible"
    COSTLY = "costly"
    ONE_WAY = "one_way"


class Domain(str, Enum):
    CLEAR = "clear"
    COMPLICATED = "complicated"
    COMPLEX = "complex"
    CHAOTIC = "chaotic"


class DecisionKind(str, Enum):
    DECISION = "decision"
    TRIVIAL = "trivial"
    CONDITIONAL_CANDIDATE = "conditional_candidate"


class ConstraintSource(str, Enum):
    USER_STATED = "user_stated"
    INFERRED = "inferred"


class CriterionKind(str, Enum):
    GATE = "gate"
    SCORE = "score"


class Likelihood(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OptionStatus(str, Enum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"
    MERGED = "merged"
    REINSTATED = "reinstated"


class ClaimKind(str, Enum):
    FACT = "fact"
    INFERENCE = "inference"
    PREDICTION = "prediction"


class EvidenceSourceKind(str, Enum):
    USER = "user"
    DOCUMENT = "document"
    URL = "url"
    MODEL_KNOWLEDGE = "model_knowledge"
    COMPUTATION = "computation"


class VerificationStatus(str, Enum):
    USER_SUPPLIED = "user_supplied"
    VERIFIED = "verified"
    INFERRED = "inferred"
    DISPUTED = "disputed"
    UNAVAILABLE = "unavailable"


QUALIFYING_EVIDENCE = {VerificationStatus.USER_SUPPLIED, VerificationStatus.VERIFIED}


class Severity(str, Enum):
    MINOR = "minor"
    MATERIAL = "material"
    CRITICAL = "critical"


class ChallengeClass(str, Enum):
    FACTUAL = "factual"
    EVIDENTIARY = "evidentiary"
    VALUE = "value"
    SCENARIO = "scenario"
    EXECUTION = "execution"


class CouldChange(str, Enum):
    NONE = "none"
    ELIGIBILITY = "eligibility"
    RANKING = "ranking"
    ACTION = "action"


class ChallengeScope(str, Enum):
    TARGETED = "targeted"
    SHARED_BLIND_SPOT = "shared_blind_spot"


class ChallengeStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    WITHDRAWN = "withdrawn"
    UNRESOLVED_FINAL = "unresolved_final"


class ResponseKind(str, Enum):
    REBUT = "rebut"
    CONCEDE = "concede"
    REVISE = "revise"
    REQUEST_VERIFICATION = "request_verification"
    WITHDRAW = "withdraw"
    REINSTATE = "reinstate"


class GateOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNVERIFIED = "unverified"


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class JudgementStatus(str, Enum):
    COMPLETE = "complete"
    MISSING = "missing"


class ScoringMethod(str, Enum):
    STRUCTURED_SCORES = "structured_scores"
    LOGPROB_EXPECTATION = "logprob_expectation"


class PromotionOutcome(str, Enum):
    BASELINE = "baseline"
    PROMOTED = "promoted"
    RETAINED_TIE = "retained_tie"
    RETAINED_LOSS = "retained_loss"
    INCONCLUSIVE = "inconclusive"
    NON_COMPARABLE = "non_comparable"
    INCUMBENT_INELIGIBLE = "incumbent_ineligible"
    NO_CHALLENGER = "no_challenger"


class StopReason(str, Enum):
    STABLE = "stable"
    NO_PRODUCTIVE_FOLLOW_UP = "no_productive_follow_up"
    MAX_ROUNDS = "max_rounds"
    BUDGET_CALLS = "budget_calls"
    BUDGET_TOKENS = "budget_tokens"
    BUDGET_TIME = "budget_time"
    BUDGET_COST = "budget_cost"
    CANCELLED = "cancelled"
    FAILED = "failed"
    TRIVIAL_QUESTION = "trivial_question"


class DecisionOutcomeKind(str, Enum):
    FIRM = "firm"
    CONDITIONAL = "conditional"
    SHORTLIST = "shortlist"
    INFORMATION_REQUEST = "information_request"
    NO_ELIGIBLE_OPTION = "no_eligible_option"


class RelationKind(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CHALLENGES = "challenges"
    ADDRESSES = "addresses"
    SUPERSEDES = "supersedes"


class EventKind(str, Enum):
    RUN_CREATED = "run_created"
    PHASE_ENTERED = "phase_entered"
    REQUEST_ISSUED = "request_issued"
    RESPONSE_COMMITTED = "response_committed"
    RESPONSE_REJECTED = "response_rejected"
    RESPONSE_DUPLICATE = "response_duplicate"
    REQUEST_FAILED = "request_failed"
    INCUMBENT_CHANGED = "incumbent_changed"
    CHALLENGE_OPENED = "challenge_opened"
    CHALLENGE_RESOLVED = "challenge_resolved"
    EVIDENCE_SNAPSHOT_CHANGED = "evidence_snapshot_changed"
    RESCORE_REQUIRED = "rescore_required"
    BUDGET_WARNING = "budget_warning"
    ROUTE_FALLBACK = "route_fallback"
    ROUTE_SUBSTITUTION = "route_substitution"
    ROUND_SUMMARISED = "round_summarised"
    REOPENED = "reopened"
    STOP_DECIDED = "stop_decided"
    POLICY_WEIGHTS_OVERRIDDEN = "policy_weights_overridden"
    RUN_FINISHED = "run_finished"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stable_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


class StrictModel(BaseModel):
    """Base for all records: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class Record(StrictModel):
    id: str
    protocol_version: str = PROTOCOL_VERSION
    created_at: str = Field(default_factory=now_iso)
    author_participant_id: str
    author_role: Role

    @field_validator("protocol_version")
    @classmethod
    def _check_version(cls, v: str) -> str:
        if v != PROTOCOL_VERSION:
            raise ValueError(f"unsupported protocol version {v!r}; expected {PROTOCOL_VERSION!r}")
        return v


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------


class Participant(StrictModel):
    id: str
    role: Role
    lens_id: Optional[str] = None
    provider: str
    model_requested: Optional[str] = None
    model_reported: Optional[str] = None
    substitution: Optional[str] = None
    isolation: Isolation = Isolation.SHARED
    sampling_supported: bool = False
    calls: int = 0                                  # answers received (committed or rejected)
    tokens: int = 0                                 # measured where available, otherwise estimated
    latency_seconds: float = 0.0                    # summed wall-clock time of its answers
    effort: Optional[str] = None                    # last known effort/variant label


# ---------------------------------------------------------------------------
# Brief, policy
# ---------------------------------------------------------------------------


class Constraint(StrictModel):
    text: str
    source: ConstraintSource


class Interpretation(StrictModel):
    text: str
    implied_action: str


class DecisionBrief(Record):
    version: int = 1
    question_raw: str
    decision_statement: str
    objectives: list[str]
    stakeholders: list[str] = []
    hard_constraints: list[Constraint] = []
    preferences: list[str] = []
    time_horizon: str
    stakes: Stakes
    reversibility: Reversibility
    domain: Domain = Domain.COMPLICATED
    evidence_gaps: list[str] = []
    interpretations: list[Interpretation] = []
    inferred_assumptions: list[str] = []
    decision_kind: DecisionKind = DecisionKind.DECISION
    supersedes_id: Optional[str] = None
    user_named_options: list[str] = []


class Criterion(StrictModel):
    id: str
    name: str
    kind: CriterionKind
    description: str = ""
    weight: float = Field(default=0.0, ge=0.0)
    anchor_0: str = ""
    anchor_5: str = ""
    anchor_10: str = ""


class Scenario(StrictModel):
    id: str
    name: str
    description: str = ""
    likelihood: Likelihood = Likelihood.MEDIUM
    priority: bool = False


class EvaluationPolicy(Record):
    brief_id: str
    brief_version: int
    rubric_version: int = 1
    criteria: list[Criterion]
    scenarios: list[Scenario] = []
    materiality_threshold: float
    promotion_margin: float
    unverified_gate_policy: str
    judge_config_hash: str
    weight_overrides_applied: list[str] = []
    weight_overrides_unapplied: list[str] = []

    @property
    def score_criteria(self) -> list[Criterion]:
        return [c for c in self.criteria if c.kind == CriterionKind.SCORE]

    @property
    def gate_criteria(self) -> list[Criterion]:
        return [c for c in self.criteria if c.kind == CriterionKind.GATE]

    def normalised_weights(self) -> dict[str, float]:
        scored = self.score_criteria
        total = sum(c.weight for c in scored)
        if total <= 0:
            raise ValueError("score criteria weights must sum to a positive number")
        return {c.id: c.weight / total for c in scored}


# ---------------------------------------------------------------------------
# Options, claims, assumptions, evidence
# ---------------------------------------------------------------------------


class GenerationNote(StrictModel):
    how: str
    resources: str = "model only"
    missing_inputs: list[str] = []


class OptionVersion(Record):
    option_id: str
    version: int
    title: str
    summary: str
    mechanism: str = ""
    lens_id: Optional[str] = None
    parent_version_id: Optional[str] = None
    merged_from: list[str] = []
    status: OptionStatus = OptionStatus.ACTIVE
    change_reason: str = ""
    claim_ids: list[str] = []
    assumption_ids: list[str] = []
    generation_note: GenerationNote
    round: int


class Claim(Record):
    text: str
    option_version_id: str
    kind: ClaimKind = ClaimKind.INFERENCE
    evidence_ids: list[str] = []


class Assumption(Record):
    text: str
    option_version_id: Optional[str] = None
    influential: bool = False
    if_false_effect: str = ""


class EvidenceSource(StrictModel):
    kind: EvidenceSourceKind
    ref: str = ""


class Evidence(Record):
    statement: str
    source: EvidenceSource
    verification_status: VerificationStatus
    snapshot_id: str = ""
    challenge_id: Optional[str] = None
    round: int = 0


# ---------------------------------------------------------------------------
# Challenges and responses
# ---------------------------------------------------------------------------


class Challenge(Record):
    target_ref: str
    mechanism: str
    severity: Severity
    challenge_class: ChallengeClass
    could_change: CouldChange
    evidence_ids: list[str] = []
    resolution_condition: str = ""
    requires_verification: bool = False
    scope: ChallengeScope = ChallengeScope.TARGETED
    status: ChallengeStatus = ChallengeStatus.OPEN
    round: int
    resolution_note: str = ""
    verification_attempted: bool = False


class Response(Record):
    challenge_id: str
    kind: ResponseKind
    text: str
    evidence_ids: list[str] = []
    new_version_id: Optional[str] = None
    round: int


# ---------------------------------------------------------------------------
# Judgements
# ---------------------------------------------------------------------------


class ComparisonKey(StrictModel):
    brief_version: int
    rubric_version: int
    evidence_snapshot_id: str
    judge_config_hash: str

    def as_tuple(self) -> tuple:
        return (self.brief_version, self.rubric_version, self.evidence_snapshot_id, self.judge_config_hash)


class GateResult(StrictModel):
    criterion_id: str = Field(description="The gate's criterion id from the policy (required_gate_ids).")
    outcome: GateOutcome = Field(description="pass | fail | unverified (cannot be checked from the evidence).")
    rationale: str = Field(default="", description="Why, 1-2 sentences.")
    evidence_ids: list[str] = Field(default=[], description="Evidence ids the outcome rests on.")
    # An "unverified" or "pass" gate may rest on a stated assumption; the live OpenCode probe
    # (claude-agent/haiku, 2026-11-24) produced exactly that, so the contract allows it.
    assumption_ids: list[str] = Field(default=[], description="Assumption ids the outcome rests on.")


class CriterionScore(StrictModel):
    criterion_id: str = Field(description="The score criterion id from the policy (required_score_ids).")
    score: int = Field(ge=0, le=10, description="Integer 0-10 against the criterion's anchors.")
    confidence: Confidence = Field(default=Confidence.MEDIUM, description="low | medium | high: how sure you are of this score.")
    rationale: str = Field(default="", description="Why, 1-2 sentences.")
    evidence_ids: list[str] = Field(default=[], description="Evidence ids behind the score (at least one of evidence_ids or assumption_ids).")
    assumption_ids: list[str] = Field(default=[], description="Assumption ids behind the score.")

    @model_validator(mode="after")
    def _cites_something(self) -> "CriterionScore":
        if not self.evidence_ids and not self.assumption_ids:
            raise ValueError(
                f"criterion score for {self.criterion_id} must cite evidence_ids or assumption_ids"
            )
        return self


class Judgement(Record):
    option_version_id: str
    comparison_key: ComparisonKey
    participant_id: str
    gate_results: list[GateResult] = []
    criterion_scores: list[CriterionScore] = []
    scenario_scores: dict[str, int] = {}
    status: JudgementStatus = JudgementStatus.COMPLETE
    method: ScoringMethod = ScoringMethod.STRUCTURED_SCORES
    order_position: Optional[int] = None
    round: int
    # controller-computed, filled on commit
    aggregate: Optional[float] = None
    lower_bound: Optional[float] = None
    upper_bound: Optional[float] = None
    eligible: Optional[bool] = None
    penalties: float = 0.0
    unverified_gates: list[str] = []
    failed_gates: list[str] = []


class PairwiseComparison(Record):
    first_version_id: str
    second_version_id: str
    preferred: Literal["first", "second", "tie"]
    rationale: str = ""
    comparison_key: ComparisonKey
    round: int


class Dissent(Record):
    participant_id: str
    position: str
    against_ref: str
    reason: str
    what_you_lose: str = ""
    round: int


class LeaderChallenge(Record):
    leader_version_id: str
    losing_scenario: str
    strongest_alternative_version_id: str
    distinguishing_evidence: str
    could_alter_outcome: bool
    response_id: Optional[str] = None
    status: ChallengeStatus = ChallengeStatus.OPEN
    related_challenge_ids: list[str] = []
    round: int


# ---------------------------------------------------------------------------
# Summaries, events, decision
# ---------------------------------------------------------------------------


class BudgetSnapshot(StrictModel):
    model_calls_used: int
    model_calls_limit: int
    tokens_estimated: int
    tokens_measured: int
    tokens_limit: int
    elapsed_seconds: float
    elapsed_limit: float
    cost_usd: Optional[float] = None
    cost_limit: Optional[float] = None
    cost_status: Literal["measured", "unavailable", "partial"] = "unavailable"


class Delta(StrictModel):
    value: Optional[float] = None
    comparable: bool = False
    note: str = ""


class RoundSummary(Record):
    round: int
    incumbent_version_id: Optional[str]
    prior_incumbent_version_id: Optional[str]
    challenger_version_id: Optional[str]
    promotion_outcome: PromotionOutcome
    delta_vs_parent: Delta = Delta()
    delta_vs_prior_incumbent: Delta = Delta()
    net_vs_round0: Delta = Delta()
    comparison_key: Optional[ComparisonKey] = None
    comparable: bool
    open_challenge_ids: list[str] = []
    open_critical_count: int = 0
    resolved_challenge_ids: list[str] = []
    new_version_ids: list[str] = []
    new_evidence_ids: list[str] = []
    dissent_ids: list[str] = []
    ranking: list[tuple[str, float]] = []
    non_comparable_version_ids: list[str] = []
    budget: BudgetSnapshot
    productive: bool = True
    stable_streak: int = 0
    note: str = ""


class RunEvent(StrictModel):
    id: str
    protocol_version: str = PROTOCOL_VERSION
    created_at: str = Field(default_factory=now_iso)
    kind: EventKind
    state_before: RunState
    state_after: RunState
    round: int
    payload: dict[str, Any] = {}
    dedup_key: Optional[str] = None


class ConfidenceReport(StrictModel):
    level: Confidence
    basis: str
    raise_if: list[str] = []
    lower_if: list[str] = []


class Signals(StrictModel):
    evidence_quality: Optional[float] = None
    judge_agreement: Optional[float] = None
    judge_agreement_note: str = ""
    ranking_robustness: Optional[float] = None
    ranking_flips: list[str] = []
    decisive_uncertainty: list[str] = []


class RoundHistoryItem(StrictModel):
    round: int
    incumbent_version_id: Optional[str]
    promotion_outcome: PromotionOutcome
    incumbent_score: Optional[float]
    delta_vs_prior_incumbent: Delta
    net_vs_round0: Delta
    comparable: bool
    open_critical_count: int


class Decision(Record):
    kind: DecisionOutcomeKind
    recommended_version_id: Optional[str]
    alternatives: list[str] = []
    decisive_evidence_ids: list[str] = []
    material_dissent_ids: list[str] = []
    unresolved_challenge_ids: list[str] = []
    trade_offs: list[str] = []
    confidence: ConfidenceReport
    signals: Signals
    stop_reason: StopReason
    unfinished_checks: list[str] = []
    next_action: str
    reversal_conditions: list[str] = []
    round_history: list[RoundHistoryItem] = []
    limitations: list[str] = []
    failed_to_establish: list[str] = []
    completed_phases: list[str] = []
    budget: BudgetSnapshot


class Relation(StrictModel):
    kind: RelationKind
    from_id: str
    to_id: str


# ---------------------------------------------------------------------------
# Role permissions: which record types each role may author
# ---------------------------------------------------------------------------


ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.CONTROLLER: {
        "DecisionBrief", "EvaluationPolicy", "OptionVersion", "Claim", "Assumption", "Evidence",
        "Challenge", "Response", "Judgement", "PairwiseComparison", "Dissent", "LeaderChallenge",
        "RoundSummary", "Decision",
    },
    Role.FRAMER: {"DecisionBrief", "Evidence", "Assumption"},
    Role.POLICY_SETTER: {"EvaluationPolicy"},
    Role.STRATEGIST: {"OptionVersion", "Claim", "Assumption", "Evidence", "Response"},
    Role.REVIEWER: {"Challenge", "Evidence", "Dissent"},
    Role.VERIFIER: {"Evidence"},
    Role.JUDGE: {"Judgement", "PairwiseComparison", "Assumption"},
    Role.CHALLENGER: {"LeaderChallenge", "Challenge", "Dissent"},
    Role.USER: set(),
}


# Allowed state transitions (from -> set(to)).
TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.INIT: {RunState.FRAMING, RunState.FAILED, RunState.CANCELLED},
    RunState.FRAMING: {RunState.POLICY, RunState.BASELINE, RunState.FAILED, RunState.CANCELLED, RunState.REPORTING},
    RunState.POLICY: {RunState.BASELINE, RunState.FAILED, RunState.CANCELLED, RunState.REPORTING},
    RunState.BASELINE: {RunState.JUDGING, RunState.FAILED, RunState.CANCELLED, RunState.REPORTING},
    RunState.GENERATING: {RunState.REVIEWING, RunState.FAILED, RunState.CANCELLED, RunState.REPORTING},
    RunState.REVIEWING: {RunState.VERIFYING, RunState.RESPONDING, RunState.REVISING, RunState.JUDGING, RunState.FAILED, RunState.CANCELLED, RunState.REPORTING},
    RunState.VERIFYING: {RunState.RESPONDING, RunState.REVISING, RunState.JUDGING, RunState.FAILED, RunState.CANCELLED, RunState.REPORTING},
    RunState.RESPONDING: {RunState.REVISING, RunState.JUDGING, RunState.FAILED, RunState.CANCELLED, RunState.REPORTING},
    RunState.REVISING: {RunState.JUDGING, RunState.FAILED, RunState.CANCELLED, RunState.REPORTING},
    RunState.JUDGING: {RunState.GENERATING, RunState.REVIEWING, RunState.CHALLENGING, RunState.REPORTING, RunState.FAILED, RunState.CANCELLED, RunState.FRAMING},
    RunState.CHALLENGING: {RunState.REVIEWING, RunState.JUDGING, RunState.REPORTING, RunState.FAILED, RunState.CANCELLED},
    RunState.REPORTING: {RunState.COMPLETE, RunState.FAILED, RunState.CANCELLED},
    RunState.COMPLETE: set(),
    RunState.FAILED: set(),
    RunState.CANCELLED: set(),
}


RECORD_TYPES: dict[str, type[BaseModel]] = {
    "DecisionBrief": DecisionBrief,
    "EvaluationPolicy": EvaluationPolicy,
    "OptionVersion": OptionVersion,
    "Claim": Claim,
    "Assumption": Assumption,
    "Evidence": Evidence,
    "Challenge": Challenge,
    "Response": Response,
    "Judgement": Judgement,
    "PairwiseComparison": PairwiseComparison,
    "Dissent": Dissent,
    "LeaderChallenge": LeaderChallenge,
    "RoundSummary": RoundSummary,
    "Decision": Decision,
}

ID_PREFIX: dict[str, str] = {
    "DecisionBrief": "brief_",
    "EvaluationPolicy": "pol_",
    "OptionVersion": "optv_",
    "Claim": "clm_",
    "Assumption": "asm_",
    "Evidence": "ev_",
    "Challenge": "chl_",
    "Response": "rsp_",
    "Judgement": "jdg_",
    "PairwiseComparison": "cmp_",
    "Dissent": "dis_",
    "LeaderChallenge": "lch_",
    "RoundSummary": "rsm_",
    "Decision": "dec_",
    "RunEvent": "evt_",
    "Participant": "p_",
    "Option": "opt_",
}
