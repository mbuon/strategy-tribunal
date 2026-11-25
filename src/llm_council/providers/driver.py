"""Drivers: feed provider replies to the engine until a chat-routed request (step
mode) or a terminal state. The chat model answers chat-routed requests through
``council submit``; fixture and OpenCode providers are answered here."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..config import CouncilConfig
from ..engine import Engine, ReplyMeta, StepResult
from ..ontology import EventKind
from .base import ModelReply, Provider, ProviderError, parse_reply_json
from .fixture import FixtureProvider
from .opencode import OpenCodeProvider


def build_providers(cfg: CouncilConfig, root: Path, run_id: str, *, fixture_path: Optional[str] = None) -> dict[str, Provider]:
    providers: dict[str, Provider] = {}
    fp = fixture_path or cfg.fixture_path
    if fp:
        providers["fixture"] = FixtureProvider(Path(fp) if Path(fp).is_absolute() else root / fp)
    if cfg.routing.opencode.enabled or any(x != "fixture" for x in cfg.routing.validation_fallbacks):
        providers["opencode"] = OpenCodeProvider(cfg.routing.opencode, root, run_id=run_id)
    return providers


def _fallback_name(cfg: CouncilConfig, providers: dict[str, Provider]) -> Optional[str]:
    fb = cfg.routing.opencode.fallback
    if fb == "fail":
        return None
    if fb == "fixture" and "fixture" in providers:
        return "fixture"
    if fb == "chat":
        return "chat"
    return None


def answer_with_fallback(engine: Engine, req, providers: dict[str, Provider]) -> tuple[Optional[ModelReply], Optional[str]]:
    """Returns (reply, route_used). route_used == 'chat' means the chat model must answer."""
    cfg = engine.cfg
    name = req.provider
    if name == "chat":
        return None, "chat"
    prov = providers.get(name)
    if prov is None:
        raise ProviderError(f"provider {name!r} requested but not available")
    try:
        return prov.answer(req), name
    except ProviderError as e:
        if name != "opencode":
            raise
        fb = _fallback_name(cfg, providers)
        engine.store.event(EventKind.ROUTE_FALLBACK, {"request_id": req.request_id, "from": name, "to": fb or "fail", "error": str(e)[:300]})
        if fb is None:
            raise
        if fb == "chat":
            req.provider = "chat"
            req.isolation = "shared"
            engine.store.save()
            return None, "chat"
        reply = providers[fb].answer(req)
        return reply, fb


def drive_until_chat_or_terminal(engine: Engine, providers: dict[str, Provider]) -> StepResult:
    result = engine.result()
    while result.status == "request":
        req = result.request
        assert req is not None
        try:
            reply, route = answer_with_fallback(engine, req, providers)
        except ProviderError as e:
            if req.provider == "fixture":
                raise  # a fixture mismatch is a test failure, not a runtime condition
            # The external route failed for this request and no fallback applies: record it and let the
            # controller take the request's failure transition (lens skipped, judgement missing, ...).
            result = engine.fail_pending(f"provider error: {e}")
            continue
        if reply is None:
            return result  # chat model must answer
        if route == "opencode" and reply.substitution:
            engine.store.event(EventKind.ROUTE_SUBSTITUTION, {"request_id": req.request_id, "note": reply.substitution})
        # keep the raw reply next to the request for audit, as the chat route does
        (engine.store.run_dir / "responses" / f"{req.request_id}.json").write_text(reply.text)
        submission = parse_reply_json(reply.text)
        meta = ReplyMeta(provider=reply.provider, model_requested=reply.model_requested, model_reported=reply.model_reported,
                         tokens_measured=reply.tokens_measured, cost_usd=reply.cost_usd, isolation=reply.isolation,
                         substitution=reply.substitution, raw_text=reply.text, tokens_detail=reply.tokens_detail,
                         latency_seconds=reply.latency_seconds, effort=reply.effort)
        result = engine.step(submission if isinstance(submission, dict) else {"__not_an_object__": submission}, meta)
    for p in providers.values():
        p.finish()
    return result
