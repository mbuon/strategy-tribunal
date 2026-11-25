"""Run store: committed state, append-only event log, snapshot, dedup, resume.

Only the controller mutates the store, through ``commit`` (validated records),
``set_state`` (allowed transitions only) and ``event``. Every mutation is
persisted: events to ``events.jsonl`` (append) and the full state to
``state.json`` (rewrite). Resume rebuilds from ``state.json``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from . import PROTOCOL_VERSION
from .budget import Budget
from .ontology import (
    ID_PREFIX,
    RECORD_TYPES,
    ROLE_PERMISSIONS,
    TRANSITIONS,
    Assumption,
    Challenge,
    Claim,
    Decision,
    DecisionBrief,
    Dissent,
    EvaluationPolicy,
    EventKind,
    Evidence,
    Judgement,
    LeaderChallenge,
    OptionVersion,
    PairwiseComparison,
    Participant,
    Relation,
    RelationKind,
    Response,
    Role,
    RoundSummary,
    RunEvent,
    RunState,
    StopReason,
    VerificationStatus,
    now_iso,
)


class RejectedUpdate(Exception):
    """Raised when a record or transition is invalid. Nothing was mutated."""


class PendingRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    request_id: str
    attempt: int
    kind: str
    role: str
    round: int
    state: str
    participant_id: str
    lens_id: Optional[str] = None
    dedup_key: str
    alias_map: dict[str, str] = {}
    match_hints: dict[str, Any] = {}
    instructions: str = ""
    payload: dict[str, Any] = {}
    response_model: str = ""
    response_schema: dict[str, Any] = {}
    isolation: str = "shared"
    provider: str = "chat"
    model: Optional[str] = None
    expect: dict[str, Any] = {}  # controller-side expectations (e.g. target version id)


class RunData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: str = PROTOCOL_VERSION
    run_id: str
    question: str
    created_at: str = Field(default_factory=now_iso)
    state: RunState = RunState.INIT
    round: int = 0
    effective_config: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    preset: Optional[str] = None
    chat_model: Optional[str] = None     # identity of the conversation model answering chat-routed requests, when declared
    discussion: list[dict[str, Any]] = []   # ordered index of every model contribution (files under discussion/)
    documents: list[dict[str, Any]] = []    # user documents registered as evidence (copies under inputs/)
    document_notes: list[str] = []

    participants: dict[str, Participant] = {}
    briefs: dict[str, DecisionBrief] = {}
    policies: dict[str, EvaluationPolicy] = {}
    option_versions: dict[str, OptionVersion] = {}
    claims: dict[str, Claim] = {}
    assumptions: dict[str, Assumption] = {}
    evidence: dict[str, Evidence] = {}
    challenges: dict[str, Challenge] = {}
    responses: dict[str, Response] = {}
    judgements: dict[str, Judgement] = {}
    comparisons: dict[str, PairwiseComparison] = {}
    dissents: dict[str, Dissent] = {}
    leader_challenges: dict[str, LeaderChallenge] = {}
    round_summaries: dict[str, RoundSummary] = {}
    decision: Optional[Decision] = None
    relations: list[Relation] = []

    counters: dict[str, int] = {}
    options_order: list[str] = []  # option ids in creation order
    incumbent_version_id: Optional[str] = None
    incumbent_history: list[dict[str, Any]] = []
    evidence_snapshot_id: str = "snap-0"
    snapshot_counter: int = 0

    pending_request: Optional[PendingRequest] = None
    dedup: dict[str, dict[str, Any]] = {}
    budget: Budget = Field(default_factory=Budget.start)
    selected_lenses: list[str] = []
    cursor: dict[str, Any] = {}
    stable_streak: int = 0
    stop_reason: Optional[StopReason] = None
    pending_stop_reason: Optional[StopReason] = None
    completed_phases: list[str] = []
    unfinished_checks: list[str] = []
    limitations: list[str] = []
    events_count: int = 0
    failure_reason: Optional[str] = None
    cancel_requested: bool = False


class Store:
    def __init__(self, run_dir: Path, data: RunData):
        self.run_dir = run_dir
        self.data = data
        self._tx_events: Optional[list[RunEvent]] = None
        self._tx_backup: Optional[RunData] = None
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "requests").mkdir(exist_ok=True)
        (self.run_dir / "responses").mkdir(exist_ok=True)

    # -- transactions (atomic application of one response) ------------------

    def begin(self) -> None:
        if self._tx_backup is not None:
            raise RuntimeError("transaction already open")
        self._tx_backup = self.data.model_copy(deep=True)
        self._tx_events = []

    def rollback(self) -> None:
        if self._tx_backup is None:
            raise RuntimeError("no transaction open")
        self.data = self._tx_backup
        self._tx_backup = None
        self._tx_events = None

    def end(self) -> None:
        if self._tx_backup is None:
            raise RuntimeError("no transaction open")
        self.verify_integrity()
        for ev in self._tx_events or []:
            self._append_event_line(ev)
        self._tx_backup = None
        self._tx_events = None

    def verify_integrity(self) -> None:
        d = self.data
        for v in d.option_versions.values():
            for c in v.claim_ids:
                if c not in d.claims:
                    raise RejectedUpdate(f"option version {v.id} references unknown claim {c}")
            for a in v.assumption_ids:
                if a not in d.assumptions:
                    raise RejectedUpdate(f"option version {v.id} references unknown assumption {a}")

    # -- persistence -------------------------------------------------------

    @classmethod
    def create(cls, runs_root: Path, run_id: str, question: str) -> "Store":
        run_dir = runs_root / run_id
        if run_dir.exists() and (run_dir / "state.json").exists():
            raise RejectedUpdate(f"run {run_id} already exists")
        store = cls(run_dir, RunData(run_id=run_id, question=question))
        store.save()
        return store

    @classmethod
    def load(cls, runs_root: Path, run_id: str) -> "Store":
        run_dir = runs_root / run_id
        path = run_dir / "state.json"
        if not path.exists():
            raise FileNotFoundError(f"no run state at {path}")
        data = RunData.model_validate_json(path.read_text())
        return cls(run_dir, data)

    def save(self) -> None:
        tmp = self.run_dir / "state.json.tmp"
        tmp.write_text(self.data.model_dump_json(indent=1))
        os.replace(tmp, self.run_dir / "state.json")

    def _append_event_line(self, ev: RunEvent) -> None:
        with (self.run_dir / "events.jsonl").open("a") as fh:
            fh.write(ev.model_dump_json() + "\n")

    def cancel_flag_present(self) -> bool:
        return (self.run_dir / ".cancel").exists() or self.data.cancel_requested

    # -- ids -----------------------------------------------------------------

    def new_id(self, record_type: str, slug: Optional[str] = None) -> str:
        prefix = ID_PREFIX[record_type]
        n = self.data.counters.get(record_type, 0) + 1
        self.data.counters[record_type] = n
        if slug:
            return f"{prefix}{slug}"
        return f"{prefix}{n:04d}"

    def id_exists(self, rid: str) -> bool:
        d = self.data
        return any(rid in coll for coll in (
            d.briefs, d.policies, d.option_versions, d.claims, d.assumptions, d.evidence, d.challenges,
            d.responses, d.judgements, d.comparisons, d.dissents, d.leader_challenges, d.round_summaries,
        )) or (d.decision is not None and d.decision.id == rid) or rid in d.participants

    # -- events and state --------------------------------------------------

    def event(self, kind: EventKind, payload: Optional[dict[str, Any]] = None, *,
              state_after: Optional[RunState] = None, dedup_key: Optional[str] = None) -> RunEvent:
        ev = RunEvent(
            id=self.new_id("RunEvent"),
            kind=kind,
            state_before=self.data.state,
            state_after=state_after or self.data.state,
            round=self.data.round,
            payload=payload or {},
            dedup_key=dedup_key,
        )
        self.data.events_count += 1
        if self._tx_events is not None:
            self._tx_events.append(ev)
        else:
            self._append_event_line(ev)
        return ev

    def set_state(self, new_state: RunState, payload: Optional[dict[str, Any]] = None) -> None:
        cur = self.data.state
        if new_state not in TRANSITIONS[cur]:
            raise RejectedUpdate(f"unauthorised transition {cur.value} -> {new_state.value}")
        self.event(EventKind.PHASE_ENTERED, {"from": cur.value, "to": new_state.value, **(payload or {})},
                   state_after=new_state)
        if cur.value not in self.data.completed_phases and cur not in (RunState.INIT,):
            self.data.completed_phases.append(cur.value)
        self.data.state = new_state

    # -- participants --------------------------------------------------------

    def participant(self, pid: str, role: Role, provider: str, lens_id: Optional[str] = None,
                    model: Optional[str] = None, isolation: str = "shared") -> Participant:
        p = self.data.participants.get(pid)
        if p is None:
            from .ontology import Isolation
            p = Participant(id=pid, role=role, lens_id=lens_id, provider=provider, model_requested=model,
                            isolation=Isolation(isolation))
            self.data.participants[pid] = p
        return p

    # -- validation ------------------------------------------------------------

    def _require(self, cond: bool, msg: str) -> None:
        if not cond:
            raise RejectedUpdate(msg)

    def _check_refs(self, record: BaseModel) -> None:
        d = self.data
        t = type(record).__name__
        if isinstance(record, OptionVersion):
            if record.parent_version_id is not None:
                self._require(record.parent_version_id in d.option_versions, f"unknown parent_version_id {record.parent_version_id}")
            for m in record.merged_from:
                self._require(m in d.option_versions, f"unknown merged_from {m}")
            # claim_ids / assumption_ids are committed right after the version inside the same
            # transaction; the transaction's end check (``verify_integrity``) confirms they exist.
        elif isinstance(record, Claim):
            self._require(record.option_version_id in d.option_versions, f"unknown option_version_id {record.option_version_id}")
            for e in record.evidence_ids:
                self._require(e in d.evidence, f"unknown evidence id {e}")
        elif isinstance(record, Assumption):
            if record.option_version_id is not None:
                self._require(record.option_version_id in d.option_versions, f"unknown option_version_id {record.option_version_id}")
        elif isinstance(record, Evidence):
            if record.challenge_id is not None:
                self._require(record.challenge_id in d.challenges, f"unknown challenge id {record.challenge_id}")
        elif isinstance(record, Challenge):
            self._require(record.target_ref in d.option_versions or record.target_ref in d.claims or record.target_ref == "__all__",
                          f"challenge target_ref {record.target_ref} does not exist")
            for e in record.evidence_ids:
                self._require(e in d.evidence, f"unknown evidence id {e}")
        elif isinstance(record, Response):
            self._require(record.challenge_id in d.challenges, f"unknown challenge id {record.challenge_id}")
            for e in record.evidence_ids:
                self._require(e in d.evidence, f"unknown evidence id {e}")
            if record.new_version_id is not None:
                self._require(record.new_version_id in d.option_versions, f"unknown new_version_id {record.new_version_id}")
        elif isinstance(record, Judgement):
            self._require(record.option_version_id in d.option_versions, f"unknown option_version_id {record.option_version_id}")
            policy = self.current_policy()
            self._require(policy is not None, "no evaluation policy registered")
            crit_ids = {c.id for c in policy.criteria}
            for g in record.gate_results:
                self._require(g.criterion_id in crit_ids, f"unknown gate criterion {g.criterion_id}")
                for e in g.evidence_ids:
                    self._require(e in d.evidence, f"unknown evidence id {e}")
                for a in g.assumption_ids:
                    self._require(a in d.assumptions, f"unknown assumption id {a}")
            for s in record.criterion_scores:
                self._require(s.criterion_id in crit_ids, f"unknown criterion {s.criterion_id}")
                for e in s.evidence_ids:
                    self._require(e in d.evidence, f"unknown evidence id {e}")
                for a in s.assumption_ids:
                    self._require(a in d.assumptions, f"unknown assumption id {a}")
            for sid in record.scenario_scores:
                self._require(sid in {s.id for s in policy.scenarios}, f"unknown scenario {sid}")
        elif isinstance(record, PairwiseComparison):
            self._require(record.first_version_id in d.option_versions and record.second_version_id in d.option_versions,
                          "pairwise comparison references unknown versions")
        elif isinstance(record, Dissent):
            self._require(self.id_exists(record.against_ref) or record.against_ref == "__decision__",
                          f"dissent against unknown ref {record.against_ref}")
        elif isinstance(record, LeaderChallenge):
            self._require(record.leader_version_id in d.option_versions, "unknown leader_version_id")
            self._require(record.strongest_alternative_version_id in d.option_versions,
                          f"unknown strongest_alternative_version_id {record.strongest_alternative_version_id}")
            for c in record.related_challenge_ids:
                self._require(c in d.challenges, f"unknown related challenge {c}")
        elif isinstance(record, EvaluationPolicy):
            self._require(record.brief_id in d.briefs, "policy references unknown brief")
            self._require(len([c for c in record.criteria if c.kind.value == "score"]) >= 1, "policy needs at least one score criterion")
            ids = [c.id for c in record.criteria]
            self._require(len(ids) == len(set(ids)), "duplicate criterion ids")
            record.normalised_weights()
        elif isinstance(record, DecisionBrief):
            if record.supersedes_id is not None:
                self._require(record.supersedes_id in d.briefs, "brief supersedes unknown brief")
        elif isinstance(record, Decision):
            for vid in ([record.recommended_version_id] if record.recommended_version_id else []) + record.alternatives:
                self._require(vid in d.option_versions, f"decision references unknown version {vid}")
            for e in record.decisive_evidence_ids:
                self._require(e in d.evidence, f"unknown evidence id {e}")
        elif isinstance(record, RoundSummary):
            pass
        else:
            raise RejectedUpdate(f"unsupported record type {t}")

    def commit(self, record: BaseModel) -> BaseModel:
        """Validate role permission and references, then store the record."""
        t = type(record).__name__
        self._require(t in RECORD_TYPES, f"unknown record type {t}")
        role = getattr(record, "author_role")
        self._require(t in ROLE_PERMISSIONS.get(role, set()), f"role {role.value} may not author {t}")
        self._require(not self.id_exists(record.id), f"duplicate id {record.id}")
        self._check_refs(record)
        d = self.data
        coll = {
            "DecisionBrief": d.briefs, "EvaluationPolicy": d.policies, "OptionVersion": d.option_versions,
            "Claim": d.claims, "Assumption": d.assumptions, "Evidence": d.evidence, "Challenge": d.challenges,
            "Response": d.responses, "Judgement": d.judgements, "PairwiseComparison": d.comparisons,
            "Dissent": d.dissents, "LeaderChallenge": d.leader_challenges, "RoundSummary": d.round_summaries,
        }
        if t == "Decision":
            d.decision = record  # type: ignore[assignment]
        else:
            coll[t][record.id] = record  # type: ignore[index]
        if isinstance(record, OptionVersion):
            if record.option_id not in d.options_order:
                d.options_order.append(record.option_id)
            if record.parent_version_id:
                self.relate(RelationKind.SUPERSEDES, record.id, record.parent_version_id)
        if isinstance(record, DecisionBrief) and record.supersedes_id:
            self.relate(RelationKind.SUPERSEDES, record.id, record.supersedes_id)
        if isinstance(record, Challenge):
            self.relate(RelationKind.CHALLENGES, record.id, record.target_ref)
        if isinstance(record, Response):
            self.relate(RelationKind.ADDRESSES, record.id, record.challenge_id)
        if isinstance(record, Claim):
            for e in record.evidence_ids:
                self.relate(RelationKind.SUPPORTS, e, record.id)
        if isinstance(record, Evidence):
            if record.verification_status != VerificationStatus.UNAVAILABLE:
                self.bump_snapshot(record.id)
            else:
                record.snapshot_id = d.evidence_snapshot_id
        return record

    def commit_baseline_evidence(self, record: "Evidence") -> "Evidence":
        """Evidence present before the run starts (the user's documents): stored under the initial snapshot without
        bumping it, since no judgement exists yet that it could make non-comparable."""
        self._require(not self.id_exists(record.id), f"duplicate id {record.id}")
        self._require(self.data.round == 0 and not self.data.judgements, "baseline evidence can only be added before any judgement")
        record.snapshot_id = self.data.evidence_snapshot_id
        self.data.evidence[record.id] = record
        return record

    def relate(self, kind: RelationKind, from_id: str, to_id: str) -> None:
        rel = Relation(kind=kind, from_id=from_id, to_id=to_id)
        if rel not in self.data.relations:
            self.data.relations.append(rel)

    def bump_snapshot(self, evidence_id: str) -> None:
        d = self.data
        d.snapshot_counter += 1
        before = d.evidence_snapshot_id
        d.evidence_snapshot_id = f"snap-{d.snapshot_counter}"
        d.evidence[evidence_id].snapshot_id = d.evidence_snapshot_id
        self.event(EventKind.EVIDENCE_SNAPSHOT_CHANGED, {"from": before, "to": d.evidence_snapshot_id, "evidence_id": evidence_id})

    # -- queries ---------------------------------------------------------------

    def current_brief(self) -> Optional[DecisionBrief]:
        if not self.data.briefs:
            return None
        return max(self.data.briefs.values(), key=lambda b: b.version)

    def current_policy(self) -> Optional[EvaluationPolicy]:
        if not self.data.policies:
            return None
        return max(self.data.policies.values(), key=lambda p: (p.brief_version, p.rubric_version))

    def active_versions(self) -> list[OptionVersion]:
        """Latest version per option whose status is active or reinstated."""
        latest: dict[str, OptionVersion] = {}
        for v in self.data.option_versions.values():
            cur = latest.get(v.option_id)
            if cur is None or v.version > cur.version:
                latest[v.option_id] = v
        out = [v for oid, v in latest.items() if v.status.value in ("active", "reinstated")]
        return sorted(out, key=lambda v: (self.data.options_order.index(v.option_id), v.version))

    def latest_version(self, option_id: str) -> Optional[OptionVersion]:
        vs = [v for v in self.data.option_versions.values() if v.option_id == option_id]
        return max(vs, key=lambda v: v.version) if vs else None

    def open_challenges(self) -> list[Challenge]:
        return [c for c in self.data.challenges.values() if c.status.value == "open"]

    def challenges_for_version(self, version_id: str, *, open_only: bool = True) -> list[Challenge]:
        out = []
        for c in self.data.challenges.values():
            if open_only and c.status.value != "open":
                continue
            if c.target_ref == version_id:
                out.append(c)
            elif c.target_ref in self.data.claims and self.data.claims[c.target_ref].option_version_id == version_id:
                out.append(c)
        return out

    def judgements_for(self, version_id: str, key_tuple: Optional[tuple] = None) -> list[Judgement]:
        out = []
        for j in self.data.judgements.values():
            if j.option_version_id != version_id or j.status.value != "complete":
                continue
            if key_tuple is not None and j.comparison_key.as_tuple() != key_tuple:
                continue
            out.append(j)
        return out

    def dedup_lookup(self, key: str) -> Optional[dict[str, Any]]:
        return self.data.dedup.get(key)

    def dedup_record(self, key: str, outcome: dict[str, Any]) -> None:
        self.data.dedup[key] = outcome

    def write_request_file(self, req: PendingRequest) -> Path:
        path = self.run_dir / "requests" / f"{req.request_id}.json"
        public = req.model_dump(mode="json")
        public.pop("alias_map", None)
        public.pop("expect", None)
        public["response_path"] = str(self.run_dir / "responses" / f"{req.request_id}.json")
        path.write_text(json.dumps(public, indent=1))
        return path
