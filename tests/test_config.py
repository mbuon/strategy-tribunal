from __future__ import annotations

import pytest
from pydantic import ValidationError

from conftest import make_root
from llm_council.config import PRESETS, CouncilConfig, load_effective_config, parse_set_overrides


def test_precedence_defaults_project_saved_preset_override(tmp_path):
    root = make_root(tmp_path, project_config={"limits": {"max_rounds": 5, "min_rounds": 1}, "review": {"panel_size": 3}},
                     saved={"review": {"panel_size": 2}, "judge": {"jury_size": 2}})
    eff = load_effective_config(root, preset="quick", overrides={"judge": {"jury_size": 3}})
    c = eff.config
    assert c.limits.max_rounds == 2 and eff.provenance["limits.max_rounds"] == "preset:quick"   # preset beats project
    assert c.review.panel_size == 1 and eff.provenance["review.panel_size"] == "preset:quick"   # preset beats saved
    assert c.judge.jury_size == 3 and eff.provenance["judge.jury_size"] == "override"           # override beats preset/saved
    assert c.judge.materiality_threshold == 0.5 and eff.provenance["judge.materiality_threshold"] == "defaults"
    assert eff.layers_present == {"defaults": True, "project": True, "saved": True, "preset": True, "override": True}


def test_saved_beats_project(tmp_path):
    root = make_root(tmp_path, project_config={"review": {"panel_size": 3}}, saved={"review": {"panel_size": 4}})
    eff = load_effective_config(root)
    assert eff.config.review.panel_size == 4 and eff.provenance["review.panel_size"] == "saved"


def test_invalid_values_rejected(tmp_path):
    root = make_root(tmp_path, project_config={"limits": {"min_rounds": 5, "max_rounds": 2}})
    with pytest.raises(ValidationError):
        load_effective_config(root)
    with pytest.raises(ValidationError):
        CouncilConfig.model_validate({"routing": {"roles": {"janitor": {}}}})
    with pytest.raises(ValidationError):
        CouncilConfig.model_validate({"judge": {"jury_size": 0}})
    with pytest.raises(ValidationError):
        CouncilConfig.model_validate({"unknown_section": {}})


def test_role_routing_defaults_and_override():
    cfg = CouncilConfig.model_validate({"routing": {"default_provider": "chat", "roles": {"judge": {"provider": "opencode", "model": "x/y"}},
                                                    "opencode": {"enabled": True}}})
    assert cfg.routing.for_role("judge").provider == "opencode" and cfg.routing.for_role("judge").model == "x/y"
    assert cfg.routing.for_role("framer").provider == "chat"


def test_presets_are_valid_and_first_pass_skips_review():
    for name in PRESETS:
        cfg = CouncilConfig.model_validate(PRESETS[name])
        assert cfg.protocol_version == "1.0"
    fp = CouncilConfig.model_validate(PRESETS["first_pass"])
    assert fp.review.panel_size == 0 and fp.limits.max_rounds == 1 and fp.limits.max_leader_challenges == 0


def test_parse_set_overrides():
    ov = parse_set_overrides(["limits.max_rounds=3", "routing.opencode.enabled=true", "routing.roles.judge.model=a/b"])
    assert ov == {"limits": {"max_rounds": 3}, "routing": {"opencode": {"enabled": True}, "roles": {"judge": {"model": "a/b"}}}}
    with pytest.raises(ValueError):
        parse_set_overrides(["novalue"])


def test_judge_config_hash_changes_with_judge_settings():
    a = CouncilConfig().judge_config_hash()
    b = CouncilConfig.model_validate({"judge": {"materiality_threshold": 0.7}}).judge_config_hash()
    c = CouncilConfig.model_validate({"limits": {"max_rounds": 6}}).judge_config_hash()
    assert a != b and a == c
