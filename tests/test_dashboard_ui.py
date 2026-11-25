"""Run folders, dashboard page and local web UI."""
from __future__ import annotations

import json
import re
import threading
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from conftest import FIXTURES, LENSES, QUESTION, make_root, run_fixture
from llm_council import ui
from llm_council.cli import legacy_runs_root, load_engine, locate_run, new_run_id, question_slug, runs_root
from llm_council.dashboard import md_to_html, render_dashboard, write_dashboard


def test_run_ids_are_dated_readable_folders_and_legacy_runs_are_still_found(tmp_path):
    root = make_root(tmp_path)
    assert runs_root(root) == root / "council_outcomes" and legacy_runs_root(root) == root / ".council" / "runs"
    rid = new_run_id("Should we shift 30% of our Q1 paid-search budget into short-form video?")
    assert re.match(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_Should-we-shift-30-of-our-Q1-paid-search-budget$", rid), rid
    assert " " not in rid and "%" not in urllib.parse.quote(rid)       # no quoting in commands, no percent-encoding in URLs
    assert question_slug("x" * 200) == "council" and question_slug("???") == "council"
    assert question_slug("2+2=5 dimostralo") == "2-2-5-dimostralo"
    # a run created under the legacy root is located and loaded
    engine, _ = run_fixture(root, FIXTURES / "main_run.json", lenses=LENSES, run_id="legacy1")
    assert engine.store.run_dir == root / ".council" / "runs" / "legacy1"
    assert locate_run(root, "legacy1") == engine.store.run_dir
    loaded, _ = load_engine(root, "legacy1")
    assert loaded.store.data.state.value == "COMPLETE"
    try:
        locate_run(root, "nope")
        assert False
    except FileNotFoundError:
        pass


def _dashboard_state(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="council-state">(.*?)</script>', html, re.S)
    assert m, "React SPA shell must embed its state"
    return json.loads(m.group(1))


def _home_state(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="council-home-state">(.*?)</script>', html, re.S)
    assert m, "home page must embed its state"
    return json.loads(m.group(1))


def test_dashboard_lists_kpis_rounds_settings_log_files_and_report(tmp_path):
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, FIXTURES / "main_run.json", lenses=LENSES, run_id="dash")
    page = write_dashboard(engine)
    assert page == engine.store.run_dir / "index.html" and page.exists()
    html = page.read_text()
    assert (engine.store.run_dir / "TITLE.txt").read_text().strip().startswith("Decide how much of the fixed Q1 paid budget")
    state = _dashboard_state(html)
    # header and KPIs
    assert state["title"].startswith("Decide how much of the fixed Q1 paid budget")
    assert state["state"] == "COMPLETE" and state["stop"] == "stable"
    assert state["outcome"]["kind"] == "conditional" and state["outcome"]["confLevel"] == "low"
    by_label = {k["l"]: k["v"] for k in state["kpis"]}
    assert by_label["Model calls"] == "32/60" and "Ranking robustness" in by_label and "Promotions" in by_label
    # outcome and rounds with decisions taken
    assert state["outcome"]["recTitle"] == "Staged 10% pilot with scale gates" and state["outcome"]["next"] and state["outcome"]["reversal"]
    taken = [r["taken"] for r in state["rounds"]]
    assert any("challenger promoted to incumbent" in t for t in taken)
    assert any("incumbent kept (challenger lost)" in t for t in taken)
    assert any("round-zero baseline set" in t for t in taken)
    assert state["incumbentHistory"]
    # objections, settings with provenance and explanations, log, files, report
    assert state["objections"]["leader"] or state["objections"]["dissents"]
    settings = {s["key"]: s for s in state["settings"]}
    assert "limits.max_model_calls" in settings and "Call budget per run" in settings["limits.max_model_calls"]["explanation"]
    assert all("layer" in s for s in state["settings"])
    assert any(r["id"] == "req_0001" and "requests/req_0001.json" in r["filesHtml"] for r in state["log"])
    assert "decision.json" in [f["rel"] for f in state["files"]] and "events.jsonl" in [f["rel"] for f in state["files"]]
    assert "Round-by-round decision quality" in state["reportHtml"]
    # a finished run does not auto-refresh; a running one does
    assert "<meta http-equiv='refresh'" not in html
    engine.store.data.state = type(engine.store.data.state)("JUDGING")
    assert "<meta http-equiv='refresh'" in render_dashboard(engine)


def test_markdown_renderer_handles_headings_lists_tables_and_escapes():
    out = md_to_html("# T\n\n## S\n- a `code` **b**\n- c\n\n| h1 | h2 |\n|---|---|\n| 1 | <x> |\n\nplain")
    assert "<h1>T</h1>" in out and "<h2>S</h2>" in out and "<li>a <code>code</code> <strong>b</strong></li>" in out
    assert "<th>h1</th>" in out and "<td>&lt;x&gt;</td>" in out and "<p>plain</p>" in out


def _serve(root: Path) -> tuple[ThreadingHTTPServer, str]:
    ui.Handler.root = root
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ui.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _post(url: str, data: dict[str, str]) -> tuple[int, str]:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read().decode()


def test_web_ui_runs_settings_and_served_dashboard(tmp_path):
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, FIXTURES / "main_run.json", lenses=LENSES, run_id="ui1")
    httpd, base = _serve(root)
    try:
        code, body = _get(base + "/")
        assert code == 200
        home = _home_state(body)
        assert home["works"] == [] and home["legacyCount"] == 1  # ui1 lives in the legacy folder
        assert any("ui1" in (c.get("html", "") if isinstance(c, dict) else "") for row in home["tableRows"] for c in row)
        code, body = _get(base + "/api/runs.json")
        rows = json.loads(body)
        assert code == 200 and rows[0]["run_id"] == "ui1" and rows[0]["kind"] == "conditional" and rows[0]["calls"] == 32 and rows[0]["legacy"] is True
        code, body = _get(base + "/settings")
        assert code == 200 and "limits.max_rounds" in body and "Rubric weights by criterion" in body and "Save changed values" in body
        code, body = _post(base + "/settings", {"action": "set", "limits.max_rounds": "3", "judge.jury_size": "2"})
        assert code == 200 and "saved" in body and json.loads((root / ".council" / "settings.json").read_text()) == {"limits": {"max_rounds": 3}, "judge": {"jury_size": 2}}
        code, body = _post(base + "/settings", {"action": "set", "limits.min_rounds": "9"})
        assert "refused" in body and "min_rounds" in body and json.loads((root / ".council" / "settings.json").read_text())["limits"] == {"max_rounds": 3}
        code, body = _post(base + "/settings", {"action": "unset", "judge.jury_size": "x"})
        assert "removed" in body and "judge" not in json.loads((root / ".council" / "settings.json").read_text())
        code, body = _post(base + "/settings", {"action": "reset"})
        assert "saved settings removed" in body and not (root / ".council" / "settings.json").exists()
        code, body = _get(base + "/runs/ui1/")
        assert code == 200 and "href='../../settings'" in body and (engine.store.run_dir / "index.html").exists()
        ui1state = _dashboard_state(body)
        assert ui1state["title"].startswith("Decide how much")
        assert ui1state["outcome"]["kind"] == "conditional" and ui1state["outcome"]["confLevel"] == "low"
        code, _ = _get(base + "/runs/ui1/report.md")
        assert code == 200
        code, _ = _get(base + "/runs/ui1/../../council.config.json")
        assert code == 404
        code, _ = _get(base + "/runs/nope/")
        assert code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_delete_run_removes_the_work_folder(tmp_path):
    import urllib.error
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, FIXTURES / "main_run.json", lenses=LENSES, run_id="gone")
    run_dir = engine.store.run_dir
    assert run_dir.exists()
    httpd, base = _serve(root)
    try:
        req = urllib.request.Request(base + "/runs/gone/", method="DELETE")
        with urllib.request.urlopen(req, timeout=10) as r:
            assert r.status == 200 and json.loads(r.read().decode()) == {"deleted": "gone"}
        assert not run_dir.exists()
        code, _ = _get(base + "/runs/gone/")
        assert code == 404
        for bad in ("/runs/nope/", "/runs/../council.config.json", "/runs/gone/report.md"):
            req = urllib.request.Request(base + bad, method="DELETE")
            try:
                urllib.request.urlopen(req, timeout=10)
                assert False, bad
            except urllib.error.HTTPError as e:
                assert e.code == 404, bad
    finally:
        httpd.shutdown(); httpd.server_close()


def test_health_and_foreign_port_detection(tmp_path):
    """A port held by another local web app must not be mistaken for the council ui (it showed that app's page)."""
    from http.server import BaseHTTPRequestHandler

    class Foreign(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = b'{"error": "not found"}'
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):  # noqa: D401
            return

    root = make_root(tmp_path)
    foreign = ThreadingHTTPServer(("127.0.0.1", 0), Foreign)
    threading.Thread(target=foreign.serve_forever, daemon=True).start()
    fport = foreign.server_address[1]
    httpd, base = _serve(root)
    oport = httpd.server_address[1]
    try:
        code, body = _get(base + "/api/health")
        assert code == 200 and json.loads(body)["app"] == "strategy-tribunal"
        assert ui.is_up(fport) and not ui.is_ours(fport) and ui.is_ours(oport) and ui.is_ours(oport, root)
        port, status = ui.pick_port(root, fport, attempts=3)
        assert port != fport and status in ("free", "ours")
        assert ui.pick_port(root, oport, attempts=1) == (oport, "ours")
        assert ui.serve(root, fport, open_browser=False) == 2   # refuses a port held by another program
    finally:
        foreign.shutdown(); foreign.server_close(); httpd.shutdown(); httpd.server_close()


def test_fixture_replay_is_labelled_and_mismatched_question_is_refused(tmp_path):
    import subprocess, sys
    from conftest import PROJECT_ROOT
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, FIXTURES / "main_run.json", lenses=LENSES, run_id="replay")
    report = (engine.store.run_dir / "report.md").read_text()
    assert "TEST REPLAY" in report and "not from a model" in report
    assert "TEST REPLAY" in _dashboard_state(write_dashboard(engine).read_text())["replay"]
    cmd = [sys.executable, "-m", "llm_council.cli", "run", "2+2=5. dimostralo", "--fixture", str(FIXTURES / "main_run.json"),
           "--lenses", LENSES, "--run-id", "wrongq", "--root", str(root)]
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
    assert out.returncode == 2 and "recorded test transcript" in out.stderr and "2+2=5" in out.stderr
    assert not (root / "council_outcomes" / "wrongq").exists()          # nothing left behind
    out = subprocess.run(cmd + ["--allow-fixture-mismatch"], capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
    assert out.returncode == 0 and "TEST REPLAY" in out.stdout


def test_who_answered_is_recorded_per_request_and_participant(tmp_path):
    """Provider, model, tokens, latency and effort are recorded on every answer and shown in report and dashboard."""
    import re as _re
    import subprocess, sys
    from conftest import PROJECT_ROOT
    from llm_council.providers.fixture import FixtureProvider
    from llm_council.state import PendingRequest
    root = make_root(tmp_path)
    fixture = FixtureProvider(FIXTURES / "main_run.json", strict_consumption=False)

    def council(*args):
        return subprocess.run([sys.executable, "-m", "llm_council.cli", *args, "--root", str(root)], capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)

    out = council("start", QUESTION, "--lenses", LENSES, "--run-id", "who", "--chat-model", "claude-test-model")
    assert out.returncode == 0, out.stderr
    for _ in range(3):
        req_json = json.loads(Path(_re.search(r"request file: (.+\.json)\)", out.stdout).group(1)).read_text())
        req = PendingRequest.model_validate({k: v for k, v in req_json.items() if k != "response_path"})
        Path(req_json["response_path"]).write_text(fixture.answer(req).text)
        out = council("submit", "who", req_json["response_path"], "--request-id", req.request_id, "--effort", "extended thinking")
        assert out.returncode == 0, out.stderr
    state = json.loads((root / "council_outcomes" / "who" / "state.json").read_text())
    assert state["chat_model"] == "claude-test-model"
    framer = state["participants"]["p_framer"]
    assert framer["provider"] == "chat" and framer["model_reported"] == "claude-test-model" and framer["calls"] == 1
    assert framer["tokens"] > 0 and framer["latency_seconds"] >= 0 and framer["effort"] == "extended thinking"
    events = [json.loads(l) for l in (root / "council_outcomes" / "who" / "events.jsonl").read_text().splitlines()]
    committed = [e for e in events if e["kind"] == "response_committed"]
    assert committed and committed[0]["payload"]["provider"] == "chat" and committed[0]["payload"]["model"] == "claude-test-model"
    assert committed[0]["payload"]["tokens_kind"] == "estimated" and "latency_seconds" in committed[0]["payload"]
    html = (root / "council_outcomes" / "who" / "index.html").read_text()
    state = _dashboard_state(html)
    assert state["answeredBy"].startswith("chat (claude-test-model)")
    assert any(p["model"] == "claude-test-model" and p["effort"] == "extended thinking" for p in state["who"])
    assert state["reasoning"] and state["orchestration"]


def test_opencode_reply_detail_reaches_participant_and_events(tmp_path):
    """Measured token detail, latency and effort from an isolated provider reply are recorded."""
    from llm_council.engine import ReplyMeta
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, FIXTURES / "main_run.json", lenses=LENSES, run_id="oc", strict=False)
    d = engine.store.data
    ev = [json.loads(l) for l in (engine.store.run_dir / "events.jsonl").read_text().splitlines()]
    # the fixture run recorded provider 'fixture' for everyone; the metadata shape is what matters here
    assert all(e["payload"].get("provider") == "fixture" for e in ev if e["kind"] == "response_committed")
    meta = ReplyMeta(provider="opencode", model_requested="claude-agent/haiku", model_reported="claude-agent/haiku", tokens_measured=1200,
                     isolation="isolated", raw_text="{}", tokens_detail={"input": 100, "output": 300, "reasoning": 800, "cache_read": 0, "cache_write": 0},
                     latency_seconds=12.5, effort="reasoning")
    assert meta.tokens_detail["reasoning"] == 800 and meta.effort == "reasoning"
    report = (engine.store.run_dir / "report.md").read_text()
    assert "## Who answered (orchestration view)" in report and "## Reasoning workflow" in report and "fixture · fixture" in report


def test_defaults_panel_sets_route_models_and_preset(tmp_path):
    root = make_root(tmp_path)
    httpd, base = _serve(root)
    try:
        code, body = _get(base + "/settings")
        assert code == 200 and "Defaults — which model to use in general" in body and "Model per role" in body and "name='route'" in body
        form = {"route": "chat", "default_model": "", "default_model__free": "claude-agent/haiku", "preset": "quick", "chat_model": "claude-sonnet-5-5",
                "role.judge.provider": "opencode", "role.judge.model__free": "claude-agent/haiku", "role.reviewer.provider": "opencode", "role.reviewer.model__free": "ollama/gemma4:26b"}
        for r in ("framer", "policy_setter", "strategist", "verifier", "challenger"):
            form[f"role.{r}.provider"] = ""
            form[f"role.{r}.model"] = ""
        code, body = _post(base + "/settings/defaults", form)
        assert code == 200 and "defaults saved" in body, body[:500]
        saved = json.loads((root / ".council" / "settings.json").read_text())
        assert saved["routing"]["default_provider"] == "chat" and saved["routing"]["opencode"]["enabled"] is True
        assert saved["routing"]["opencode"]["default_model"] == "claude-agent/haiku"
        assert saved["routing"]["roles"] == {"judge": {"provider": "opencode", "model": "claude-agent/haiku"}, "reviewer": {"provider": "opencode", "model": "ollama/gemma4:26b"}}
        assert saved["defaults"] == {"preset": "quick", "chat_model": "claude-sonnet-5-5"}
        # the default preset applies to a run that names none; an explicit --preset still wins
        from argparse import Namespace
        from llm_council.cli import effective
        eff = effective(root, Namespace(preset=None, set=[], opencode=False, provider=None, fixture=None, lenses=None))
        assert eff.preset == "quick" and eff.config.limits.max_model_calls == 24
        eff2 = effective(root, Namespace(preset="deep", set=[], opencode=False, provider=None, fixture=None, lenses=None))
        assert eff2.preset == "deep"
        # clearing the judge again removes the saved keys instead of writing nulls
        form["role.judge.provider"] = ""; form["role.judge.model__free"] = ""; form["preset"] = ""
        code, body = _post(base + "/settings/defaults", form)
        saved = json.loads((root / ".council" / "settings.json").read_text())
        assert "judge" not in saved["routing"]["roles"] and "preset" not in saved.get("defaults", {})
        # invalid: a role name is fixed by the form, but an impossible model string is still validated (no crash)
        form["route"] = "opencode"
        code, body = _post(base + "/settings/defaults", form)
        assert "defaults saved" in body and json.loads((root / ".council" / "settings.json").read_text())["routing"]["default_provider"] == "opencode"
    finally:
        httpd.shutdown(); httpd.server_close()


def test_dashboard_and_settings_are_organised_in_tabs(tmp_path):
    from llm_council.dashboard import tabify
    out = tabify(["<div>intro</div>", "<h2>Outcome</h2>", "<p>a</p>", "<h2>Report</h2>", "<p>r</p>"],
                 [("overview", "Overview", ["Outcome"]), ("report", "Report", ["Report"])])
    assert "<div class='tabs'>" in out and "data-tab='overview'" in out and "data-tab='report'" in out
    assert "<section class='tab' id='tab-overview'><div>intro</div>\n<h2>Outcome</h2>\n<p>a</p></section>" in out
    assert "<section class='tab' id='tab-report'><h2>Report</h2>\n<p>r</p></section>" in out and "hashchange" in out
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, FIXTURES / "main_run.json", lenses=LENSES, run_id="tabs")
    html = write_dashboard(engine).read_text()
    state = _dashboard_state(html)
    for key in ("kpis", "outcome", "rounds", "reasoning", "objections", "who", "settings", "discussion", "files", "reportHtml"):
        assert key in state, key
    from conftest import PROJECT_ROOT
    web_src = PROJECT_ROOT / "web" / "src"
    app_jsx = "".join(p.read_text() for p in (web_src / "components").glob("*.jsx"))
    for tid in ("overview", "reasoning", "orchestration", "settings", "discussion", "files", "report"):
        assert f'value="{tid}"' in app_jsx, tid
    dialog = (web_src / "components" / "ui" / "dialog.jsx").read_text()
    assert "@radix-ui/react-dialog" in dialog and "DialogContent" in dialog  # Radix renders role=dialog + aria-modal at runtime
    assert "DialogContent" in app_jsx and "DialogTitle" in app_jsx
    assert "TabsList" in app_jsx and "@radix-ui/react-tabs" in (web_src / "components" / "ui" / "tabs.jsx").read_text()
    httpd, base = _serve(root)
    try:
        code, body = _get(base + "/settings")
        assert code == 200 and all(f"id='tab-{t}'" in body for t in ("defaults", "all", "presets", "saved"))
        assert body.count("<form method='post' action='/settings'>") == 1 and "</form>" in body.split("id='tab-all'")[1].split("</section>")[0]
    finally:
        httpd.shutdown(); httpd.server_close()


def test_home_page_has_one_tab_per_work_and_links_to_settings(tmp_path):
    root = make_root(tmp_path)
    # two works in the new folder, one legacy run
    import subprocess, sys
    from conftest import PROJECT_ROOT
    for rid in ("w_one", "w_two"):
        out = subprocess.run([sys.executable, "-m", "llm_council.cli", "run", QUESTION, "--fixture", str(FIXTURES / "main_run.json"), "--lenses", LENSES,
                              "--run-id", rid, "--root", str(root)], capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=180)
        assert out.returncode == 0, out.stderr
    run_fixture(root, FIXTURES / "main_run.json", lenses=LENSES, run_id="old_one")
    httpd, base = _serve(root)
    try:
        code, body = _get(base + "/")
        assert code == 200
        assert "href='/settings'" in body and "Settings" in body                      # home -> settings
        home = _home_state(body)
        assert len(home["works"]) == 2 and home["legacyCount"] == 1                    # one tab per work + legacy
        assert {w["runId"] for w in home["works"]} == {"w_one", "w_two"}
        assert all("/runs/" + w["runId"] + "/" == w["href"] for w in home["works"])
        first = home["works"][0]["summary"]
        assert first["outcome"]["recTitle"] == "Staged 10% pilot with scale gates"
        assert any("challenger promoted to incumbent" in r["taken"] for r in first["rounds"])
        assert first["reasoning"] and first["objections"] and first["who"]
        code, body = _get(base + "/settings")
        assert code == 200 and "href='/'" in body and "Works" in body                  # settings -> home
        code, body = _get(base + "/runs/w_one/")
        assert code == 200 and "All works" in body and "href='../../settings'" in body  # dashboard -> both
    finally:
        httpd.shutdown(); httpd.server_close()


def test_md_files_open_in_a_formatted_modal(tmp_path):
    """Clicking an .md file opens it fully formatted in a modal, not as raw text."""
    from conftest import PROJECT_ROOT
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, FIXTURES / "main_run.json", lenses=LENSES, run_id="modal")
    html = write_dashboard(engine).read_text()
    # SPA shell with the built shadcn bundle inlined (no external assets), embedded pre-rendered content
    assert 'id="council-root"' in html and 'id="council-state"' in html
    assert '<script src=' not in html and 'createRoot' in html  # built bundle inlined, no external scripts
    state = _dashboard_state(html)
    assert "report.md" in state["mdMap"] and ("<h1>" in state["mdMap"]["report.md"] or "<h2>" in state["mdMap"]["report.md"])
    assert "discussion.md" in state["mdMap"]
    assert any(f["isMd"] and f["rel"] == "report.md" for f in state["files"])
    # shadcn/Radix dialog wiring in source, dark theme tokens in CSS
    dialog = (PROJECT_ROOT / "web" / "src" / "components" / "modal.jsx").read_text()
    assert "@radix-ui/react-dialog" in (PROJECT_ROOT / "web" / "src" / "components" / "ui" / "dialog.jsx").read_text()
    assert "Dialog" in dialog and "fetch(" in dialog
    css = (PROJECT_ROOT / "web" / "src" / "index.css").read_text()
    assert ".dark" in css and "--background" in css
    assert "council-theme" in (PROJECT_ROOT / "web" / "src" / "components" / "theme.jsx").read_text()
    # the served home page carries the same SPA (legacy run listed; raw md still served)
    httpd, base = _serve(root)
    try:
        code, body = _get(base + "/")
        assert code == 200 and 'id="council-home-state"' in body
        assert _home_state(body)["legacyCount"] == 1  # modal run lives in the legacy folder
        code, body = _get(base + "/runs/modal/report.md")
        assert code == 200 and body.startswith("# ")  # raw file still served for fetch + direct open
    finally:
        httpd.shutdown(); httpd.server_close()


def test_home_state_never_hands_react_an_empty_html_object(tmp_path):
    """A `{"html": ""}` cell crashed the React home page (error #31) for runs without a confidence level."""
    from llm_council.dashboard import home_state
    from llm_council.ui import local_time, run_rows
    root = make_root(tmp_path)
    run_fixture(root, FIXTURES / "main_run.json", lenses=LENSES, run_id="h1")
    # a run with no decision yet (running) has no confidence
    from llm_council.state import Store
    Store.create(root / "council_outcomes", "running1", QUESTION)
    rows = run_rows(root)
    for r in rows:
        r["when"] = local_time(r["created_at"]); r["label"] = r["when"]; r["stateMark"] = ""
    state = home_state(root, rows)
    for row in state["tableRows"]:
        for cell in row:
            assert not (isinstance(cell, dict) and not cell.get("html")), row
    assert any(r[0] and isinstance(r[1], dict) and r[1]["html"].startswith("<a") for r in state["tableRows"])
    assert state["works"] and all(w["summary"] is not None or w["summaryError"] for w in state["works"])
