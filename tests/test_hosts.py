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
        # fixtures are refused through the tool, as through the skill
        bad = _rpc(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                          "params": {"name": "council_start", "arguments": {"args": f"{QUESTION} --fixture x.json"}}})
        assert bad["result"]["isError"] is True and "fixture" in bad["result"]["content"][0]["text"]
        # a chat-routed run: start, read the first request, submit the framer's reply, get the next request
        started = _rpc(proc, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                              "params": {"name": "council_start", "arguments": {"args": f"{QUESTION} --lenses {LENSES} --run-id mcp --provider chat",
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
