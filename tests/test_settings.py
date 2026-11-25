from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import PROJECT_ROOT, make_root
from llm_council import settings as st
from llm_council.config import load_effective_config


def council(root: Path, *args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "llm_council.cli", *args, "--root", str(root)]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)


def test_set_validates_and_writes_saved_layer(tmp_path):
    root = make_root(tmp_path)
    saved, eff = st.set_values(root, ["limits.max_rounds=3", "judge.jury_size=2", "routing.roles.judge.provider=opencode"])
    assert json.loads(st.saved_path(root).read_text()) == saved
    assert eff.config.limits.max_rounds == 3 and eff.provenance["limits.max_rounds"] == "saved"
    assert eff.config.judge.jury_size == 2
    # saved beats project; preset and override still beat saved
    eff2 = load_effective_config(root, preset="quick", overrides={"judge": {"jury_size": 3}})
    assert eff2.config.limits.max_rounds == 2 and eff2.config.judge.jury_size == 3


def test_invalid_value_is_refused_and_file_untouched(tmp_path):
    root = make_root(tmp_path)
    st.set_values(root, ["limits.max_rounds=3"])
    before = st.saved_path(root).read_text()
    try:
        st.set_values(root, ["limits.min_rounds=9"])  # min > max is invalid
        assert False, "expected SettingsError"
    except st.SettingsError as e:
        assert "min_rounds" in str(e)
    assert st.saved_path(root).read_text() == before
    try:
        st.set_values(root, ["routing.roles.janitor.provider=chat"])
        assert False
    except st.SettingsError:
        pass
    try:
        st.set_values(root, ["judge.jury_size=0"])
        assert False
    except st.SettingsError:
        pass


def test_unset_and_reset(tmp_path):
    root = make_root(tmp_path)
    st.set_values(root, ["limits.max_rounds=3", "review.panel_size=1"])
    saved, eff = st.unset_values(root, ["limits.max_rounds"])
    assert "limits" not in saved and eff.config.limits.max_rounds == 4 and eff.provenance["limits.max_rounds"] == "project"
    assert st.reset(root) and not st.saved_path(root).exists()
    assert not st.reset(root)


def test_settings_cli_commands(tmp_path):
    root = make_root(tmp_path)
    out = council(root, "settings", "show")
    assert out.returncode == 0 and "absent" in out.stdout and "precedence:" in out.stdout
    out = council(root, "settings", "set", "limits.max_rounds=3", "routing.opencode.enabled=true")
    assert out.returncode == 0, out.stderr
    assert "limits.max_rounds = 3  <- saved" in out.stdout and "opencode ENABLED" in out.stdout
    out = council(root, "settings", "set", "limits.max_rounds=0")
    assert out.returncode == 2 and "nothing written" in out.stderr
    out = council(root, "settings", "show", "--section", "limits")
    assert "limits.max_rounds = 3  <- saved" in out.stdout and "judge.jury_size" not in out.stdout
    out = council(root, "settings", "routes")
    assert out.returncode == 0 and "judge" in out.stdout and "enabled=True" in out.stdout
    out = council(root, "settings", "validate")
    assert out.returncode == 0 and "VALID" in out.stdout
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"limits": {"max_model_calls": 2, "finalisation_reserve_calls": 3}}))
    out = council(root, "settings", "validate", str(bad))
    assert out.returncode == 2 and "INVALID" in out.stderr
    out = council(root, "settings", "presets")
    assert "first_pass" in out.stdout and "quick" in out.stdout
    out = council(root, "settings", "wizard")
    assert out.returncode == 0 and "limits.max_rounds" in out.stdout and "[current 3" in out.stdout
    out = council(root, "settings", "wizard", "--answer", "review.panel_size=1", "--answer", "judge.jury_size=2")
    assert out.returncode == 0 and "review.panel_size = 1  <- saved" in out.stdout
    out = council(root, "settings", "wizard", "--answer", "nonsense.key=1")
    assert out.returncode == 2
    out = council(root, "settings", "unset", "limits.max_rounds")
    assert out.returncode == 0 and "limits.max_rounds = 4  <- project" in out.stdout
    out = council(root, "settings", "reset")
    assert out.returncode == 2
    out = council(root, "settings", "reset", "--yes")
    assert out.returncode == 0 and "removed" in out.stdout
    # the effective config seen by a run reflects saved settings
    council(root, "settings", "set", "limits.max_rounds=3")
    out = council(root, "config", "show")
    assert "limits.max_rounds = 3  <- saved" in out.stdout
