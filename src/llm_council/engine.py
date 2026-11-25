"""The controller: an explicit, resumable state machine.

``Engine.step(submission)`` applies a responder's submission to the pending
request (validate -> commit atomically -> advance) and then runs controller-only
transitions until either a new request is needed (returned to the driver) or a
terminal state is reached. Only this module advances state or commits
deliberation records. Models only propose.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
import json
import random
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

from .budget import estimate_tokens
from .config import CouncilConfig
from .judge import Combined, combine, finalize_judgement, is_close, promotion, rank
from .lenses import LENSES, select_lenses
from .ontology import (
    TERMINAL_STATES,
    Assumption,
    Challenge,
    ChallengeStatus,
    ComparisonKey,
    CouldChange,
    DecisionBrief,
    DecisionKind,
    EvaluationPolicy,
    EventKind,
    Evidence,
    EvidenceSource,
    EvidenceSourceKind,
    Isolation,
    Judgement,
    JudgementStatus,
    OptionStatus,
    OptionVersion,
    PairwiseComparison,
    PromotionOutcome,
    RelationKind,
    Role,
    RunState,
    StopReason,
    VerificationStatus,
)
from .phases import (
    RESPONSE_MODELS,
    Applier,
    BaselineResponse,
    ChallengeReplyResponse,
    CompareResponse,
    FrameResponse,
    GenerateResponse,
    JudgeResponse,
    LeaderChallengeResponse,
    PolicyResponse,
    RespondResponse,
    ReviewResponse,
    VerifyResponse,
    brief_payload,
    challenge_payload,
    evidence_payload,
    lens_instruction,
    option_payload,
    policy_payload,
)
from .prompts import instructions_for
from .report import build_decision, build_round_summary, render_report
from .state import PendingRequest, RejectedUpdate, Store

CONTROLLER = {"author_participant_id": "controller", "author_role": Role.CONTROLLER}


class ReplyMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = "chat"
    model_requested: Optional[str] = None
    model_reported: Optional[str] = None
    tokens_measured: Optional[int] = None
    cost_usd: Optional[float] = None
    isolation: str = "shared"
    substitution: Optional[str] = None
    raw_text: str = ""
    tokens_detail: dict[str, int] = {}
    latency_seconds: Optional[float] = None
    effort: Optional[str] = None


class StepResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str  # request | terminal
    state: str
    request: Optional[PendingRequest] = None
    message: str = ""


class Engine:
    def __init__(self, store: Store, cfg: CouncilConfig):
        self.store = store
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)

    # ------------------------------------------------------------------ public

    def step(self, submission: Optional[dict[str, Any]] = None, meta: Optional[ReplyMeta] = None) -> StepResult:
        d = self.store.data
        if d.pending_request is not None:
            if submission is None:
                return StepResult(status="request", state=d.state.value, request=d.pending_request)
            self._apply_submission(submission, meta or ReplyMeta())
            self.store.save()
            d = self.store.data  # a rollback may have swapped the data object
            if d.pending_request is not None:
                return StepResult(status="request", state=d.state.value, request=d.pending_request)
        elif submission is not None:
            raise RejectedUpdate("no pending request to submit to")
        return self._advance()

    def fail_pending(self, error: str) -> StepResult:
        """A provider could not answer the pending request at all (timeout, route failure with no fallback).
        No model call is charged; the request takes the same failure transition as an exhausted retry."""
        d = self.store.data
        req = d.pending_request
        if req is None:
            return self.result()
        self.store.event(EventKind.REQUEST_FAILED, {"request_id": req.request_id, "kind": req.kind, "error": error[:800], "provider_failure": True})
        d.pending_request = None
        self._on_request_failed(req, error)
        self.store.save()
        return self._advance()

    def result(self) -> StepResult:
        d = self.store.data
        if d.state in TERMINAL_STATES:
            return StepResult(status="terminal", state=d.state.value, message=self._terminal_message())
        if d.pending_request is not None:
            return StepResult(status="request", state=d.state.value, request=d.pending_request)
        return self._advance()

    # ---------------------------------------------------------------- advance

    def _advance(self) -> StepResult:
        d = self.store.data
        guard = 0
        while True:
            guard += 1
            if guard > 500:
                raise RuntimeError("controller loop did not converge")
            if d.state in TERMINAL_STATES:
                self.store.save()
                return StepResult(status="terminal", state=d.state.value, message=self._terminal_message())
            if d.state not in (RunState.INIT, RunState.REPORTING) and self.store.cancel_flag_present():
                d.pending_stop_reason = StopReason.CANCELLED
                d.unfinished_checks.append(f"cancelled while in {d.state.value} (round {d.round})")
                self.store.event(EventKind.STOP_DECIDED, {"reason": "cancelled"})
                self.store.set_state(RunState.REPORTING)
                continue
            # Token, time and cost limits are enforced before every request, not only between rounds.
            hard = d.budget.limit_hit(self.cfg.limits)
            if hard in (StopReason.BUDGET_TOKENS, StopReason.BUDGET_TIME, StopReason.BUDGET_COST) \
                    and d.state not in (RunState.INIT, RunState.FRAMING, RunState.POLICY, RunState.BASELINE, RunState.REPORTING) \
                    and d.pending_stop_reason != hard:
                d.pending_stop_reason = hard
                d.unfinished_checks.append(f"{hard.value} reached while in {d.state.value} (round {d.round}); remaining phase work skipped")
                self.store.event(EventKind.STOP_DECIDED, {"reason": hard.value, "round": d.round, "state": d.state.value})
                self.store.set_state(RunState.REPORTING)
                continue
            handler = getattr(self, f"_on_{d.state.value}")
            req = handler()
            if req is not None:
                d.pending_request = req
                self.store.write_request_file(req)
                self.store.event(EventKind.REQUEST_ISSUED, {"request_id": req.request_id, "kind": req.kind, "role": req.role,
                                                            "participant": req.participant_id, "attempt": req.attempt,
                                                            "provider": req.provider}, dedup_key=req.dedup_key)
                self.store.save()
                return StepResult(status="request", state=d.state.value, request=req)
            self.store.save()

    def _terminal_message(self) -> str:
        d = self.store.data
        if d.state == RunState.COMPLETE:
            return f"RUN COMPLETE ({d.stop_reason.value if d.stop_reason else 'n/a'})"
        if d.state == RunState.FAILED:
            return f"RUN FAILED: {d.failure_reason}"
        return "RUN CANCELLED"

    # ------------------------------------------------------------ comparisons

    def key(self) -> ComparisonKey:
        d = self.store.data
        brief = self.store.current_brief()
        policy = self.store.current_policy()
        return ComparisonKey(
            brief_version=brief.version if brief else 0,
            rubric_version=policy.rubric_version if policy else 0,
            evidence_snapshot_id=d.evidence_snapshot_id,
            judge_config_hash=self.cfg.judge_config_hash(),
        )

    def candidates(self) -> list[OptionVersion]:
        d = self.store.data
        out = self.store.active_versions()
        inc = d.incumbent_version_id
        if inc and inc not in {v.id for v in out}:
            out.append(d.option_versions[inc])
        return out

    def combined(self, version_id: str, key: Optional[ComparisonKey] = None) -> Combined:
        policy = self.store.current_policy()
        k = (key or self.key()).as_tuple()
        js = self.store.judgements_for(version_id, k)
        return combine(js, policy, self.cfg.judge, version_id, k)

    def owner_participant(self, v: OptionVersion) -> str:
        return f"p_strategist_{v.lens_id or 'direct'}"

    # ------------------------------------------------------------ routing

    def _route(self, role: str) -> tuple[str, Optional[str], str]:
        rr = self.cfg.routing.for_role(role)
        provider = rr.provider or self.cfg.routing.default_provider
        if provider == "opencode" and not self.cfg.routing.opencode.enabled:
            provider = "chat" if self.cfg.routing.default_provider == "opencode" else self.cfg.routing.default_provider
        isolation = Isolation.ISOLATED.value if provider == "opencode" else Isolation.SHARED.value
        model = rr.model
        if provider == "opencode" and model is None:
            model = self.cfg.routing.opencode.default_model
        return provider, model, isolation

    def _issue(self, *, kind: str, role: Role, participant_id: str, payload: dict[str, Any], match_hints: dict[str, Any],
               expect: Optional[dict[str, Any]] = None, lens_id: Optional[str] = None, alias_map: Optional[dict[str, str]] = None,
               attempt: int = 1, provider_override: Optional[str] = None, model_override: Optional[str] = None) -> PendingRequest:
        d = self.store.data
        provider, model, isolation = self._route(role.value)
        if provider_override:
            provider, model = provider_override, model_override
            isolation = Isolation.ISOLATED.value if provider == "opencode" else Isolation.SHARED.value
        self.store.participant(participant_id, role, provider, lens_id=lens_id, model=model, isolation=isolation)
        n = d.counters.get("Request", 0) + 1
        d.counters["Request"] = n
        request_id = f"req_{n:04d}"
        dedup_key = hashlib.sha256(f"{d.run_id}|{request_id}|{attempt}".encode()).hexdigest()[:24]
        model_cls = RESPONSE_MODELS[kind]
        from .discussion import discussion_payload, documents_payload
        from .prompts import context_block
        shared: dict[str, Any] = {}
        # What the role may see of the conversation: isolated routes get it blind (no authorship, no models); judges never
        # see the ranking and get summaries only (they score one option from the payload, not from the chatter); roles
        # whose payload already carries the options get those contributions as summaries instead of a second full copy.
        blind = isolation == Isolation.ISOLATED.value
        mode = "summaries" if kind in ("judge", "compare") else None
        in_payload = {"baseline", "generate", "respond"} if any(k in payload for k in ("candidates", "existing_options", "option")) else set()
        disc = discussion_payload(self.store, self.cfg, alias_map=alias_map if blind else None, blind=blind,
                                  hide_scores=kind in ("judge", "compare"), mode=mode, summarize_kinds=in_payload)
        if disc is not None:
            shared["discussion_so_far"] = disc
        docs = documents_payload(self.store, self.cfg)
        if docs is not None:
            shared["documents"] = docs
        has_tools = provider == "chat"
        today = datetime.now().strftime("%Y-%m-%d")
        shared["capabilities"] = {"tools": "claude_code" if has_tools else "none", "can_read_files": has_tools, "today": today,
                                  "language": "answer free text in the language of the question"}
        ctx = context_block(kind, phase=d.state.value, round_no=d.round, max_rounds=self.cfg.limits.max_rounds, has_tools=has_tools,
                            today=today, lens_id=lens_id)
        req = PendingRequest(
            request_id=request_id, attempt=attempt, kind=kind, role=role.value, round=d.round, state=d.state.value,
            participant_id=participant_id, lens_id=lens_id, dedup_key=dedup_key, alias_map=alias_map or {},
            match_hints={"kind": kind, "role": role.value, "round": d.round, "lens": lens_id, **match_hints},
            instructions=instructions_for(kind, lens_instruction(lens_id), has_discussion=disc is not None, has_documents=docs is not None,
                                          context=ctx, repair="previous_reply" in payload),
            payload={"run_id": d.run_id, "round": d.round, "context_isolation": isolation, **payload, **shared},
            response_model=model_cls.__name__, response_schema=model_cls.model_json_schema(),
            isolation=isolation, provider=provider, model=model, expect=expect or {},
        )
        return req

    def _alias_for(self, versions: list[OptionVersion], isolation: str) -> dict[str, str]:
        if isolation != Isolation.ISOLATED.value:
            return {}
        order = list(versions)
        self.rng.shuffle(order)
        return {f"OPT-{i + 1}": v.id for i, v in enumerate(order)}

    # ------------------------------------------------------------ submission

    def _apply_submission(self, submission: dict[str, Any], meta: ReplyMeta) -> None:
        d = self.store.data
        req = d.pending_request
        assert req is not None
        raw = meta.raw_text or json.dumps(submission)
        d.budget.charge(calls=1, tokens_measured=meta.tokens_measured,
                        tokens_estimated=None if meta.tokens_measured is not None else estimate_tokens(raw),
                        cost_usd=meta.cost_usd)
        tokens_this = meta.tokens_measured if meta.tokens_measured is not None else estimate_tokens(raw)
        if meta.provider == "chat" and not meta.model_reported and d.chat_model:
            meta.model_reported = d.chat_model
        p = d.participants.get(req.participant_id)
        if p is not None:
            p.provider = meta.provider or p.provider
            p.model_requested = meta.model_requested or p.model_requested
            p.model_reported = meta.model_reported or p.model_reported
            p.substitution = meta.substitution or p.substitution
            p.isolation = Isolation(meta.isolation) if meta.isolation else p.isolation
            p.calls += 1
            p.tokens += tokens_this
            p.latency_seconds += meta.latency_seconds or 0.0
            p.effort = meta.effort or p.effort
        who = {"provider": meta.provider, "model": meta.model_reported or meta.model_requested,
               "tokens": tokens_this, "tokens_kind": "measured" if meta.tokens_measured is not None else "estimated",
               "tokens_detail": meta.tokens_detail, "latency_seconds": meta.latency_seconds, "effort": meta.effort}
        error: Optional[str] = None
        notes: list[str] = []
        try:
            model_cls = RESPONSE_MODELS[req.kind]
            if not isinstance(submission, dict):
                raise RejectedUpdate("submission must be a JSON object")
            parsed = model_cls.model_validate(submission)
            self.store.begin()
            try:
                notes = self._apply_valid(req, parsed) or []
                self.store.end()
            except Exception:
                self.store.rollback()
                raise
        except ValidationError as e:
            error = "schema validation failed: " + "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:6])
        except (RejectedUpdate, ValueError) as e:
            error = f"rejected: {e}"
        d = self.store.data  # re-fetch: rollback restores the pre-transaction object
        req = d.pending_request
        assert req is not None
        from .discussion import record_contribution
        record_contribution(self.store, req, submission, provider=meta.provider, model=meta.model_reported or meta.model_requested,
                            outcome="committed" if error is None else "rejected", error=error, write_files=self.cfg.discussion.write_transcript,
                            notes=notes)
        if error is None:
            self.store.event(EventKind.RESPONSE_COMMITTED, {"request_id": req.request_id, "kind": req.kind, "attempt": req.attempt, **who,
                                                            **({"partial": notes} if notes else {})},
                             dedup_key=req.dedup_key)
            self.store.dedup_record(req.dedup_key, {"request_id": req.request_id, "outcome": "committed"})
            d.pending_request = None
            return
        self.store.event(EventKind.RESPONSE_REJECTED, {"request_id": req.request_id, "kind": req.kind, "attempt": req.attempt,
                                                       "error": error[:800], **who}, dedup_key=req.dedup_key)
        self.store.dedup_record(req.dedup_key, {"request_id": req.request_id, "outcome": "rejected", "error": error[:300]})
        if req.attempt < self.cfg.retries.max_attempts and d.budget.remaining_calls(self.cfg.limits) > 0:
            retry = self._issue(kind=req.kind, role=Role(req.role), participant_id=req.participant_id,
                                payload={k: v for k, v in req.payload.items() if k not in ("run_id", "round", "context_isolation", "capabilities")}
                                | {"previous_attempt_error": error[:800], "previous_reply": self._previous_reply(meta, submission)},
                                match_hints={k: v for k, v in req.match_hints.items() if k not in ("kind", "role", "round", "lens")},
                                expect=req.expect, lens_id=req.lens_id, alias_map=req.alias_map, attempt=req.attempt + 1)
            d.pending_request = retry
            self.store.write_request_file(retry)
            self.store.event(EventKind.REQUEST_ISSUED, {"request_id": retry.request_id, "kind": retry.kind, "role": retry.role,
                                                        "participant": retry.participant_id, "attempt": retry.attempt,
                                                        "retry_of": req.request_id}, dedup_key=retry.dedup_key)
            return
        fallbacks = self.cfg.routing.validation_fallbacks
        used = int(req.expect.get("_fallback_index", 0))
        if used < len(fallbacks) and d.budget.remaining_calls(self.cfg.limits) > 0:
            target = fallbacks[used]
            provider, model = ("fixture", None) if target == "fixture" else ("opencode", target)
            self.store.event(EventKind.ROUTE_FALLBACK, {"request_id": req.request_id, "from": f"{req.provider}:{req.model or ''}",
                                                        "to": f"{provider}:{model or ''}", "reason": "validation",
                                                        "error": error[:300], "fallback_index": used + 1})
            retry = self._issue(kind=req.kind, role=Role(req.role), participant_id=req.participant_id,
                                payload={k: v for k, v in req.payload.items() if k not in ("run_id", "round", "context_isolation", "capabilities")}
                                | {"previous_attempt_error": error[:800], "previous_reply": self._previous_reply(meta, submission),
                                   "note": f"Previous attempts by another model were rejected by the controller; you are fallback model {used + 1}."},
                                match_hints={k: v for k, v in req.match_hints.items() if k not in ("kind", "role", "round", "lens")},
                                expect={**req.expect, "_fallback_index": used + 1}, lens_id=req.lens_id, alias_map=req.alias_map,
                                attempt=req.attempt + 1, provider_override=provider, model_override=model)
            d.pending_request = retry
            self.store.write_request_file(retry)
            self.store.event(EventKind.REQUEST_ISSUED, {"request_id": retry.request_id, "kind": retry.kind, "role": retry.role,
                                                        "participant": retry.participant_id, "attempt": retry.attempt,
                                                        "retry_of": req.request_id, "provider": retry.provider, "model": retry.model,
                                                        "validation_fallback": used + 1}, dedup_key=retry.dedup_key)
            return
        self.store.event(EventKind.REQUEST_FAILED, {"request_id": req.request_id, "kind": req.kind, "error": error[:800]})
        d.pending_request = None
        self._on_request_failed(req, error)

    @staticmethod
    def _previous_reply(meta: "ReplyMeta", submission: Any, limit: int = 24000) -> str:
        """The rejected reply as the model wrote it (raw text when the provider kept it), capped, for a repair retry."""
        raw = meta.raw_text or ""
        if not raw.strip():
            try:
                raw = json.dumps(submission, ensure_ascii=False, indent=1)
            except (TypeError, ValueError):
                raw = str(submission)
        return raw if len(raw) <= limit else raw[:limit] + "\n… [truncated by the controller]"

    def _apply_valid(self, req: PendingRequest, parsed: BaseModel) -> list[str]:
        d = self.store.data
        ap = Applier(self.store, req)
        cur = d.cursor
        if isinstance(parsed, FrameResponse):
            ap.apply_frame(parsed)
        elif isinstance(parsed, PolicyResponse):
            ap.apply_policy(parsed, materiality=self.cfg.judge.materiality_threshold, margin=self.cfg.judge.promotion_margin,
                            unverified_policy=self.cfg.judge.unverified_gate_policy, judge_hash=self.cfg.judge_config_hash(),
                            weight_overrides=self.cfg.policy.weight_overrides)
        elif isinstance(parsed, BaselineResponse):
            ap.apply_options(parsed.options, parsed.evidence, lens_id="direct", round_no=0)
        elif isinstance(parsed, GenerateResponse):
            if not parsed.options and not parsed.nothing_material:
                raise RejectedUpdate("generate response with no options must set nothing_material=true")
            new = ap.apply_options(parsed.options, parsed.evidence, lens_id=req.lens_id, round_no=d.round)
            self._merge_duplicates(new)
            cur.setdefault("lens_done", []).append(req.lens_id)
        elif isinstance(parsed, ReviewResponse):
            ap.apply_review(parsed, round_no=d.round)
            cur.setdefault("review_done", {}).setdefault(str(d.round), []).append(req.participant_id)
            if parsed.reframe is not None:
                cur["reframe"] = parsed.reframe.model_dump()
        elif isinstance(parsed, VerifyResponse):
            ap.apply_verify(parsed, challenge_id=req.expect["challenge_id"])
            d.budget.verification_calls_used += 1
        elif isinstance(parsed, RespondResponse):
            target = d.option_versions[req.expect["version_id"]]
            ap.apply_respond(parsed, round_no=d.round, allowed_challenge_ids=set(req.expect["challenge_ids"]),
                             target_version=target, lens_id=target.lens_id)
            cur.setdefault("respond_done", {}).setdefault(str(d.round), []).append(req.expect["version_id"])
        elif isinstance(parsed, JudgeResponse):
            policy = self.store.current_policy()
            key = ComparisonKey.model_validate(req.expect["comparison_key"])
            if key.as_tuple() != self.key().as_tuple():
                raise RejectedUpdate("comparison key changed while the judgement was pending; rescoring required")
            # judge-stated assumptions: declared ones first, then any asm_ id the judge cites without declaring
            declared: dict[str, str] = {}
            for a in parsed.assumptions:
                aid = ap._assign_id("Assumption", a.id) if not (a.id and a.id in d.assumptions) else a.id
                if aid not in d.assumptions:
                    self.store.commit(Assumption(id=aid, text=a.text, option_version_id=req.expect["version_id"], influential=a.influential,
                                                 if_false_effect=a.if_false_effect, author_participant_id=req.participant_id, author_role=Role.JUDGE))
                if a.id:
                    declared[a.id] = aid
            cited = {x for g in parsed.gate_results for x in g.evidence_ids + g.assumption_ids} | \
                    {x for sc in parsed.criterion_scores for x in sc.evidence_ids + sc.assumption_ids}
            for ref in sorted(cited):
                ref2 = declared.get(ref, ap.remap.get(ref, ref))
                if ref2.startswith("asm_") and ref2 not in d.assumptions and ref2 not in d.evidence and ref2 not in d.claims:
                    # The judge states an assumption by name only: record it as a judge-stated assumption so the
                    # judgement stays auditable instead of being rejected for an unknown id.
                    self.store.commit(Assumption(id=ref2, text=f"Judge-stated assumption '{ref2}' (named in the judgement, no text supplied)",
                                                 option_version_id=req.expect["version_id"], influential=False,
                                                 author_participant_id=req.participant_id, author_role=Role.JUDGE))
            def _fix(ids: list[str]) -> list[str]:
                return [declared.get(x, ap.remap.get(x, x)) for x in ids]
            gates = [g.model_copy(update=self._normalise_citations(_fix(g.evidence_ids), _fix(g.assumption_ids), req.expect["version_id"]))
                     for g in parsed.gate_results]
            scores = [s.model_copy(update=self._normalise_citations(_fix(s.evidence_ids), _fix(s.assumption_ids), req.expect["version_id"]))
                      for s in parsed.criterion_scores]
            j = Judgement(
                id=ap._assign_id("Judgement", None), option_version_id=req.expect["version_id"], comparison_key=key,
                participant_id=req.participant_id, gate_results=gates, criterion_scores=scores,
                scenario_scores=parsed.scenario_scores, status=JudgementStatus.COMPLETE, round=d.round,
                author_participant_id=req.participant_id, author_role=Role.JUDGE,
            )
            j = finalize_judgement(j, policy, self.cfg.judge)
            self.store.commit(j)
        elif isinstance(parsed, CompareResponse):
            key = ComparisonKey.model_validate(req.expect["comparison_key"])
            cmp = PairwiseComparison(
                id=ap._assign_id("PairwiseComparison", None), first_version_id=req.expect["first"],
                second_version_id=req.expect["second"], preferred=parsed.preferred, rationale=parsed.rationale,
                comparison_key=key, round=d.round, author_participant_id=req.participant_id, author_role=Role.JUDGE,
            )
            self.store.commit(cmp)
            slot = req.expect["slot"]
            pref_id = {"first": req.expect["first"], "second": req.expect["second"], "tie": "tie"}[parsed.preferred]
            cur["compare"][slot] = pref_id
        elif isinstance(parsed, LeaderChallengeResponse):
            lc = ap.apply_leader_challenge(parsed, leader_version_id=req.expect["leader_version_id"], round_no=d.round)
            d.budget.leader_challenges_used += 1
            cur["leader_challenge_id"] = lc.id
        elif isinstance(parsed, ChallengeReplyResponse):
            ap.apply_challenge_reply(parsed, leader_challenge_id=req.expect["leader_challenge_id"], round_no=d.round)
            cur["challenge_reply_done"] = True
        else:
            raise RejectedUpdate(f"unsupported response type {type(parsed).__name__}")
        return ap.notes

    def _normalise_citations(self, evidence_ids: list[str], assumption_ids: list[str], version_id: str) -> dict[str, list[str]]:
        """Judges frequently cite a claim id where evidence is expected. A claim is not evidence, so the
        citation is replaced by the claim's own evidence ids; a claim without evidence is treated as the
        option's inference and the option's assumptions are cited instead. Unknown ids are left for the
        store to reject."""
        d = self.store.data
        ev: list[str] = []
        asm: list[str] = list(assumption_ids)
        for ref in evidence_ids:
            if ref in d.claims:
                claim = d.claims[ref]
                if claim.evidence_ids:
                    ev.extend(claim.evidence_ids)
                else:
                    ov = d.option_versions.get(claim.option_version_id)
                    asm.extend(ov.assumption_ids if ov else [])
            elif ref in d.assumptions:
                asm.append(ref)
            elif ref in d.option_versions:
                # citing the option itself: use its claims' evidence and its assumptions
                ov = d.option_versions[ref]
                for cid in ov.claim_ids:
                    ev.extend(d.claims[cid].evidence_ids if cid in d.claims else [])
                asm.extend(ov.assumption_ids)
            else:
                ev.append(ref)
        return {"evidence_ids": list(dict.fromkeys(ev)), "assumption_ids": list(dict.fromkeys(asm))}

    def _on_request_failed(self, req: PendingRequest, error: str) -> None:
        d = self.store.data
        cur = d.cursor
        kind = req.kind
        if kind in ("frame", "policy", "baseline"):
            d.failure_reason = f"{kind} request failed after {req.attempt} attempts: {error[:300]}"
            d.stop_reason = StopReason.FAILED
            self.store.event(EventKind.RUN_FINISHED, {"state": "FAILED", "reason": d.failure_reason})
            self.store.set_state(RunState.FAILED)
        elif kind == "generate":
            cur.setdefault("lens_done", []).append(req.lens_id)
            d.unfinished_checks.append(f"lens {req.lens_id} produced no valid options ({error[:120]})")
        elif kind == "review":
            cur.setdefault("review_done", {}).setdefault(str(d.round), []).append(req.participant_id)
            d.unfinished_checks.append(f"reviewer {req.participant_id} failed in round {d.round}")
        elif kind == "verify":
            ch = d.challenges[req.expect["challenge_id"]]
            ev = Evidence(id=self.store.new_id("Evidence"), statement=f"Verification of {ch.id} failed: {error[:200]}",
                          source=EvidenceSource(kind=EvidenceSourceKind.COMPUTATION, ref="controller"),
                          verification_status=VerificationStatus.UNAVAILABLE, challenge_id=ch.id, **CONTROLLER)
            self.store.commit(ev)
            ch.verification_attempted = True
            d.budget.verification_calls_used += 1
        elif kind == "respond":
            cur.setdefault("respond_done", {}).setdefault(str(d.round), []).append(req.expect["version_id"])
            d.unfinished_checks.append(f"owner of {req.expect['version_id']} did not respond validly in round {d.round}")
        elif kind == "judge":
            key = ComparisonKey.model_validate(req.expect["comparison_key"])
            j = Judgement(id=self.store.new_id("Judgement"), option_version_id=req.expect["version_id"], comparison_key=key,
                          participant_id=req.participant_id, status=JudgementStatus.MISSING, round=d.round, **CONTROLLER)
            self.store.commit(j)
            d.unfinished_checks.append(f"judgement missing for {req.expect['version_id']} under {key.evidence_snapshot_id}")
        elif kind == "compare":
            cur["compare"][req.expect["slot"]] = "failed"
        elif kind == "challenge":
            cur["challenge_skipped"] = True
            d.unfinished_checks.append("leader challenge produced no valid record")
        elif kind == "challenge_reply":
            cur["challenge_reply_done"] = True
            d.unfinished_checks.append("leader owner did not reply validly to the leader challenge")

    # ------------------------------------------------------------ handlers

    def _on_INIT(self) -> Optional[PendingRequest]:
        self.store.event(EventKind.RUN_CREATED, {"question": self.store.data.question})
        self.store.set_state(RunState.FRAMING)
        return None

    def _on_FRAMING(self) -> Optional[PendingRequest]:
        d = self.store.data
        brief = self.store.current_brief()
        if brief is None:
            return self._issue(kind="frame", role=Role.FRAMER, participant_id="p_framer",
                               payload={"question": d.question}, match_hints={})
        self.store.set_state(RunState.POLICY)
        return None

    def _on_POLICY(self) -> Optional[PendingRequest]:
        brief = self.store.current_brief()
        policy = self.store.current_policy()
        if policy is not None and policy.brief_version == brief.version:
            self.store.set_state(RunState.BASELINE)
            return None
        return self._issue(kind="policy", role=Role.POLICY_SETTER, participant_id="p_policy_setter",
                           payload={"brief": brief_payload(self.store), "evidence": evidence_payload(self.store),
                                    "judge_contract": {"score_range": "0-10 integers", "weights": "relative, normalised by controller",
                                                       "gate_outcomes": ["pass", "fail", "unverified"],
                                                       "materiality_threshold": self.cfg.judge.materiality_threshold}},
                           match_hints={})

    def _on_BASELINE(self) -> Optional[PendingRequest]:
        d = self.store.data
        if any(v.round == 0 for v in d.option_versions.values()):
            d.round = 0
            self.store.set_state(RunState.JUDGING)
            return None
        brief = self.store.current_brief()
        return self._issue(kind="baseline", role=Role.STRATEGIST, participant_id="p_strategist_direct", lens_id="direct",
                           payload={"brief": brief_payload(self.store), "policy": policy_payload(self.store),
                                    "evidence": evidence_payload(self.store),
                                    "user_named_options": brief.user_named_options if brief else [],
                                    "required": "one option per user-named option plus the status quo and the direct answer"},
                           match_hints={})

    def _on_GENERATING(self) -> Optional[PendingRequest]:
        d = self.store.data
        if not d.selected_lenses:
            brief = self.store.current_brief()
            lc = self.cfg.lenses
            d.selected_lenses = select_lenses(brief, mode=lc.selection, explicit=lc.explicit, min_n=lc.min, max_n=lc.max,
                                              include_staged=lc.always_include_staged, include_information=lc.always_include_information_option)
        done = d.cursor.setdefault("lens_done", [])
        remaining = [l for l in d.selected_lenses if l not in done]
        if remaining:
            if d.budget.can_afford(self.cfg.limits, 1):
                lens = remaining[0]
                return self._issue(kind="generate", role=Role.STRATEGIST, participant_id=f"p_strategist_{lens}", lens_id=lens,
                                   payload={"brief": brief_payload(self.store), "policy": policy_payload(self.store),
                                            "evidence": evidence_payload(self.store),
                                            "existing_options": [option_payload(self.store, v) for v in self.candidates()],
                                            "lens": {"id": lens, "name": LENSES[lens].name, "method": LENSES[lens].method,
                                                     "observer_only": LENSES[lens].observer_only}},
                                   match_hints={})
            for l in remaining:
                done.append(l)
                d.unfinished_checks.append(f"lens {l} skipped: call budget exhausted")
        if len(self.candidates()) < 2:
            d.failure_reason = "fewer than two option versions after generation"
            d.stop_reason = StopReason.FAILED
            self.store.event(EventKind.RUN_FINISHED, {"state": "FAILED", "reason": d.failure_reason})
            self.store.set_state(RunState.FAILED)
            return None
        self.store.set_state(RunState.REVIEWING)
        return None

    def _on_REVIEWING(self) -> Optional[PendingRequest]:
        d = self.store.data
        panel = self.cfg.review.panel_size
        if panel == 0:
            self.store.set_state(RunState.JUDGING)
            return None
        done = d.cursor.setdefault("review_done", {}).setdefault(str(d.round), [])
        if len(done) < panel:
            if d.budget.can_afford(self.cfg.limits, 1):
                idx = len(done) + 1
                provider, _, isolation = self._route(Role.REVIEWER.value)
                cands = self.candidates()
                alias = self._alias_for(cands, isolation)
                inv = {v: k for k, v in alias.items()}
                withhold = isolation == Isolation.ISOLATED.value
                open_ch = [challenge_payload(self.store, c, alias) for c in self.store.open_challenges()]
                payload = {
                    "brief": brief_payload(self.store), "policy": policy_payload(self.store),
                    "evidence": evidence_payload(self.store),
                    "candidates": [option_payload(self.store, v, label=inv.get(v.id), withhold_author=withhold) for v in cands],
                    "open_challenges": open_ch,
                    "note": ("Authorship and prior rankings are withheld; candidates are pseudonymised." if withhold else
                             "Shared context: no blind review is claimed. Prior rankings are not included in this payload."),
                    "already_reviewed_this_round": len(done),
                    "valid_target_ids": [inv.get(v.id, v.id) for v in cands]
                    + [c for v in cands for c in v.claim_ids if c in d.claims]
                    + [a for v in cands for a in v.assumption_ids if a in d.assumptions] + ["__all__"],
                }
                return self._issue(kind="review", role=Role.REVIEWER, participant_id=f"p_reviewer_{idx}", payload=payload,
                                   match_hints={"reviewer": idx}, alias_map=alias)
            d.unfinished_checks.append(f"review panel incomplete in round {d.round}: call budget exhausted")
            while len(done) < panel:
                done.append("skipped")
        if self._verification_queue() and d.budget.verification_calls_used < self.cfg.limits.max_verification_calls:
            self.store.set_state(RunState.VERIFYING)
        else:
            self.store.set_state(RunState.RESPONDING)
        return None

    def _verification_queue(self) -> list[Challenge]:
        return [c for c in self.store.open_challenges() if c.requires_verification and not c.verification_attempted]

    def _on_VERIFYING(self) -> Optional[PendingRequest]:
        d = self.store.data
        queue = self._verification_queue()
        if queue and d.budget.verification_calls_used < self.cfg.limits.max_verification_calls and d.budget.can_afford(self.cfg.limits, 1):
            c = queue[0]
            target = None
            if c.target_ref in d.option_versions:
                target = option_payload(self.store, d.option_versions[c.target_ref])
            elif c.target_ref in d.claims:
                target = d.claims[c.target_ref].model_dump(mode="json")
            return self._issue(kind="verify", role=Role.VERIFIER, participant_id="p_verifier",
                               payload={"challenge": challenge_payload(self.store, c, {}), "target": target,
                                        "evidence": evidence_payload(self.store), "brief": brief_payload(self.store)},
                               match_hints={"challenge_id": c.id}, expect={"challenge_id": c.id})
        for c in queue:
            d.unfinished_checks.append(f"verification pending for {c.id} (verification budget or call budget exhausted)")
        self.store.set_state(RunState.RESPONDING)
        return None

    def _last_response(self, ch: Challenge):
        rs = [r for r in self.store.data.responses.values() if r.challenge_id == ch.id]
        return max(rs, key=lambda r: r.id) if rs else None

    def _new_evidence_since(self, ch: Challenge, resp) -> bool:
        """True when usable evidence linked to the challenge was committed in a later round than the
        last response (verification precedes responding within a round)."""
        d = self.store.data
        return any(e.challenge_id == ch.id and e.round > resp.round and e.verification_status.value != "unavailable"
                   for e in d.evidence.values())

    def challenge_awaits_owner(self, ch: Challenge) -> bool:
        """An open challenge needs an owner response when it has none yet, when new evidence arrived
        after the last response, or when the last response was a revision or a verification request
        (the owner may still rebut or revise again). A concession or an evidence-less rebuttal with
        nothing new since is settled: the position is recorded and re-asking cannot change it."""
        last = self._last_response(ch)
        if last is None:
            return True
        if last.kind.value in ("revise", "request_verification"):
            return True
        return self._new_evidence_since(ch, last)

    def _targets_with_open_challenges(self) -> list[tuple[OptionVersion, list[Challenge]]]:
        out = []
        for v in self.candidates():
            chs = [c for c in self.store.challenges_for_version(v.id) if c.target_ref != "__all__" and self.challenge_awaits_owner(c)]
            if chs:
                out.append((v, chs))
        return out

    def _on_RESPONDING(self) -> Optional[PendingRequest]:
        d = self.store.data
        done = d.cursor.setdefault("respond_done", {}).setdefault(str(d.round), [])
        pending = [(v, chs) for v, chs in self._targets_with_open_challenges() if v.id not in done]
        if pending:
            if d.budget.can_afford(self.cfg.limits, 1):
                v, chs = pending[0]
                return self._issue(kind="respond", role=Role.STRATEGIST, participant_id=self.owner_participant(v), lens_id=v.lens_id,
                                   payload={"brief": brief_payload(self.store), "policy": policy_payload(self.store),
                                            "evidence": evidence_payload(self.store), "option": option_payload(self.store, v),
                                            "open_challenges": [challenge_payload(self.store, c, {}) for c in chs]},
                                   match_hints={"option_id": v.option_id, "version_id": v.id},
                                   expect={"version_id": v.id, "challenge_ids": [c.id for c in chs]})
            for v, _ in pending:
                done.append(v.id)
                d.unfinished_checks.append(f"owner of {v.id} could not respond in round {d.round}: call budget exhausted")
        self.store.set_state(RunState.REVISING)
        return None

    def _on_REVISING(self) -> Optional[PendingRequest]:
        self.store.set_state(RunState.JUDGING)
        return None

    def _judge_queue(self, key: ComparisonKey) -> list[tuple[OptionVersion, int]]:
        d = self.store.data
        cands = self.candidates()
        if self.cfg.judge.rescore_scope == "incumbent_and_new":
            cands = [v for v in cands if v.id == d.incumbent_version_id or v.round == d.round or not self.store.judgements_for(v.id)]
        out = []
        kt = key.as_tuple()
        for v in cands:
            for j in range(1, self.cfg.judge.jury_size + 1):
                pid = f"p_judge_{j}"
                existing = [x for x in d.judgements.values() if x.option_version_id == v.id and x.participant_id == pid
                            and x.comparison_key.as_tuple() == kt]
                if not existing:
                    out.append((v, j))
        return out

    def _on_JUDGING(self) -> Optional[PendingRequest]:
        d = self.store.data
        cur = d.cursor
        self._maybe_reframe()
        key = self.key()
        queue = self._judge_queue(key)
        if queue:
            if d.budget.can_afford(self.cfg.limits, 1) or d.round == 0:
                v, j = queue[0]
                policy = self.store.current_policy()
                return self._issue(kind="judge", role=Role.JUDGE, participant_id=f"p_judge_{j}",
                                   payload={"brief": brief_payload(self.store), "policy": policy_payload(self.store),
                                            "evidence": evidence_payload(self.store), "option": option_payload(self.store, v),
                                            "challenges_on_option": [challenge_payload(self.store, c, {}) for c in self.store.challenges_for_version(v.id, open_only=False)],
                                            "comparison_key": key.model_dump(mode="json"),
                                            "required_gate_ids": [c.id for c in policy.gate_criteria],
                                            "required_score_ids": [c.id for c in policy.score_criteria]},
                                   match_hints={"version_id": v.id, "snapshot": key.evidence_snapshot_id, "judge": j},
                                   expect={"version_id": v.id, "comparison_key": key.model_dump(mode="json")})
            for v, j in queue:
                d.unfinished_checks.append(f"{v.id} not (re)scored under {key.evidence_snapshot_id} by p_judge_{j}: call budget exhausted")
                self.store.event(EventKind.RESCORE_REQUIRED, {"version_id": v.id, "snapshot": key.evidence_snapshot_id, "status": "skipped_budget"})
            cur["judge_budget_skipped"] = True
        # Compare / tiebreak
        cmp = cur.get("compare")
        if cmp and cmp.get("round") == d.round and (cmp.get("a") is None or cmp.get("b") is None):
            req = self._compare_request(cmp, key)
            if req is not None:
                return req
        self._adjudicate(key)
        return self._decide_continue()

    def _compare_request(self, cmp: dict[str, Any], key: ComparisonKey) -> Optional[PendingRequest]:
        d = self.store.data
        inc, chal = cmp["inc"], cmp["chal"]
        slot = "a" if cmp.get("a") is None else "b"
        first, second = (inc, chal) if slot == "a" else (chal, inc)
        if not d.budget.can_afford(self.cfg.limits, 1):
            cmp[slot] = "failed"
            if cmp.get("a") is None or cmp.get("b") is None:
                return self._compare_request(cmp, key)
            return None
        provider, _, isolation = self._route(Role.JUDGE.value)
        withhold = isolation == Isolation.ISOLATED.value
        return self._issue(kind="compare", role=Role.JUDGE, participant_id="p_judge_1",
                           payload={"brief": brief_payload(self.store), "policy": policy_payload(self.store),
                                    "evidence": evidence_payload(self.store),
                                    "first": option_payload(self.store, d.option_versions[first], label="first", withhold_author=withhold),
                                    "second": option_payload(self.store, d.option_versions[second], label="second", withhold_author=withhold)},
                           match_hints={"slot": slot, "first": first, "second": second},
                           expect={"slot": slot, "first": first, "second": second, "comparison_key": key.model_dump(mode="json")})

    def _maybe_reframe(self) -> None:
        d = self.store.data
        rf = d.cursor.get("reframe")
        if not rf:
            return
        d.cursor["reframe"] = None
        if d.budget.reframes_used >= self.cfg.limits.max_reframes:
            d.unfinished_checks.append("reframe proposed but max_reframes reached")
            return
        brief = self.store.current_brief()
        policy = self.store.current_policy()
        new_brief = brief.model_copy(update={
            "id": self.store.new_id("DecisionBrief"), "version": brief.version + 1, "decision_statement": rf["decision_statement"],
            "supersedes_id": brief.id, "inferred_assumptions": brief.inferred_assumptions + [f"reframe: {rf['reason']}"],
            **CONTROLLER,
        })
        self.store.commit(new_brief)
        new_policy = policy.model_copy(update={"id": self.store.new_id("EvaluationPolicy"), "brief_id": new_brief.id,
                                               "brief_version": new_brief.version, "rubric_version": 1, **CONTROLLER})
        self.store.commit(new_policy)
        d.budget.reframes_used += 1
        self.store.event(EventKind.RESCORE_REQUIRED, {"reason": "reframe", "brief_version": new_brief.version})

    def _adjudicate(self, key: ComparisonKey) -> None:
        d = self.store.data
        cur = d.cursor
        cands = self.candidates()
        combs = {v.id: self.combined(v.id, key) for v in cands}
        prior_incumbent = d.incumbent_version_id
        outcome: PromotionOutcome
        note = ""
        challenger_id: Optional[str] = None
        pairwise: Optional[str] = None
        cmp = cur.get("compare")
        if cmp and cmp.get("round") == d.round and cmp.get("a") is not None and cmp.get("b") is not None:
            a, b = cmp["a"], cmp["b"]
            if a == "failed" or b == "failed":
                pairwise = "disagree"
            elif a == cmp["chal"] and b == cmp["chal"]:
                pairwise = "challenger"
            elif a == cmp["inc"] and b == cmp["inc"]:
                pairwise = "incumbent"
            elif a == "tie" and b == "tie":
                pairwise = "incumbent"
            else:
                pairwise = "disagree"
            cur["compare"] = None
        if prior_incumbent is None:
            ranking = rank(list(combs.values()))
            if ranking:
                d.incumbent_version_id = ranking[0][0]
                d.incumbent_history.append({"round": d.round, "version_id": ranking[0][0], "outcome": "baseline"})
                self.store.event(EventKind.INCUMBENT_CHANGED, {"from": None, "to": ranking[0][0], "outcome": "baseline"})
                outcome = PromotionOutcome.BASELINE
                note = "round-zero incumbent is the best eligible baseline option"
            else:
                outcome = PromotionOutcome.NO_CHALLENGER
                note = "no eligible option after round zero"
        else:
            inc = combs.get(prior_incumbent) or self.combined(prior_incumbent, key)
            others = [c for vid, c in combs.items() if vid != prior_incumbent and c.status == "complete" and c.eligible]
            others.sort(key=lambda c: (-c.aggregate, c.version_id))
            chal = others[0] if others else None
            challenger_id = chal.version_id if chal else None
            if inc.status == "complete" and not inc.eligible:
                outcome, note = PromotionOutcome.INCUMBENT_INELIGIBLE, f"incumbent failed gates {inc.failed_gates}"
                if chal is not None:
                    d.incumbent_version_id = chal.version_id
                    d.incumbent_history.append({"round": d.round, "version_id": chal.version_id, "outcome": outcome.value})
                    self.store.event(EventKind.INCUMBENT_CHANGED, {"from": prior_incumbent, "to": chal.version_id, "outcome": outcome.value})
                else:
                    d.incumbent_version_id = None
            else:
                outcome, note = promotion(inc, chal, self.cfg.judge, pairwise=pairwise)
                if outcome == PromotionOutcome.INCONCLUSIVE and pairwise is None and self.cfg.judge.pairwise_tiebreak \
                        and chal is not None and is_close(inc, chal, self.cfg.judge) and d.budget.can_afford(self.cfg.limits, 2) \
                        and not cur.get("compare_done_round") == d.round:
                    cur["compare"] = {"round": d.round, "inc": prior_incumbent, "chal": chal.version_id, "a": None, "b": None}
                    cur["compare_done_round"] = d.round
                    return self._on_JUDGING_resume()
                if outcome == PromotionOutcome.PROMOTED:
                    d.incumbent_version_id = chal.version_id
                    d.incumbent_history.append({"round": d.round, "version_id": chal.version_id, "outcome": outcome.value})
                    self.store.event(EventKind.INCUMBENT_CHANGED, {"from": prior_incumbent, "to": chal.version_id, "outcome": outcome.value, "note": note})
        self._resolve_by_revision(key)
        if cur.get("final_rescore"):
            note = (note + "; " if note else "") + "final rescore under the evidence added after the leader challenge"
        summary = build_round_summary(self, key=key, outcome=outcome, note=note, prior_incumbent=prior_incumbent,
                                      challenger_id=challenger_id, combs=combs)
        self.store.commit(summary)
        d.stable_streak = summary.stable_streak
        self.store.event(EventKind.ROUND_SUMMARISED, {"round": d.round, "outcome": outcome.value, "incumbent": d.incumbent_version_id,
                                                      "stable_streak": d.stable_streak, "comparable": summary.comparable})
        cur["adjudicated_round"] = d.round

    def _on_JUDGING_resume(self) -> None:
        # Marker: the caller (_on_JUDGING) will re-enter and issue compare requests on the next loop iteration.
        self.store.data.cursor["needs_compare"] = True

    def _resolve_by_revision(self, key: ComparisonKey) -> None:
        """A revision resolves a challenge for the *new* version once that version is judged.
        The challenged version keeps the challenge open while it is still a candidate (e.g. the
        incumbent); once it is superseded and out of contention the challenge closes as superseded."""
        d = self.store.data
        cand_ids = {v.id for v in self.candidates()}
        for ch in self.store.open_challenges():
            for r in d.responses.values():
                if r.challenge_id == ch.id and r.kind.value == "revise" and r.new_version_id:
                    comb = self.combined(r.new_version_id, key)
                    if comb.status != "complete":
                        continue
                    target_version = ch.target_ref if ch.target_ref in d.option_versions else \
                        (d.claims[ch.target_ref].option_version_id if ch.target_ref in d.claims else None)
                    if r.new_version_id == d.incumbent_version_id:
                        ch.status = ChallengeStatus.RESOLVED
                        ch.resolution_note = f"resolved by promoted revision {r.new_version_id}"
                        self.store.event(EventKind.CHALLENGE_RESOLVED, {"challenge_id": ch.id, "by": r.id, "how": "revision_promoted"})
                    elif target_version is not None and target_version not in cand_ids:
                        ch.status = ChallengeStatus.RESOLVED
                        ch.resolution_note = f"target {target_version} superseded by judged revision {r.new_version_id}; no longer a candidate"
                        self.store.event(EventKind.CHALLENGE_RESOLVED, {"challenge_id": ch.id, "by": r.id, "how": "target_superseded"})

    def blocking_challenges(self) -> list[Challenge]:
        """Open challenges with a credible path to changing ranking or action."""
        d = self.store.data
        out = []
        for c in self.store.open_challenges():
            if c.could_change not in (CouldChange.RANKING, CouldChange.ACTION):
                continue
            if c.target_ref == "__all__":
                continue
            # does it concern a candidate?
            cand_ids = {v.id for v in self.candidates()}
            tgt = c.target_ref if c.target_ref in d.option_versions else (d.claims[c.target_ref].option_version_id if c.target_ref in d.claims else None)
            if tgt not in cand_ids:
                continue
            if c.requires_verification:
                attempted = c.verification_attempted
                has_qualifying = any(e.challenge_id == c.id and e.verification_status.value in ("verified", "user_supplied") for e in d.evidence.values())
                if attempted and not has_qualifying:
                    continue  # verification unavailable: no credible path
                if not attempted and d.budget.verification_calls_used >= self.cfg.limits.max_verification_calls:
                    continue
            last = self._last_response(c)
            if last is not None and last.kind.value in ("concede", "rebut") and not self._new_evidence_since(c, last):
                # The owner has taken a final position and nothing new can arrive without verification:
                # the objection stays open and is reported, but further rounds cannot resolve it.
                continue
            out.append(c)
        return out

    def _decide_continue(self) -> Optional[PendingRequest]:
        d = self.store.data
        cur = d.cursor
        if cur.pop("needs_compare", False):
            return None  # loop re-enters _on_JUDGING to issue compare requests
        if cur.pop("final_rescore", False):
            # Rescoring after the leader challenge: the stop reason was already decided.
            self.store.set_state(RunState.REPORTING)
            return None
        brief = self.store.current_brief()
        lim = self.cfg.limits
        if d.round == 0:
            if brief.decision_kind == DecisionKind.TRIVIAL:
                d.pending_stop_reason = StopReason.TRIVIAL_QUESTION
                self.store.event(EventKind.STOP_DECIDED, {"reason": "trivial_question"})
                self.store.set_state(RunState.REPORTING)
                return None
            d.round = 1
            self.store.set_state(RunState.GENERATING)
            return None
        last = list(d.round_summaries.values())[-1] if d.round_summaries else None
        stop: Optional[StopReason] = d.budget.limit_hit(lim)
        blocking = self.blocking_challenges()
        if stop is None and d.round >= lim.min_rounds and d.stable_streak >= lim.stable_rounds_required and not blocking:
            stop = StopReason.STABLE
        elif stop is None and d.round >= lim.min_rounds and last is not None and not last.productive and not blocking:
            stop = StopReason.NO_PRODUCTIVE_FOLLOW_UP
        elif stop is None and d.round >= lim.max_rounds:
            stop = StopReason.MAX_ROUNDS
        elif stop is None and not d.budget.can_afford(lim, self.cfg.review.panel_size + 1):
            stop = StopReason.BUDGET_CALLS
        if stop is None:
            d.round += 1
            self.store.set_state(RunState.REVIEWING)
            return None
        d.pending_stop_reason = stop
        self.store.event(EventKind.STOP_DECIDED, {"reason": stop.value, "round": d.round, "stable_streak": d.stable_streak,
                                                  "blocking_challenges": [c.id for c in blocking]})
        if stop == StopReason.BUDGET_CALLS:
            d.unfinished_checks.append(f"call budget reached after round {d.round}; deliberation stopped early")
        can_challenge = (d.budget.leader_challenges_used < lim.max_leader_challenges and d.incumbent_version_id is not None
                         and d.budget.remaining_calls(lim) >= 2 and not cur.get("challenge_skipped"))
        if can_challenge:
            cur.pop("leader_challenge_id", None)
            cur.pop("challenge_reply_done", None)
            self.store.set_state(RunState.CHALLENGING)
        else:
            if d.budget.leader_challenges_used < lim.max_leader_challenges and d.incumbent_version_id is not None:
                d.unfinished_checks.append("leader challenge not run (call budget)")
            self.store.set_state(RunState.REPORTING)
        return None

    def _on_CHALLENGING(self) -> Optional[PendingRequest]:
        d = self.store.data
        cur = d.cursor
        lim = self.cfg.limits
        lc_id = cur.get("leader_challenge_id")
        leader = d.incumbent_version_id
        if cur.get("challenge_skipped"):
            self.store.set_state(RunState.REPORTING)
            return None
        if lc_id is None:
            if leader is None or d.budget.remaining_calls(lim) < 2:
                d.unfinished_checks.append("leader challenge not run")
                self.store.set_state(RunState.REPORTING)
                return None
            lv = d.option_versions[leader]
            alts = [v for v in self.candidates() if v.id != leader]
            ranking = [(vid, agg) for vid, agg in rank([self.combined(v.id) for v in self.candidates()])]
            return self._issue(kind="challenge", role=Role.CHALLENGER, participant_id="p_challenger",
                               payload={"brief": brief_payload(self.store), "policy": policy_payload(self.store),
                                        "evidence": evidence_payload(self.store), "leader": option_payload(self.store, lv),
                                        "alternatives": [option_payload(self.store, v) for v in alts],
                                        "ranking": ranking,
                                        "open_challenges": [challenge_payload(self.store, c, {}) for c in self.store.open_challenges()],
                                        "resolved_challenges": [challenge_payload(self.store, c, {}) for c in d.challenges.values() if c.status.value == "resolved"]},
                               match_hints={"leader_version_id": leader}, expect={"leader_version_id": leader})
        lc = d.leader_challenges[lc_id]
        if lc.response_id is None and not cur.get("challenge_reply_done"):
            if d.budget.remaining_calls(lim) < 1:
                d.unfinished_checks.append("leader owner reply not run (call budget)")
                cur["challenge_reply_done"] = True
            else:
                lv = d.option_versions[lc.leader_version_id]
                return self._issue(kind="challenge_reply", role=Role.STRATEGIST, participant_id=self.owner_participant(lv), lens_id=lv.lens_id,
                                   payload={"brief": brief_payload(self.store), "evidence": evidence_payload(self.store),
                                            "leader": option_payload(self.store, lv),
                                            "leader_challenge": lc.model_dump(mode="json", exclude={"created_at", "author_participant_id", "author_role", "protocol_version"}),
                                            "strongest_alternative": option_payload(self.store, d.option_versions[lc.strongest_alternative_version_id])},
                                   match_hints={"leader_challenge_id": lc.id}, expect={"leader_challenge_id": lc.id})
        unresolved = lc.status == ChallengeStatus.OPEN
        if unresolved and lc.could_alter_outcome and d.budget.reopens_used < lim.max_reopens and d.round < lim.max_rounds \
                and d.budget.can_afford(lim, self.cfg.review.panel_size + 1):
            d.budget.reopens_used += 1
            d.pending_stop_reason = None
            d.round += 1
            self.store.event(EventKind.REOPENED, {"leader_challenge_id": lc.id, "round": d.round})
            cur.pop("leader_challenge_id", None)
            cur.pop("challenge_reply_done", None)
            self.store.set_state(RunState.REVIEWING)
            return None
        if unresolved:
            lc.status = ChallengeStatus.UNRESOLVED_FINAL
            mirror = d.challenges[lc.related_challenge_ids[0]]
            mirror.status = ChallengeStatus.UNRESOLVED_FINAL
            d.unfinished_checks.append(f"{lc.id} unresolved: {lc.distinguishing_evidence}")
        # Evidence added by the reply changes the snapshot: rescore before reporting when affordable.
        last = list(d.round_summaries.values())[-1] if d.round_summaries else None
        if last is not None and last.comparison_key is not None and last.comparison_key.as_tuple() != self.key().as_tuple():
            needed = len(self._judge_queue(self.key()))
            if needed and d.budget.can_afford(lim, needed) and not cur.get("final_rescore_done"):
                cur["final_rescore"] = True
                cur["final_rescore_done"] = True
                self.store.event(EventKind.RESCORE_REQUIRED, {"reason": "evidence after final judging", "versions": needed,
                                                              "snapshot": d.evidence_snapshot_id})
                self.store.set_state(RunState.JUDGING)
                return None
        self.store.set_state(RunState.REPORTING)
        return None

    def _on_REPORTING(self) -> Optional[PendingRequest]:
        d = self.store.data
        d.stop_reason = d.pending_stop_reason or StopReason.FAILED
        decision = build_decision(self)
        self.store.commit(decision)
        report_md = render_report(self, decision)
        (self.store.run_dir / "report.md").write_text(report_md)
        (self.store.run_dir / "decision.json").write_text(decision.model_dump_json(indent=1))
        self.store.event(EventKind.RUN_FINISHED, {"state": "COMPLETE" if d.stop_reason != StopReason.CANCELLED else "CANCELLED",
                                                  "stop_reason": d.stop_reason.value, "decision": decision.kind.value})
        self.store.set_state(RunState.CANCELLED if d.stop_reason == StopReason.CANCELLED else RunState.COMPLETE)
        return None

    # ------------------------------------------------------------ merge dups

    def _merge_duplicates(self, new_versions: list[OptionVersion]) -> None:
        d = self.store.data
        existing = [v for v in self.candidates() if v.id not in {n.id for n in new_versions}]
        norm = {_norm(v.title): v for v in existing}
        for nv in new_versions:
            key = _norm(nv.title)
            if key in norm:
                surv = norm[key]
                nv.status = OptionStatus.MERGED
                nv.merged_from = [surv.id]
                nv.change_reason = f"duplicate of {surv.id} ({surv.title}); merged, lineage kept"
                self.store.relate(RelationKind.SUPERSEDES, surv.id, nv.id)
                self.store.event(EventKind.RESPONSE_COMMITTED, {"merged": nv.id, "into": surv.id})


def _norm(text: str) -> str:
    return " ".join("".join(ch for ch in text.lower() if ch.isalnum() or ch == " ").split())
