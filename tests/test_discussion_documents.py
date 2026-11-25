"""The council is a discussion: every contribution is written in order, later roles receive it, and user documents are evidence."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from conftest import FIXTURES, LENSES, PROJECT_ROOT, QUESTION, make_root, run_fixture
from llm_council.config import CouncilConfig
from llm_council.discussion import collect_documents, contribution_summary, discussion_payload, json_to_md


def _requests(run_dir: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((run_dir / "requests").glob("req_*.json"))]


def test_every_contribution_is_written_in_order_and_fed_to_later_roles(tmp_path):
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, FIXTURES / "main_run.json", lenses=LENSES, run_id="disc")
    d = engine.store.data
    run_dir = engine.store.run_dir
    # one transcript entry per answered request, in request order, all committed (this fixture rejects nothing)
    assert len(d.discussion) == 32 and [e["n"] for e in d.discussion] == list(range(1, 33))
    assert all(e["outcome"] == "committed" for e in d.discussion)
    files = sorted((run_dir / "discussion").glob("*.md"))
    assert len(files) == 32 and files[0].name.startswith("001_r0_FRAMING_framer") and files[-1].name.startswith("032_")
    text = (run_dir / "discussion.md").read_text()
    assert text.index("# D1 ") < text.index("# D2 ") < text.index("# D32 ")
    assert "raw JSON" in text and "Staged 10% pilot" in text
    # the first request carries no discussion; the policy request carries the framer's contribution in full
    reqs = _requests(run_dir)
    assert "discussion_so_far" not in reqs[0]["payload"]
    pol = reqs[1]
    assert pol["kind"] == "policy" and "Discussion:" in pol["instructions"]
    disc = pol["payload"]["discussion_so_far"]
    assert disc["contributions"][0]["d"] == "D1" and disc["contributions"][0]["role"] == "framer"
    assert "decision statement" in disc["contributions"][0]["says"] and disc["policy"] == "current_round_and_summaries"
    # a round-1 reviewer sees this round's strategist proposals in full, and round 0 as digest + summaries
    review = next(r for r in reqs if r["kind"] == "review" and r["round"] == 1)
    disc = review["payload"]["discussion_so_far"]
    cur = [c for c in disc["contributions"] if c["round"] == 1]
    assert any(c["role"] == "strategist" and "Staged 10% pilot" in c["says"] for c in cur)
    assert disc["earlier_rounds"] and disc["earlier_rounds"][0]["round"] == 0 and "incumbent" in disc["earlier_rounds"][0]["controller_digest"]
    r0 = [c for c in disc["contributions"] if c["round"] == 0]
    assert r0 and all(len(c["says"]) <= 430 for c in r0)          # earlier round: summaries only
    # a round-2 request gets the digest of round 1 (the promotion) too
    r2 = next(r for r in reqs if r["round"] == 2)
    digests = {x["round"]: x["controller_digest"] for x in r2["payload"]["discussion_so_far"]["earlier_rounds"]}
    assert 0 in digests and 1 in digests and "promoted" in digests[1]
    # the dashboard has the discussion tab and the report notes the shared transcript
    import json as _json
    import re as _re
    from llm_council.dashboard import write_dashboard
    html = write_dashboard(engine).read_text()
    m = _re.search(r'<script type="application/json" id="council-state">(.*?)</script>', html, re.S)
    assert m and any(x["n"] == 32 for x in _json.loads(m.group(1))["discussion"])
    assert "Discussion transcript shared with every role" in (run_dir / "report.md").read_text()


def test_discussion_cap_shortens_then_drops_oldest_first(tmp_path):
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, FIXTURES / "main_run.json", lenses=LENSES, run_id="cap")
    cfg = CouncilConfig.model_validate(engine.store.data.effective_config | {"discussion": {"max_chars": 1500}})
    disc = discussion_payload(engine.store, cfg)
    assert disc["truncated"] is True and len(json.dumps(disc["contributions"])) + len(json.dumps(disc["earlier_rounds"])) <= 1500
    kept = [c["d"] for c in disc["contributions"]]
    assert kept == sorted(kept, key=lambda x: int(x[1:])) and kept[-1] == "D32"   # newest survive
    cfg = CouncilConfig.model_validate(engine.store.data.effective_config | {"discussion": {"include": "none"}})
    assert discussion_payload(engine.store, cfg) is None
    cfg = CouncilConfig.model_validate(engine.store.data.effective_config | {"discussion": {"include": "full", "max_chars": 2_000_000}})
    full = discussion_payload(engine.store, cfg)
    assert all(len(c["says"]) > 0 for c in full["contributions"]) and any("raw JSON" not in c["says"] for c in full["contributions"])


def test_rejected_replies_are_in_the_transcript_but_not_fed_to_others(tmp_path):
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, FIXTURES / "schema_rejection.json", lenses=LENSES, run_id="rej", strict=False)
    d = engine.store.data
    rejected = [e for e in d.discussion if e["outcome"] == "rejected"]
    assert rejected and all(e["error"] for e in rejected)
    assert (engine.store.run_dir / rejected[0]["file"]).read_text().startswith("# D")
    payloads = [r["payload"].get("discussion_so_far") for r in _requests(engine.store.run_dir)]
    fed = {c["d"] for p in payloads if p for c in p["contributions"]}
    assert not any(f"D{e['n']}" in fed for e in rejected)


def test_json_to_md_and_summaries():
    md = json_to_md({"decision_statement": "Decide X", "objectives": ["a", "b"], "nested": {"k": 1, "flag": True}, "empty": []})
    assert "- **decision statement:** Decide X" in md and "  - a" in md and "**flag:** yes" in md and "**empty:** (empty)" in md
    s = contribution_summary("generate", {"options": [{"title": "T", "summary": "S"}]})
    assert s.startswith("Options: “T”: S")
    assert contribution_summary("review", {"challenges": [{"severity": "material", "target": "optv_1", "mechanism": "m"}]}).startswith("Objections: [material] optv_1: m")
    assert len(contribution_summary("frame", {"decision_statement": "x" * 2000, "objectives": []})) <= 420


def test_user_documents_become_evidence_and_reach_every_role(tmp_path):
    root = make_root(tmp_path)
    docs = tmp_path / "docs"
    (docs / "sub").mkdir(parents=True)
    (docs / "brief.md").write_text("# Campaign brief\nBudget 400k EUR. Video CPM rose 30% last January.\n")
    (docs / "sub" / "data.csv").write_text("month,cac\njan,42\nfeb,45\n")
    (docs / "image.png").write_bytes(b"\x89PNG\r\n")
    (docs / "huge.txt").write_text("x" * 300_000)
    cmd = [sys.executable, "-m", "llm_council.cli", "run", QUESTION, "--fixture", str(FIXTURES / "main_run.json"), "--lenses", LENSES,
           "--run-id", "docs", "--docs", str(docs), "--root", str(root)]
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=180)
    assert out.returncode == 0, out.stderr
    assert "documents: 2 registered as evidence (ev_doc_brief, ev_doc_data)" in out.stdout
    run_dir = root / "council_outcomes" / "docs"
    state = json.loads((run_dir / "state.json").read_text())
    assert [x["evidence_id"] for x in state["documents"]] == ["ev_doc_brief", "ev_doc_data"]
    ev = state["evidence"]["ev_doc_brief"]
    assert ev["verification_status"] == "user_supplied" and ev["source"]["kind"] == "document" and ev["author_role"] == "controller"
    index = (run_dir / "inputs" / "INDEX.md").read_text()
    assert "ev_doc_brief" in index and "skipped (extension not allowed)" in index and "huge.txt" in index and "over 200000 bytes" in index
    assert (run_dir / "inputs" / "01_brief.md").read_text().startswith("# Campaign brief")
    # every request carries the excerpts and the instruction to cite them
    reqs = _requests(run_dir)
    assert all("documents" in r["payload"] and "Documents:" in r["instructions"] for r in reqs)
    first = reqs[0]["payload"]["documents"]
    assert first["documents"][0]["evidence_id"] == "ev_doc_brief" and "Video CPM rose 30%" in first["documents"][0]["excerpt"]
    assert first["documents"][1]["excerpt_is_complete"] is True
    # evidence payload (what claims can cite) includes the document evidence
    assert any(e["id"] == "ev_doc_brief" for e in reqs[0]["payload"].get("evidence", [])) or "ev_doc_brief" in json.dumps(reqs[2]["payload"].get("evidence", []))
    html = (run_dir / "index.html").read_text()   # the CLI writes the dashboard
    assert "Input documents" in html and "ev_doc_brief" in html and "inputs/01_brief.md" in html
    assert "User documents: 2 file(s)" in (run_dir / "report.md").read_text()


def test_collect_documents_limits(tmp_path):
    cfg = CouncilConfig.model_validate({"documents": {"max_file_bytes": 1000, "max_total_bytes": 1500}})
    f = tmp_path / "f"
    f.mkdir()
    (f / "a.md").write_text("a" * 900)
    (f / "b.md").write_text("b" * 900)
    (f / "c.md").write_text("c" * 1200)
    (f / ".hidden.md").write_text("h")
    docs, notes = collect_documents([str(f), str(tmp_path / "missing.md")], cfg)
    assert [d["name"] for d in docs] == ["a.md"] and any("total over" in n for n in notes) and any("over 1000 bytes" in n for n in notes) and any("not found" in n for n in notes)
    assert not any(".hidden" in d["name"] for d in docs)


def test_docs_flag_passes_through_the_args_file(tmp_path):
    from llm_council.cli import split_args_text
    q, flags = split_args_text('What should we do? --preset quick --docs "/tmp/a b,/tmp/c" --chat-model claude-sonnet-5-5')
    assert q == "What should we do?" and flags["preset"] == "quick" and flags["docs"] == "/tmp/a b,/tmp/c" and flags["chat_model"] == "claude-sonnet-5-5"
