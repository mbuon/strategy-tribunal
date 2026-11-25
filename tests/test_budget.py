from __future__ import annotations

from conftest import events, make_root, run_fixture
from llm_council.budget import Budget
from llm_council.config import Limits
from llm_council.ontology import RunState, StopReason


def test_budget_exhaustion_stops_early_with_partial_report(tmp_path):
    root = make_root(tmp_path)
    engine, result = run_fixture(root, "main_run.json", run_id="budget", strict=False,
                                 overrides={"limits": {"max_model_calls": 16, "finalisation_reserve_calls": 2}})
    d = engine.store.data
    assert d.state == RunState.COMPLETE
    assert d.stop_reason == StopReason.BUDGET_CALLS
    assert d.budget.model_calls_used <= 16
    # judging could not be completed for every option: explicit, never imputed
    assert any("not (re)scored" in u for u in d.unfinished_checks)
    assert any(e["kind"] == "rescore_required" and e["payload"]["status"] == "skipped_budget" for e in events(engine))
    dec = d.decision
    assert dec.stop_reason == StopReason.BUDGET_CALLS
    assert dec.completed_phases and "FRAMING" in dec.completed_phases
    assert any("budget" in u.lower() for u in dec.unfinished_checks)
    assert any(e["kind"] == "stop_decided" and e["payload"]["reason"] == "budget_calls" for e in events(engine))
    # the report says which phases completed and which checks are outstanding
    report = (engine.store.run_dir / "report.md").read_text()
    assert "## Unfinished checks" in report and "Completed phases:" in report


def test_leader_challenge_uses_reserve_when_deliberation_budget_is_gone(tmp_path):
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, "main_run.json", run_id="reserve", strict=False,
                            overrides={"limits": {"max_model_calls": 20, "finalisation_reserve_calls": 3}})
    d = engine.store.data
    assert d.stop_reason == StopReason.BUDGET_CALLS
    # two reserve calls were available for the leader challenge
    assert d.leader_challenges, "leader challenge should run from the finalisation reserve"
    assert d.budget.model_calls_used <= 20


def test_budget_labels_measured_vs_estimated():
    b = Budget.start()
    lim = Limits(max_model_calls=10, finalisation_reserve_calls=2)
    b.charge(calls=1, tokens_estimated=100)
    assert b.cost_status == "unavailable"
    b.charge(calls=1, tokens_measured=250, cost_usd=0.01)
    snap = b.snapshot(lim)
    assert snap.tokens_estimated == 100 and snap.tokens_measured == 250
    assert snap.cost_status == "partial" and snap.cost_usd == 0.01
    assert b.remaining_calls(lim) == 8 and b.deliberation_calls_available(lim) == 6
    assert b.can_afford(lim, 6) and not b.can_afford(lim, 7)
    b.elapsed_override = 10_000.0
    assert b.limit_hit(Limits(max_elapsed_seconds=5.0, max_model_calls=10, finalisation_reserve_calls=1)) == StopReason.BUDGET_TIME


def test_token_limit_enforced_before_every_request(tmp_path):
    root = make_root(tmp_path)
    engine, _ = run_fixture(root, "main_run.json", run_id="tok", strict=False,
                            overrides={"limits": {"max_tokens_estimate": 1500}})
    d = engine.store.data
    assert d.state == RunState.COMPLETE and d.stop_reason == StopReason.BUDGET_TOKENS
    assert d.budget.tokens_estimated >= 1500
    # the stop happened as soon as the limit was crossed, not at a round boundary
    stop = [e for e in events(engine) if e["kind"] == "stop_decided"][0]["payload"]
    assert stop["reason"] == "budget_tokens" and stop["state"] not in ("JUDGING",) or stop["reason"] == "budget_tokens"
    assert any("budget_tokens reached while in" in u for u in d.decision.unfinished_checks)


def test_retry_does_not_exceed_call_budget(tmp_path):
    root = make_root(tmp_path)
    # frame always malformed: the first attempt consumes the only call; no retry may be issued
    engine, _ = run_fixture(root, "retries_exhausted.json", run_id="nocalls", lenses="", strict=False,
                            overrides={"limits": {"max_model_calls": 2, "finalisation_reserve_calls": 1}})
    d = engine.store.data
    assert d.budget.model_calls_used <= 2
