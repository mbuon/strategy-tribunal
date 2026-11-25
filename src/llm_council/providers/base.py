"""Provider protocol: answer one PendingRequest with raw text plus usage metadata."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from ..state import PendingRequest


class ProviderError(Exception):
    pass


class ModelReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    provider: str
    model_requested: Optional[str] = None
    model_reported: Optional[str] = None
    tokens_measured: Optional[int] = None
    cost_usd: Optional[float] = None
    isolation: str = "shared"
    substitution: Optional[str] = None
    session_ref: Optional[str] = None
    tokens_detail: dict[str, int] = {}          # input / output / reasoning / cache_read / cache_write when the provider reports them
    latency_seconds: Optional[float] = None     # wall-clock time of the call
    effort: Optional[str] = None                # provider/model effort or variant label when known (e.g. "#high", "reasoning")


class Provider:
    name: str = "base"
    isolation: str = "shared"

    def answer(self, req: PendingRequest) -> ModelReply:  # pragma: no cover - interface
        raise NotImplementedError

    def finish(self) -> None:
        """Hook for end-of-run checks (e.g. fixture consumption)."""


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


def parse_reply_json(text: str) -> Any:
    """Parse a model reply as JSON; tolerate a single markdown fence. Returns the raw
    text wrapped in a dict when parsing fails so that schema validation rejects it
    with a clear error instead of the engine crashing."""
    t = text.strip()
    m = _FENCE.match(t)
    if m:
        t = m.group(1)
    try:
        return json.loads(t)
    except json.JSONDecodeError as e:
        # Models sometimes wrap the object in prose or a fence that is not at the edges: take the outermost
        # object, then try the small mechanical repairs that account for most rejected replies. Anything else is
        # rejected by schema validation with the parse error attached.
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end > start:
            inner = t[start:end + 1]
            for candidate in (inner, repair_json_text(inner)):
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
        return {"__unparseable__": t[:500], "__error__": str(e)}


_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_PAREN_STRING = re.compile(r"\(\s*(\"(?:[^\"\\]|\\.)*\")\s*\)")
_SMART_QUOTES = {"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"}


def repair_json_text(t: str) -> str:
    """Mechanical repairs for the JSON slips models make most: trailing commas, a string wrapped in parentheses
    (``["ev_a", ("ev_b")]``), typographic quotes, JavaScript-style comments. Never changes a reply that already parses."""
    t = _PAREN_STRING.sub(r"\1", t)
    t = _TRAILING_COMMA.sub(r"\1", t)
    t = re.sub(r"^\s*//.*$", "", t, flags=re.M)
    for k, v in _SMART_QUOTES.items():
        t = t.replace(k, v)
    return t
