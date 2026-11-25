"""Discussion transcript and user documents: what every role can read before it answers.

Two things make a council a *discussion* rather than a loop of independent calls:

1. **The discussion transcript.** Every model contribution (committed or rejected) is written, in order, to
   ``<run>/discussion/NNN_rR_<phase>_<role>[_<lens>].md`` and appended to ``<run>/discussion.md``, rendered as
   readable Markdown with the raw JSON below it. Every later request carries ``discussion_so_far``: the full text
   of this round's contributions plus the controller's summary of every earlier round (incumbent, outcome, open
   objections) and the short summary of each earlier contribution, within ``discussion.max_chars``. Roles are told
   to build on, answer or contest what others said and to cite the D-numbers.

2. **User documents.** ``--docs path[,path]`` copies the user's files and folders into ``<run>/inputs/``, registers
   each as ``user_supplied`` evidence (``ev_doc_<slug>``) so claims can cite it, and puts an excerpt of each into
   every request's ``documents`` list within ``documents.max_chars_in_payload``. On the chat route the model can
   read the full copies; on isolated routes only the excerpts travel.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .ontology import Evidence, EvidenceSource, EvidenceSourceKind, Role, VerificationStatus

if TYPE_CHECKING:  # pragma: no cover
    from .config import CouncilConfig
    from .state import PendingRequest, Store

# ---------------------------------------------------------------------------
# rendering a JSON reply as readable Markdown
# ---------------------------------------------------------------------------


def _label(key: str) -> str:
    return key.replace("_", " ")


def json_to_md(obj: Any, level: int = 0) -> str:
    """Faithful, readable rendering of a reply: dict keys become labels, lists become bullets."""
    pad = "  " * level
    if isinstance(obj, dict):
        lines = []
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}- **{_label(str(k))}:**")
                lines.append(json_to_md(v, level + 1))
            else:
                lines.append(f"{pad}- **{_label(str(k))}:** {json_to_md(v, level + 1).strip() if not isinstance(v, (dict, list)) else '(empty)'}")
        return "\n".join(lines)
    if isinstance(obj, list):
        if all(not isinstance(x, (dict, list)) for x in obj):
            return "\n".join(f"{pad}- {x}" for x in obj) if obj else f"{pad}- (empty)"
        return "\n".join(json_to_md(x, level) if isinstance(x, (dict, list)) else f"{pad}- {x}" for x in obj)
    if obj is None:
        return "—"
    if isinstance(obj, bool):
        return "yes" if obj else "no"
    return str(obj)


# ---------------------------------------------------------------------------
# transcript
# ---------------------------------------------------------------------------


def _short(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def contribution_summary(kind: str, submission: Any, max_chars: int = 420) -> str:
    """One-paragraph gist of a reply, by request kind (used for earlier rounds in the payload)."""
    s = submission if isinstance(submission, dict) else {}
    try:
        if kind == "frame":
            return _short(f"Brief: {s.get('decision_statement', '')} Objectives: {'; '.join(s.get('objectives', []))}. Assumptions: {'; '.join(s.get('inferred_assumptions', []))}", max_chars)
        if kind == "policy":
            crit = "; ".join(f"{c.get('name')} ({c.get('kind')}{', w ' + str(c.get('weight')) if c.get('kind') == 'score' else ''})" for c in s.get("criteria", []))
            return _short(f"Rubric: {crit}. Scenarios: {'; '.join(x.get('name', '') for x in s.get('scenarios', []))}", max_chars)
        if kind in ("baseline", "generate"):
            opts = "; ".join(f"“{o.get('title')}”: {o.get('summary', '')}" for o in s.get("options", []))
            return _short(f"Options: {opts or 'none (nothing material)'}", max_chars)
        if kind == "review":
            ch = "; ".join(f"[{c.get('severity')}] {c.get('target')}: {c.get('mechanism', '')}" for c in s.get("challenges", []))
            dis = "; ".join(f"dissent: {x.get('position', '')}" for x in s.get("dissents", []) or [])
            return _short(f"Objections: {ch or 'none'}. {dis}", max_chars)
        if kind == "verify":
            return _short("Verification: " + "; ".join(f"{e.get('verification_status')}: {e.get('statement', '')}" for e in s.get("evidence", [])), max_chars)
        if kind == "respond":
            return _short("Responses: " + "; ".join(f"{r.get('kind')} {r.get('challenge_id')}: {r.get('text', '')}" for r in s.get("responses", [])), max_chars)
        if kind == "judge":
            sc = "; ".join(f"{c.get('criterion_id')}={c.get('score')}" for c in s.get("criterion_scores", []))
            gates = "; ".join(f"{g.get('criterion_id')}:{g.get('outcome')}" for g in s.get("gate_results", []))
            return _short(f"Scores: {sc}. Gates: {gates}", max_chars)
        if kind == "compare":
            return _short(f"Pairwise: prefers {s.get('preferred')} — {s.get('rationale', '')}", max_chars)
        if kind == "challenge":
            return _short(f"Leader challenge: loses if {s.get('losing_scenario', '')}; alternative {s.get('strongest_alternative_version_id')}; evidence: {s.get('distinguishing_evidence', '')}", max_chars)
        if kind == "challenge_reply":
            return _short(f"Leader reply: {s.get('kind')} — {s.get('text', '')}", max_chars)
    except Exception:  # noqa: BLE001 - a summary must never fail a commit
        pass
    return _short(json.dumps(submission)[:max_chars], max_chars)


def record_contribution(store: "Store", req: "PendingRequest", submission: Any, *, provider: str, model: Optional[str],
                        outcome: str, error: Optional[str] = None, write_files: bool = True,
                        notes: Optional[list[str]] = None) -> dict[str, Any]:
    """Append one model contribution to the run's discussion (index in state, files on disk). Never raises."""
    d = store.data
    n = len(d.discussion) + 1
    lens = req.lens_id or ""
    builds_on = submission.get("builds_on") if isinstance(submission, dict) else None
    entry = {
        "n": n, "round": req.round, "phase": req.state, "kind": req.kind, "role": req.role, "lens": lens or None,
        "participant": req.participant_id, "provider": provider, "model": model, "request_id": req.request_id, "attempt": req.attempt,
        "outcome": outcome, "error": (error or "")[:300] or None, "summary": contribution_summary(req.kind, submission),
        "file": None, "chars": len(json.dumps(submission)) if submission is not None else 0,
        "builds_on": [str(x) for x in builds_on] if isinstance(builds_on, list) else [],
        "notes": list(notes or []),
    }
    try:
        if write_files:
            ddir = store.run_dir / "discussion"
            ddir.mkdir(exist_ok=True)
            name = f"{n:03d}_r{req.round}_{req.state}_{req.role}" + (f"_{lens}" if lens else "") + ".md"
            who = f"{provider} · {model}" if model else provider
            head = [f"# D{n} — round {req.round} · {req.state} · {req.role}" + (f" (lens {lens})" if lens else ""),
                    f"participant `{req.participant_id}` · answered by {who} · request `{req.request_id}` attempt {req.attempt} · **{outcome}**"
                    + (f" — {error[:300]}" if error else "") + (" — partial: " + "; ".join(notes) if notes else ""), ""]
            body = json_to_md(submission) if isinstance(submission, (dict, list)) else str(submission)
            text = "\n".join(head) + body + "\n\n<details><summary>raw JSON</summary>\n\n```json\n" + json.dumps(submission, indent=1, ensure_ascii=False) + "\n```\n</details>\n"
            (ddir / name).write_text(text)
            with (store.run_dir / "discussion.md").open("a") as fh:
                fh.write(text + "\n---\n\n")
            entry["file"] = f"discussion/{name}"
    except Exception as exc:  # noqa: BLE001
        entry["file_error"] = f"{type(exc).__name__}: {exc}"
    d.discussion.append(entry)
    return entry


def _round_digest(store: "Store", round_no: int, *, with_scores: bool = True) -> Optional[str]:
    """The controller's own summary of a finished round: incumbent, outcome, ranking, open objections.
    ``with_scores=False`` (judges) names the incumbent and the open objections but withholds the ranking and its numbers."""
    d = store.data
    rs = next((r for r in d.round_summaries.values() if r.round == round_no), None)
    if rs is None:
        return None
    ov = d.option_versions

    def t(vid: Optional[str]) -> str:
        return ov[vid].title if vid and vid in ov else (vid or "—")

    rank = "; ".join(f"{t(v)} {s:.2f}" for v, s in rs.ranking[:5])
    open_ch = [c for c in d.challenges.values() if c.round <= round_no and c.status.value in ("open", "unresolved_final")]
    objections = "; ".join(f"{c.id} [{c.severity.value}] on {t(c.target_ref) if c.target_ref in ov else c.target_ref}: {_short(c.mechanism, 140)}" for c in open_ch[:8])
    if not with_scores:
        return (f"Round {round_no}: {len(rs.ranking)} option(s) scored; "
                + (f"open objections: {objections}." if objections else "no open objection."))
    return (f"Round {round_no} outcome ({rs.promotion_outcome.value}): incumbent {t(rs.incumbent_version_id)}"
            + (f", challenger {t(rs.challenger_version_id)}" if rs.challenger_version_id else "") + f". Ranking: {rank}."
            + (f" Open objections: {objections}." if objections else " No open objection.") + (f" Note: {rs.note}" if rs.note else ""))


def _strip_header(text: str) -> str:
    """Drop the '# Dn — …' and 'participant … answered by …' lines of a transcript file (authorship, model)."""
    lines = text.split("\n")
    while lines and (lines[0].startswith("# D") or lines[0].startswith("participant `") or not lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines).strip()


def discussion_payload(store: "Store", cfg: "CouncilConfig", *, alias_map: Optional[dict[str, str]] = None, blind: bool = False,
                       hide_scores: bool = False, mode: Optional[str] = None,
                       summarize_kinds: Optional[set[str]] = None) -> Optional[dict[str, Any]]:
    """What a role receives about the conversation so far, within ``discussion.max_chars``.

    Current-round contributions travel in full (rendered text); earlier rounds as the controller's digest plus each
    contribution's short summary. Oldest material is dropped first when the cap is hit. ``alias_map`` (isolated
    review) replaces option version ids with their pseudonyms. ``blind`` withholds who said what (participant ids,
    providers, models); ``hide_scores`` withholds the ranking numbers from the digests (judges); ``mode`` overrides
    ``discussion.include`` for this request; ``summarize_kinds`` are request kinds whose contributions are given as
    summaries because the payload already carries their content in full (options, responses)."""
    dc = cfg.discussion
    include = mode or dc.include
    if include == "none" or not store.data.discussion:
        return None
    d = store.data
    entries = [e for e in d.discussion if e.get("outcome") == "committed"]
    inverse = {v: k for k, v in (alias_map or {}).items()}
    summarize_kinds = summarize_kinds or set()

    def mask(text: str) -> str:
        if not inverse:
            return text
        return re.sub(r"optv_[A-Za-z0-9_]+", lambda m: inverse.get(m.group(0), m.group(0)), text)

    cur = d.round
    items: list[dict[str, Any]] = []
    for e in entries:
        full = include == "full" or (include == "current_round_and_summaries" and e["round"] == cur)
        in_payload = e.get("kind") in summarize_kinds
        text = e["summary"]
        if full and not in_payload and e.get("file"):
            p = store.run_dir / e["file"]
            if p.exists():
                raw = p.read_text()
                text = _strip_header(raw.split("<details>", 1)[0])
        item = {"d": f"D{e['n']}", "round": e["round"], "phase": e["phase"], "role": e["role"], "lens": e.get("lens"), "says": mask(text)}
        if not blind:
            item["participant"] = e["participant"]
        if in_payload and full:
            item["see_payload"] = True
        if e.get("builds_on"):
            item["builds_on"] = e["builds_on"]
        items.append(item)
    digests = [{"round": r, "controller_digest": mask(x)} for r in range(0, cur) if (x := _round_digest(store, r, with_scores=not hide_scores))]
    if include == "summaries":
        items = [{**i, "says": mask(next(e["summary"] for e in entries if f"D{e['n']}" == i["d"]))} for i in items]
    # cap: drop oldest full items first (downgrade to summary), then drop oldest summaries
    def size() -> int:
        return len(json.dumps(items)) + len(json.dumps(digests))

    truncated = False
    by_d = {f"D{e['n']}": e for e in entries}
    for i in items:
        if size() <= dc.max_chars:
            break
        if len(i["says"]) > len(by_d[i["d"]]["summary"]):
            i["says"] = mask(by_d[i["d"]]["summary"])
            truncated = True
    for g in digests:
        if size() <= dc.max_chars:
            break
        if len(g["controller_digest"]) > 400:
            g["controller_digest"] = g["controller_digest"][:399] + "…"
            truncated = True
    # then drop the oldest material first, whichever kind it is (a digest of round r is older than round r's contributions)
    while size() > dc.max_chars and (items or digests):
        if digests and (not items or digests[0]["round"] <= items[0]["round"]):
            digests.pop(0)
        else:
            items.pop(0)
        truncated = True
    return {"how_to_use": "Ordered contributions of the other roles in this run (D-numbers). Build on them, answer them or contest them "
                          "explicitly in your reply and list the D-numbers you rely on in builds_on. Earlier rounds are the controller's digest plus short summaries; "
                          "entries marked see_payload are given in full elsewhere in this request; the full transcript is in the run folder (discussion.md).",
            "policy": include, "earlier_rounds": digests, "contributions": items, "truncated": truncated,
            "transcript_path": str(store.run_dir / "discussion.md")}


# ---------------------------------------------------------------------------
# user documents
# ---------------------------------------------------------------------------

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".council", "council_outcomes"}


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    return s[:40] or "doc"


def collect_documents(paths: list[str], cfg: "CouncilConfig", *, base: Optional[Path] = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Read the user's files/folders into memory within the configured limits. Returns (documents, notes)."""
    dc = cfg.documents
    docs: list[dict[str, Any]] = []
    notes: list[str] = []
    total = 0
    seen: set[str] = set()
    for raw in paths:
        p = Path(raw).expanduser()
        if not p.is_absolute() and base is not None:
            p = base / p
        if not p.exists():
            notes.append(f"not found: {raw}")
            continue
        files = [p] if p.is_file() else sorted(f for f in p.rglob("*") if f.is_file() and not any(part in SKIP_DIRS or part.startswith(".") for part in f.relative_to(p).parts))
        for f in files:
            key = str(f.resolve())
            if key in seen:
                continue
            seen.add(key)
            if f.suffix.lower() not in dc.extensions:
                notes.append(f"skipped (extension not allowed): {f}")
                continue
            size = f.stat().st_size
            if size > dc.max_file_bytes:
                notes.append(f"skipped (over {dc.max_file_bytes} bytes): {f}")
                continue
            if total + size > dc.max_total_bytes:
                notes.append(f"skipped (total over {dc.max_total_bytes} bytes): {f}")
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                notes.append(f"unreadable: {f} ({e})")
                continue
            total += size
            docs.append({"path": str(f), "name": f.name, "slug": _slug(f.stem), "bytes": size, "chars": len(text), "text": text})
    # disambiguate slugs
    counts: dict[str, int] = {}
    for doc in docs:
        counts[doc["slug"]] = counts.get(doc["slug"], 0) + 1
        if counts[doc["slug"]] > 1:
            doc["slug"] = f"{doc['slug']}_{counts[doc['slug']]}"
    return docs, notes


def register_documents(store: "Store", cfg: "CouncilConfig", docs: list[dict[str, Any]], notes: list[str]) -> list[str]:
    """Copy documents into ``<run>/inputs/``, write ``inputs/INDEX.md``, commit one user-supplied Evidence per document."""
    d = store.data
    idir = store.run_dir / "inputs"
    idir.mkdir(exist_ok=True)
    ids: list[str] = []
    index = ["# Input documents", "", "Supplied by the user with --docs; each is evidence (user_supplied) that every role may cite by id.", ""]
    for i, doc in enumerate(docs, 1):
        copy = idir / f"{i:02d}_{doc['name']}"
        copy.write_text(doc["text"])
        eid = f"ev_doc_{doc['slug']}"
        head = _short(doc["text"][:600], 300)
        ev = Evidence(id=eid, statement=f"Document “{doc['name']}” ({doc['chars']:,} chars) supplied by the user: {head}",
                      source=EvidenceSource(kind=EvidenceSourceKind.DOCUMENT, ref=doc["path"]), verification_status=VerificationStatus.USER_SUPPLIED,
                      round=0, author_participant_id="controller", author_role=Role.CONTROLLER)
        store.commit_baseline_evidence(ev)
        ids.append(eid)
        d.documents.append({"evidence_id": eid, "name": doc["name"], "path": doc["path"], "copy": f"inputs/{copy.name}", "chars": doc["chars"], "bytes": doc["bytes"]})
        index.append(f"- `{eid}` — {doc['name']} ({doc['chars']:,} chars) — original `{doc['path']}` — copy `inputs/{copy.name}`")
    if notes:
        index += ["", "## Notes", *[f"- {n}" for n in notes]]
    (idir / "INDEX.md").write_text("\n".join(index) + "\n")
    d.document_notes = list(notes)
    return ids


def documents_payload(store: "Store", cfg: "CouncilConfig") -> Optional[dict[str, Any]]:
    """Excerpts of the user's documents for a request, within ``documents.max_chars_in_payload``."""
    d = store.data
    if not d.documents:
        return None
    dc = cfg.documents
    budget = dc.max_chars_in_payload
    per_doc = min(dc.max_chars_per_document, max(500, budget // max(1, len(d.documents))))
    items = []
    for doc in d.documents:
        p = store.run_dir / doc["copy"]
        text = p.read_text() if p.exists() else ""
        excerpt = text[:per_doc]
        items.append({"evidence_id": doc["evidence_id"], "name": doc["name"], "chars": doc["chars"], "copy": str(p),
                      "excerpt": excerpt, "excerpt_is_complete": len(excerpt) >= len(text)})
    return {"how_to_use": "Files the user supplied for this decision. Cite a document by its evidence_id when you rely on it. "
                          "Excerpts are capped; the full copy is at `copy` (readable on the chat route).",
            "documents": items, "notes": d.document_notes}


_PATH_RE = re.compile(r"(?:(?<=[\s\"'`(\[])|^)((?:~|\.{1,2})?/[^\s\"'`<>|;,)\]]+)")


def paths_in_text(text: str, *, base: Optional[Path] = None) -> list[str]:
    """Local paths named in free text that exist on this machine (files or folders), in order, de-duplicated.
    Trailing punctuation is stripped; relative ``./x`` paths resolve against ``base``."""
    found: list[str] = []
    for m in _PATH_RE.finditer(text or ""):
        raw = m.group(1).rstrip(".:!?")
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (base or Path.cwd()) / p
        try:
            if p.exists() and str(p) not in found:
                found.append(str(p))
        except OSError:
            continue
    return found


def register_question_documents(store: "Store", cfg: "CouncilConfig", question: str, *, base: Optional[Path] = None) -> list[str]:
    """When the question names existing local files or folders and no --docs was given, register them as documents so
    every role (tool-less ones included) receives their content as evidence. Returns the evidence ids."""
    paths = paths_in_text(question, base=base)
    if not paths:
        return []
    docs, notes = collect_documents(paths, cfg, base=base)
    notes = [f"auto-detected from the question: {', '.join(paths)}"] + notes
    return register_documents(store, cfg, docs, notes)
