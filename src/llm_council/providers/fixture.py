"""Deterministic fixture provider.

A fixture file is a JSON object ``{"responses": [...]}``. Each entry has a
``match`` object compared against the request's ``match_hints`` (kind, role,
round, lens, version_id, snapshot, challenge_id, reviewer, judge, slot, ...).
Matching is by request content, never by call order. Each entry is consumed
once unless ``"once": false``. An unmatched request raises; at the end of the
run, unconsumed ``once`` entries raise. Entries may carry ``"raw"`` text instead
of ``"content"`` to exercise schema rejection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ..state import PendingRequest
from .base import ModelReply, Provider, ProviderError


class FixtureProvider(Provider):
    name = "fixture"
    isolation = "shared"

    def __init__(self, path: Path | str, *, strict_consumption: bool = True):
        self.path = Path(path)
        data = json.loads(self.path.read_text())
        self.entries: list[dict[str, Any]] = data["responses"]
        self.meta: dict[str, Any] = data.get("meta", {})
        self.used: list[int] = []
        self.strict = strict_consumption
        self.log: list[dict[str, Any]] = []

    def _matches(self, match: dict[str, Any], hints: dict[str, Any]) -> bool:
        for k, v in match.items():
            if hints.get(k) != v:
                return False
        return True

    def answer(self, req: PendingRequest) -> ModelReply:
        hints = dict(req.match_hints)
        hints["attempt"] = req.attempt
        best: Optional[int] = None
        best_len = -1
        for i, e in enumerate(self.entries):
            if i in self.used and e.get("once", True):
                continue
            m = e.get("match", {})
            if self._matches(m, hints) and len(m) > best_len:
                best, best_len = i, len(m)
        if best is None:
            raise ProviderError(f"fixture {self.path.name}: no response matches request {req.request_id} hints {hints}")
        entry = self.entries[best]
        self.used.append(best)
        self.log.append({"request_id": req.request_id, "entry": best, "hints": hints})
        if "raw" in entry:
            text = entry["raw"]
        else:
            text = json.dumps(entry["content"])
        return ModelReply(text=text, provider="fixture", model_requested="fixture", model_reported="fixture",
                          tokens_measured=None, cost_usd=None, isolation=self.isolation)

    def finish(self) -> None:
        if not self.strict:
            return
        unconsumed = [i for i, e in enumerate(self.entries) if e.get("once", True) and i not in self.used]
        if unconsumed:
            raise ProviderError(f"fixture {self.path.name}: unconsumed responses at indexes {unconsumed}: "
                                + "; ".join(json.dumps(self.entries[i].get("match")) for i in unconsumed))
