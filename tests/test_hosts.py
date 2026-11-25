"""Hosts beyond Claude Code: the MCP server (Claude Desktop and other tool-using chats) and the copy-paste loop
(`council submit <run> -` reading the reply from stdin) that any chat without tools can drive."""
from __future__ import annotations

import json
import re
import subprocess
import sys

from conftest import FIXTURES, LENSES, PROJECT_ROOT, QUESTION, make_root

sys.path.insert(0, str(FIXTURES))
from build_fixtures import FRAME, POLICY  # noqa: E402


def _rpc(proc, msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if "id" not in msg:
        return None
    line = proc.stdout.readline()
    assert line, "server closed the stream"
    return json.loads(line)


def test_mcp_server_speaks_the_protocol_and_drives_a_run(tmp_path):
    root = make_root(tmp_path)
    proc = subprocess.Popen([sys.executable, "-m", "llm_council.cli", "mcp", "--root", str(root)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(PROJECT_ROOT))
    try:
        init = _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}})
        assert init["result"]["protocolVersion"] == "2025-06-18" and init["result"]["serverInfo"]["name"] == "strategy-tribunal"
        assert "council_start" in init["result"]["instructions"] and "builds_on" in init["result"]["instructions"]
        _rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}
        tools = _rpc(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]
        names = {t["name"] for t in tools}
        assert {"council_start", "council_submit", "council_next", "council_status", "council_report", "council_cancel", "council_runs"} <= names
        assert all("inputSchema" in t and "description" in t for t in tools)
        # only a short list of flags passes through the tool: fixtures, providers and config overrides are refused
        for bad_args in (f"{QUESTION} --fixture x.json", f"{QUESTION} --provider fixture", f"{QUESTION} --set routing.opencode.binary=/tmp/evil"):
            bad = _rpc(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "council_start", "arguments": {"args": bad_args}}})
            assert bad["result"]["isError"] is True and "refused" in bad["result"]["content"][0]["text"], bad_args
        assert not (root / "council_outcomes").exists() or not any((root / "council_outcomes").iterdir())
        # a chat-routed run: start, read the first request, submit the framer's reply, get the next request
        started = _rpc(proc, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                              "params": {"name": "council_start", "arguments": {"args": f"{QUESTION} --lenses {LENSES} --run-id mcp",
                                                                                "chat_model": "test-model"}}})
        text = started["result"]["content"][0]["text"]
        assert started["result"]["isError"] is False, text
        assert "=== COUNCIL REQUEST req_0001" in text and "kind=frame" in text and "How the council works" in text
        sub = _rpc(proc, {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                          "params": {"name": "council_submit", "arguments": {"run_id": "mcp", "request_id": "req_0001", "response": FRAME}}})
        text = sub["result"]["content"][0]["text"]
        assert sub["result"]["isError"] is False, text
        assert "=== COUNCIL REQUEST req_0002" in text and "kind=policy" in text
        status = _rpc(proc, {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "council_status", "arguments": {"run_id": "mcp"}}})
        assert "POLICY" in status["result"]["content"][0]["text"]
        runs = _rpc(proc, {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "council_runs", "arguments": {}}})
        assert "mcp" in runs["result"]["content"][0]["text"]
        unknown = _rpc(proc, {"jsonrpc": "2.0", "id": 9, "method": "nope"})
        assert unknown["error"]["code"] == -32601
        assert (root / "council_outcomes" / "mcp" / "responses" / "req_0001.json").exists()
        who = json.loads((root / "council_outcomes" / "mcp" / "state.json").read_text())["participants"]["p_framer"]
        assert who["provider"] == "chat" and who["model_reported"] == "test-model"
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
        assert proc.returncode == 0, proc.stderr.read()


def test_copy_paste_loop_submits_a_reply_from_stdin(tmp_path):
    root = make_root(tmp_path)
    cmd = [sys.executable, "-m", "llm_council.cli"]
    out = subprocess.run([*cmd, "start", "--args", f"{QUESTION} --lenses {LENSES} --run-id paste --provider chat", "--root", str(root)],
                         capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
    assert out.returncode == 0, out.stderr
    assert "=== COUNCIL REQUEST req_0001" in out.stdout
    out = subprocess.run([*cmd, "submit", "paste", "-", "--request-id", "req_0001", "--root", str(root)],
                         input=json.dumps(FRAME), capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
    assert out.returncode == 0, out.stderr
    assert "=== COUNCIL REQUEST req_0002" in out.stdout and "kind=policy" in out.stdout
    out = subprocess.run([*cmd, "submit", "paste", "-", "--request-id", "req_0002", "--root", str(root)],
                         input="```json\n" + json.dumps(POLICY) + "\n```\n", capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)
    assert out.returncode == 0, out.stderr
    assert re.search(r"=== COUNCIL REQUEST req_0003", out.stdout)   # a fenced paste is accepted too


def test_mcp_submit_refuses_ids_that_leave_the_run_folder(tmp_path):
    from llm_council.mcp import call_tool
    root = make_root(tmp_path)
    for run_id, request_id in [("../../etc", "req_0001"), ("mcp", "../x"), ("mcp", "req_0001/../../y"), ("", "req_0001")]:
        text, is_error = call_tool("council_submit", {"run_id": run_id, "request_id": request_id, "response": {}}, root)
        assert is_error and text.startswith("error:"), (run_id, request_id, text)
    assert not list(tmp_path.rglob("*.mcp.json"))


def test_ui_requires_a_token_off_loopback_and_blocks_cross_origin_and_dangerous_keys(tmp_path):
    import threading, urllib.request, urllib.error
    from http.server import ThreadingHTTPServer
    from llm_council.ui import Handler, web_form_allowed
    root = make_root(tmp_path)
    Handler.root = root
    Handler.token = "s3cret"
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{port}"
        try:
            urllib.request.urlopen(base + "/api/health", timeout=5)
            raise AssertionError("no token must be refused")
        except urllib.error.HTTPError as e:
            assert e.code == 401
        req = urllib.request.Request(base + "/api/health", headers={"Authorization": "Bearer s3cret"})
        assert urllib.request.urlopen(req, timeout=5).status == 200
        # cross-origin state change is refused even with the token
        req = urllib.request.Request(base + "/settings", data=b"limits.max_rounds=3", method="POST",
                                     headers={"Authorization": "Bearer s3cret", "Origin": "http://evil.example"})
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("cross-origin POST must be refused")
        except urllib.error.HTTPError as e:
            assert e.code == 403
        # the first visit with ?token= sets the cookie and redirects
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        try:
            opener.open(base + "/?token=s3cret", timeout=5)
        except urllib.error.HTTPError as e:
            assert e.code == 302 and "council_token=s3cret" in e.headers.get("Set-Cookie", "")
        # DNS rebinding: a Host header that is not this server is refused even with the token
        req = urllib.request.Request(base + "/api/health", headers={"Authorization": "Bearer s3cret", "Host": "evil.example"})
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("foreign Host must be refused")
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        httpd.shutdown()
        Handler.token = None
    assert web_form_allowed({"routing.opencode.binary": "/tmp/x"}) and web_form_allowed({"limits.max_rounds": "3"}) is None
    # writing the parent object, or the whole section, is refused too
    assert web_form_allowed({"routing.opencode": '{"binary": "/tmp/x"}'}) and web_form_allowed({"routing": '{"opencode": {"binary": "x"}}'})
    assert web_form_allowed({"storage": '{"legacy_runs_root": "/etc"}'}) and web_form_allowed({"routing.opencode.default_model": "x"}) is None
    assert web_form_allowed({"routing.opencode.agent": "x"}) and web_form_allowed({"limits.max_rounds=3": ""}) and web_form_allowed({"a=b.c": "1"})


def test_mcp_question_is_never_parsed_as_options(tmp_path):
    from llm_council.mcp import call_tool
    from llm_council.cli import split_args_text
    root = make_root(tmp_path)
    text, is_error = call_tool("council_start", {"args": "--help me decide --preset quick --run-id dash"}, root)
    assert not is_error, text
    assert "=== COUNCIL REQUEST req_0001" in text
    assert json.loads((root / "council_outcomes" / "dash" / "state.json").read_text())["question"] == "--help me decide"
    q, flags = split_args_text("What now? --preset=deep --lenses=regret")
    assert q == "What now?" and flags["preset"] == "deep" and flags["lenses"] == "regret"

