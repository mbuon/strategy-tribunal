from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from conftest import make_root
from llm_council import settings as st
from llm_council.config import CouncilConfig, load_effective_config
from llm_council.ontology import EventKind
from llm_council.phases import Applier, FrameResponse, PolicyResponse
from llm_council.state import PendingRequest, RunData, Store


def _policy_response() -> PolicyResponse:
    return PolicyResponse.model_validate({
        "criteria": [
            {"id": "crit_gate_budget", "name": "Budget gate", "kind": "gate"},
            {"name": "Cost efficiency", "kind": "score", "weight": 1},
            {"id": "crit_speed", "name": "Speed", "kind": "score", "weight": 1},
            {"name": "Risk", "kind": "score", "weight": 2},
        ]
    })


def _store_with_brief(tmp_path) -> Store:
    store = Store(tmp_path / "r", RunData(run_id="r", question="q"))
    req = PendingRequest(request_id="req_1", attempt=1, kind="frame", role="framer", round=0, state="FRAMING",
                         participant_id="p_framer", dedup_key="k")
    Applier(store, req).apply_frame(FrameResponse(decision_statement="decide something concrete here", objectives=["o"],
                                                  time_horizon="Q1", stakes="high", reversibility="costly"))
    return store


def test_weight_overrides_apply_by_name_or_id_and_are_recorded(tmp_path):
    store = _store_with_brief(tmp_path)
    req = PendingRequest(request_id="req_2", attempt=1, kind="policy", role="policy_setter", round=0, state="POLICY",
                         participant_id="p_policy_setter", dedup_key="k2")
    pol = Applier(store, req).apply_policy(_policy_response(), materiality=0.5, margin=0.0, unverified_policy="penalty",
                                           judge_hash="h", weight_overrides={"Cost Efficiency": 5, "crit_speed": 3,
                                                                              "Budget gate": 9, "nonexistent": 1})
    by_id = {c.id: c for c in pol.criteria}
    assert by_id["crit_cost_efficiency"].weight == 5 and by_id["crit_speed"].weight == 3 and by_id["crit_risk"].weight == 2
    assert by_id["crit_gate_budget"].weight == 0  # gates never take a weight
    assert pol.weight_overrides_applied == ["Cost Efficiency", "crit_speed"]
    assert sorted(pol.weight_overrides_unapplied) == ["Budget gate", "nonexistent"]
    w = pol.normalised_weights()
    assert w["crit_cost_efficiency"] == pytest.approx(0.5) and w["crit_speed"] == pytest.approx(0.3) and w["crit_risk"] == pytest.approx(0.2)
    events = [json.loads(l) for l in (store.run_dir / "events.jsonl").read_text().splitlines()]
    ev = [e for e in events if e["kind"] == EventKind.POLICY_WEIGHTS_OVERRIDDEN.value]
    assert ev and ev[-1]["payload"]["applied"] == ["Cost Efficiency", "crit_speed"]


def test_no_overrides_leaves_policy_untouched(tmp_path):
    store = _store_with_brief(tmp_path)
    req = PendingRequest(request_id="req_2", attempt=1, kind="policy", role="policy_setter", round=0, state="POLICY",
                         participant_id="p_policy_setter", dedup_key="k2")
    pol = Applier(store, req).apply_policy(_policy_response(), materiality=0.5, margin=0.0, unverified_policy="penalty", judge_hash="h")
    assert pol.weight_overrides_applied == [] and pol.weight_overrides_unapplied == []
    assert {c.id: c.weight for c in pol.score_criteria} == {"crit_cost_efficiency": 1, "crit_speed": 1, "crit_risk": 2}
    ev_file = store.run_dir / "events.jsonl"
    assert not ev_file.exists() or EventKind.POLICY_WEIGHTS_OVERRIDDEN.value not in ev_file.read_text()


def test_weight_overrides_validated_in_config_and_settings(tmp_path):
    with pytest.raises(ValidationError):
        CouncilConfig.model_validate({"policy": {"weight_overrides": {"cost": 0}}})
    with pytest.raises(ValidationError):
        CouncilConfig.model_validate({"policy": {"weight_overrides": {"cost": -1}}})
    with pytest.raises(ValidationError):
        CouncilConfig.model_validate({"policy": {"weights": {"cost": 1}}})  # unknown key
    root = make_root(tmp_path)
    saved, eff = st.set_values(root, ['policy.weight_overrides={"cost":5,"crit_speed":1}'])
    assert eff.config.policy.weight_overrides == {"cost": 5, "crit_speed": 1}
    assert eff.provenance["policy.weight_overrides.cost"] == "saved"
    with pytest.raises(st.SettingsError):
        st.set_values(root, ['policy.weight_overrides={"cost":0}'])
    # per-run overrides layer on top of the saved weights (key by key) and win on conflicts
    eff2 = load_effective_config(root, overrides={"policy": {"weight_overrides": {"risk": 2, "cost": 1}}})
    assert eff2.config.policy.weight_overrides == {"cost": 1, "crit_speed": 1, "risk": 2}
    assert eff2.provenance["policy.weight_overrides.cost"] == "override" and eff2.provenance["policy.weight_overrides.crit_speed"] == "saved"
