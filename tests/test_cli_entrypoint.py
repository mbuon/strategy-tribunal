"""The chat entry point gate: drive the exact commands the /council skill runs
(`council start --args-file` -> write response -> the printed SUBMIT_COMMAND line
executed through a shell ...) with the fixture standing in for the chat model.
Also checks idempotent duplicate submission, `status`, `report`, `cancel` and
`config show`."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from conftest import FIXTURES, LENSES, PROJECT_ROOT, QUESTION, make_root
from llm_council.cli import split_args_text
from llm_council.providers.fixture import FixtureProvider
from llm_council.state import PendingRequest


def council(root: Path, *args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "llm_council.cli", *args, "--root", str(root)]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)


def shell(root: Path, line: str) -> subprocess.CompletedProcess:
    """Run a printed command line exactly as the chat model would, through a shell.
    `.venv/bin/council` is replaced by the test interpreter so the test does not depend on the project venv."""
    line = line.replace(".venv/bin/council ", f"{shlex.quote(sys.executable)} -m llm_council.cli ", 1) + f" --root {shlex.quote(str(root))}"
    env = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT / "src"))
    return subprocess.run(line, shell=True, capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120, env=env)


def test_split_args_text():
    q, flags = split_args_text('Should we "really" shift budget? --preset quick --opencode --set limits.max_rounds=3 --lenses a,b')
    assert q == "Should we really shift budget?" and flags["preset"] == "quick" and flags["opencode"] is True
    assert flags["set"] == ["limits.max_rounds=3"] and flags["lenses"] == "a,b"
    q2, f2 = split_args_text("plain question with $dollar and `ticks` --unknown-flag kept")
    assert "--unknown-flag" in q2 and f2["set"] == []


def test_step_mode_end_to_end_through_cli(tmp_path):
    root = make_root(tmp_path, name="proj with space & amp")  # the real root has both characters
    fixture = FixtureProvider(FIXTURES / "main_run.json")
    inbox = tmp_path / "inbox.txt"
    inbox.write_text(f"{QUESTION} --lenses {LENSES} --run-id cli\n")
    out = council(root, "start", "--args-file", str(inbox))
    assert out.returncode == 0, out.stderr
    assert "=== COUNCIL REQUEST req_0001" in out.stdout and "kind=frame" in out.stdout
    run_dir = root / "council_outcomes" / "cli"
    steps = 0
    text = out.stdout
    while "=== COUNCIL REQUEST" in text:
        m = re.search(r"request file: (.+\.json)\)", text)
        req_json = json.loads(Path(m.group(1)).read_text())
        req = PendingRequest.model_validate({k: v for k, v in req_json.items() if k != "response_path"})
        reply = fixture.answer(req)  # the fixture plays the chat model
        Path(req_json["response_path"]).write_text(reply.text)
        submit_line = re.search(r"^SUBMIT_COMMAND: (.+)$", text, re.M).group(1)
        assert "--request-id " + req.request_id in submit_line
        assert shlex.split(submit_line)[3] == req_json["response_path"]  # the quoted path round-trips through a shell
        out = shell(root, submit_line)
        assert out.returncode == 0, out.stderr
        text = out.stdout
        steps += 1
        assert steps < 60
    assert "=== RUN COMPLETE (stable) ===" in text
    assert "CONDITIONAL: Staged 10% pilot with scale gates" in text
    assert (run_dir / "report.md").exists() and (run_dir / "decision.json").exists()
    fixture.finish()
    decision = json.loads((run_dir / "decision.json").read_text())
    assert decision["kind"] == "conditional" and decision["stop_reason"] == "stable"
    assert decision["budget"]["model_calls_used"] == 32
    # idempotent duplicate submission of an already-answered request
    dup = shell(root, submit_line)
    assert dup.returncode == 0 and "duplicate submission" in dup.stdout
    st = council(root, "status", "cli")
    assert st.returncode == 0 and "state=COMPLETE" in st.stdout and "calls 32/60 (measured)" in st.stdout
    rep = council(root, "report", "cli")
    assert rep.returncode == 0 and "## Round-by-round decision quality" in rep.stdout


def test_cancel_through_cli(tmp_path):
    root = make_root(tmp_path)
    fixture = FixtureProvider(FIXTURES / "main_run.json", strict_consumption=False)
    out = council(root, "start", QUESTION, "--lenses", LENSES, "--run-id", "cx")
    assert out.returncode == 0, out.stderr
    for _ in range(4):
        m = re.search(r"request file: (.+\.json)\)", out.stdout)
        req_json = json.loads(Path(m.group(1)).read_text())
        req = PendingRequest.model_validate({k: v for k, v in req_json.items() if k != "response_path"})
        Path(req_json["response_path"]).write_text(fixture.answer(req).text)
        out = shell(root, re.search(r"^SUBMIT_COMMAND: (.+)$", out.stdout, re.M).group(1))
        assert out.returncode == 0, out.stderr
    out = council(root, "cancel", "cx")
    assert out.returncode == 0, out.stderr
    assert "RUN CANCELLED" in out.stdout
    decision = json.loads((root / "council_outcomes" / "cx" / "decision.json").read_text())
    assert decision["stop_reason"] == "cancelled" and decision["completed_phases"]
    again = council(root, "cancel", "cx")
    assert "already finished" in again.stdout


def test_config_show_prints_provenance_and_enforcement(tmp_path):
    root = make_root(tmp_path)
    out = council(root, "config", "show", "--preset", "quick", "--set", "limits.max_rounds=3", "--opencode")
    assert out.returncode == 0, out.stderr
    assert "limits.max_rounds = 3  <- override" in out.stdout
    assert "review.panel_size = 1  <- preset:quick" in out.stdout
    assert "judge.jury_size = 1  <- project" in out.stdout
    assert "opencode ENABLED" in out.stdout
    assert "max_cost_usd" in out.stdout and "unavailable" in out.stdout


def test_autonomous_run_requires_fixture_or_opencode(tmp_path):
    root = make_root(tmp_path)
    out = council(root, "run", QUESTION, "--run-id", "nofx")
    assert out.returncode == 2 and "needs --fixture" in out.stderr
