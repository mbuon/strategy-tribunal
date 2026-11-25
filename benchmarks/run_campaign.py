"""Benchmark campaign runner (Run 2).

Runs every case in ``benchmarks/cases.json`` under every system configuration through the real
engine with the OpenCode route (all roles served by the configured OpenCode model), within the
documented resource limits, then evaluates outcomes:

* objective / failure-mode cases: programmatic checks against the known outcome;
* open cases: a blinded A/B rubric by an independent evaluator model (different from the in-run model).

Results land in ``benchmarks/results/<timestamp>/`` (``runs.json``, ``evaluations.json``,
``summary.md``). Usage is measured (calls, tokens from OpenCode, elapsed). Cost is unavailable on the
subscription provider and reported as such. The campaign stops at the first provider quota error.

Usage:  python benchmarks/run_campaign.py [--cases id,id] [--systems id,id] [--model provider/model]
        [--evaluator provider/model] [--max-runs N] [--repeat N] [--out DIR]
        python benchmarks/run_campaign.py --rescore DIR            # recompute checks + summary, no model calls
        python benchmarks/run_campaign.py --merge DIR1,DIR2 --out DIR   # consolidate campaigns (re-checked)

The per-run call cap is min(preset/project cap, campaign cap): the campaign limit never raises a preset's own cap.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llm_council.cli import locate_run  # noqa: E402
from llm_council.config import load_effective_config  # noqa: E402
from llm_council.providers.opencode import parse_events  # noqa: E402


def run_dir_of(run_id: str) -> Path:
    try:
        return locate_run(ROOT, run_id)
    except FileNotFoundError:
        return ROOT / ".council" / "runs" / run_id


def system_preset(system: dict):
    args = system.get("args", [])
    return args[args.index("--preset") + 1] if "--preset" in args else None


def system_call_cap(system: dict, limits: dict, root: Path = ROOT) -> int:
    """The campaign cap is a ceiling: a preset that already caps calls lower keeps its own cap."""
    eff = load_effective_config(root, preset=system_preset(system))
    return min(eff.config.limits.max_model_calls, int(limits["max_calls_per_run"]))


def run_case(case: dict, system: dict, model: str, run_id: str, limits: dict) -> dict:
    call_cap = system_call_cap(system, limits)
    args = [sys.executable, "-m", "llm_council.cli", "run", case["question"], "--run-id", run_id, "--provider", "opencode", "--opencode",
            "--set", f"routing.opencode.default_model={json.dumps(model)}", "--set", 'routing.opencode.fallback="fail"',
            "--set", f"limits.max_model_calls={call_cap}",
            "--set", f"limits.max_tokens_estimate={limits['max_tokens_estimate_per_run']}",
            "--set", f"limits.max_elapsed_seconds={limits['max_elapsed_seconds_per_run']}",
            *system["args"], "--root", str(ROOT)]
    t0 = time.time()
    proc = subprocess.run(args, capture_output=True, text=True, cwd=str(ROOT), timeout=limits["max_elapsed_seconds_per_run"] + 300)
    elapsed = time.time() - t0
    run_dir = run_dir_of(run_id)
    out = {"case": case["id"], "system": system["id"], "run_id": run_id, "exit_code": proc.returncode, "elapsed_seconds": round(elapsed, 1),
           "call_cap": call_cap, "stderr_tail": proc.stderr[-400:], "stdout_tail": proc.stdout[-600:]}
    dec_path = run_dir / "decision.json"
    state_path = run_dir / "state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text())
        out["state"] = state["state"]
        out["budget"] = state["budget"]
        out["failure_reason"] = state.get("failure_reason")
        out["completed_phases"] = state.get("completed_phases", [])
        out["unfinished_checks"] = state.get("unfinished_checks", [])
        out["rounds"] = state.get("round")
        out["participants"] = {k: {"provider": v["provider"], "model_requested": v.get("model_requested"), "model_reported": v.get("model_reported"),
                                   "isolation": v["isolation"]} for k, v in state["participants"].items()}
        out["option_titles"] = {k: v["title"] for k, v in state["option_versions"].items()}
        out["challenges"] = [{"id": c["id"], "mechanism": c["mechanism"][:160], "status": c["status"], "could_change": c["could_change"]} for c in state["challenges"].values()]
        out["briefs"] = [{"decision_statement": b["decision_statement"], "inferred_assumptions": b["inferred_assumptions"], "evidence_gaps": b["evidence_gaps"],
                          "decision_kind": b["decision_kind"]} for b in state["briefs"].values()]
        out["judgement_gate_fails"] = [{"version": j["option_version_id"], "failed_gates": j.get("failed_gates", [])} for j in state["judgements"].values() if j.get("failed_gates")]
    if dec_path.exists():
        dec = json.loads(dec_path.read_text())
        out["decision"] = {k: dec[k] for k in ("kind", "recommended_version_id", "alternatives", "stop_reason", "confidence", "next_action",
                                               "unresolved_challenge_ids", "unfinished_checks", "signals", "limitations")}
        out["decision"]["recommended_title"] = out["option_titles"].get(dec["recommended_version_id"]) if dec.get("recommended_version_id") else None
        out["report"] = (run_dir / "report.md").read_text()
    quota = "provider.quota" in (proc.stdout + proc.stderr) or any("provider.quota" in l for l in _events(run_dir))
    out["provider_quota_error"] = quota
    return out


def _events(run_dir: Path) -> list[str]:
    p = run_dir / "events.jsonl"
    return p.read_text().splitlines() if p.exists() else []


def _phrase_in(phrase: str, text: str) -> bool:
    """Whole-word/phrase, case-insensitive match (so 'vendor a' does not match 'vendor abc' or 'data (')."""
    return re.search(r"(?<!\w)" + re.escape(phrase.strip().lower()) + r"(?!\w)", text.lower()) is not None


def _text_values(obj) -> list[str]:
    """Every string VALUE in a nested structure; dict keys (field names) are never included."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _text_values(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _text_values(v)]
    return []


def premise_text(run: dict) -> str:
    dec = run.get("decision") or {}
    parts = []
    for b in run.get("briefs", []):
        parts += _text_values(b.get("inferred_assumptions", [])) + _text_values(b.get("evidence_gaps", [])) + _text_values(b.get("interpretations", []))
    parts += [c.get("mechanism", "") for c in run.get("challenges", [])]
    parts += _text_values(dec.get("signals", {}))
    return "\n".join(parts)


def check_expected(case: dict, run: dict, limits: dict | None = None) -> dict:
    exp = case["expected"]
    checks: dict[str, bool | None] = {}
    dec = run.get("decision")
    title = (dec or {}).get("recommended_title") or ""
    if "recommended_contains" in exp:
        checks["recommended_matches"] = bool(title) and any(_phrase_in(s, title) for s in exp["recommended_contains"])
    if "recommended_not_contains" in exp:
        checks["recommended_avoids"] = not any(_phrase_in(s, title) for s in exp["recommended_not_contains"])
    if "gate_failed_option_contains" in exp:
        failed_titles = [run.get("option_titles", {}).get(j["version"], "") for j in run.get("judgement_gate_fails", [])]
        checks["gate_failed_on_planted_option"] = any(any(s.lower() in t.lower() for s in exp["gate_failed_option_contains"]) for t in failed_titles)
    if "kind_in" in exp:
        checks["kind_acceptable"] = (dec or {}).get("kind") in exp["kind_in"]
    if "premise_flagged" in exp:
        text = premise_text(run).lower()
        checks["premise_flagged"] = any(s.lower() in text for s in exp["premise_flagged"])
    if "stop_reason_in" in exp:
        checks["stop_reason_acceptable"] = (dec or {}).get("stop_reason") in exp["stop_reason_in"]
    if "max_calls" in exp:
        checks["within_call_cap"] = (run.get("budget") or {}).get("model_calls_used", 10**9) <= exp["max_calls"]
    checks["completed"] = run.get("state") == "COMPLETE"
    if limits:
        calls = (run.get("budget") or {}).get("model_calls_used", 10**9)
        checks["within_campaign_limits"] = calls <= limits["max_calls_per_run"] and run.get("elapsed_seconds", 10**9) <= limits["max_elapsed_seconds_per_run"]
    return checks


def primary_passed(case: dict, checks: dict) -> bool | None:
    """The predeclared primary measure for a case: None for rubric-only (open) cases."""
    keys = [k for k in ("recommended_matches", "recommended_avoids", "gate_failed_on_planted_option", "kind_acceptable",
                        "premise_flagged", "stop_reason_acceptable", "within_call_cap") if k in checks]
    if not keys:
        return None
    return all(checks[k] for k in keys) and checks.get("completed", False)


def opencode_call(model: str, prompt: str, timeout: int = 240) -> dict:
    cfg_dir = ROOT / "adapters" / "opencode"
    env = dict(os.environ, PWD=str(cfg_dir))
    args = ["opencode", "run", "--format", "json", "--archived", "--title", "council benchmark evaluator", "--agent", "council-member",
            "--standalone", "--model", model, prompt]
    proc = subprocess.run(args, capture_output=True, text=True, cwd=str(cfg_dir), env=env, timeout=timeout)
    parsed = parse_events(proc.stdout or "")
    parsed["exit_code"] = proc.returncode
    return parsed


EVAL_PROMPT = """You are an independent evaluator of decision recommendations. You will see a decision question and two anonymised
decision records (A and B) produced by different systems. Score each record on three criteria from 0 to 10:
1. defensibility: is the recommendation justified by the stated evidence and reasoning, with uncertainty acknowledged?
2. completeness: are trade-offs, alternatives, risks and what would reverse the decision covered?
3. actionability: is there one concrete next action and clear conditions?
Then say which record is better overall ("A", "B" or "tie"). Answer with exactly one JSON object:
{"A": {"defensibility": int, "completeness": int, "actionability": int}, "B": {...}, "better": "A"|"B"|"tie", "reason": "one sentence"}

QUESTION:
%s

RECORD A:
%s

RECORD B:
%s
"""


EVAL_SECTIONS = ["## Outcome", "## Strongest alternatives", "## Material dissent", "## Trade-offs", "## Reopen", "## What the council failed"]
EVAL_SECTION_CAP = {"## Material dissent": 12, "## Strongest alternatives": 8, "## Trade-offs": 8, "## Reopen": 8, "## What the council failed": 8}
EVAL_LINE_CAP = 600
EVAL_TOTAL_CAP = 14000


def summarise_for_eval(run: dict) -> str:
    """Blinded evaluator input: outcome, alternatives, dissent, trade-offs, reversal conditions, gaps.

    Sections are capped by line count (dissent: objections on the recommended option and shared blind spots first),
    lines by length, and the whole by EVAL_TOTAL_CAP without ever cutting inside a line. Run ids and lens/round hints
    are removed. The earlier 6 000-character hard cut truncated long council records mid-sentence and was penalised by
    the evaluator as "cut off" (Run 2 finding); the cap is now 14 000 characters on whole lines."""
    dec = run.get("decision") or {}
    rep = run.get("report") or ""
    rec_id = dec.get("recommended_version_id") or ""
    sections: dict[str, list[str]] = {}
    current = None
    for line in rep.splitlines():
        if line.startswith("## "):
            current = next((s for s in EVAL_SECTIONS if line.startswith(s)), None)
            if current:
                sections.setdefault(current, []).append(line)
            continue
        if current and line.strip() and not line.startswith("**Stopping reason"):
            sections[current].append(line)
    out: list[str] = []
    for sec in EVAL_SECTIONS:
        lines = sections.get(sec)
        if not lines:
            continue
        head, body = lines[0], lines[1:]
        if sec == "## Material dissent":
            def _dissent_key(l: str) -> int:
                if rec_id and f"`{rec_id}`" in l:
                    return 0
                if "`__all__`" in l or "Dissent" in l:
                    return 1
                return 2
            body = sorted(body, key=_dissent_key)
        cap = EVAL_SECTION_CAP.get(sec)
        if cap and len(body) > cap:
            body = body[:cap] + [f"- … {len(lines) - 1 - cap} further item(s) omitted for length"]
        out.append(head)
        out += [l if len(l) <= EVAL_LINE_CAP else l[:EVAL_LINE_CAP].rstrip() + " …" for l in body]
    text = "\n".join(out)
    text = re.sub(r"`optv_[A-Za-z0-9_]+`", "`option`", text)
    text = re.sub(r"`(dis|chl|lch|asm|ev|clm)_[A-Za-z0-9_]+`", "`item`", text)
    text = re.sub(r"\(round \d+, lens [a-z_]+\)", "", text)
    if len(text) > EVAL_TOTAL_CAP:
        kept: list[str] = []
        size = 0
        for l in text.splitlines():
            if size + len(l) + 1 > EVAL_TOTAL_CAP:
                kept.append("- … remaining lines omitted for length")
                break
            kept.append(l)
            size += len(l) + 1
        text = "\n".join(kept)
    return text


def evaluate_pair(question: str, run_a: dict, run_b: dict, evaluator: str, rng: random.Random) -> dict:
    swap = rng.random() < 0.5
    first, second = (run_b, run_a) if swap else (run_a, run_b)
    prompt = EVAL_PROMPT % (question, summarise_for_eval(first), summarise_for_eval(second))
    res = opencode_call(evaluator, prompt)
    out = {"swap": swap, "first": first["system"], "second": second["system"], "error": res.get("error"), "tokens": res.get("tokens"), "raw": res.get("text", "")[:1500]}
    try:
        txt = res.get("text", "").strip()
        if txt.startswith("```"):
            txt = txt.strip("`").split("\n", 1)[1]
        js = json.loads(txt)
        a_scores = js["A"] if not swap else js["B"]
        b_scores = js["B"] if not swap else js["A"]
        better = js["better"]
        winner = "tie" if better == "tie" else (("a" if better == "A" else "b") if not swap else ("b" if better == "A" else "a"))
        out.update({"scores": {run_a["system"]: a_scores, run_b["system"]: b_scores}, "winner": {"a": run_a["system"], "b": run_b["system"], "tie": "tie"}[winner],
                    "reason": js.get("reason", "")})
    except Exception as e:  # noqa: BLE001
        out["parse_error"] = str(e)
    return out


def load_spec() -> dict:
    return json.loads((ROOT / "benchmarks" / "cases.json").read_text())


def recheck(spec: dict, runs: list[dict], reload_reports: bool = False) -> list[dict]:
    by_id = {c["id"]: c for c in spec["cases"]}
    for r in runs:
        run_dir = run_dir_of(r["run_id"])
        state_path = run_dir / "state.json"
        if "completed_phases" not in r and state_path.exists():  # older campaigns did not capture these fields
            state = json.loads(state_path.read_text())
            r["completed_phases"] = state.get("completed_phases", [])
            r["unfinished_checks"] = state.get("unfinished_checks", [])
            r["rounds"] = state.get("round")
        if reload_reports and (run_dir / "decision.json").exists() and r.get("decision"):
            # pick up a `council rereport` (decision/report rebuilt from committed state, no model calls)
            dec = json.loads((run_dir / "decision.json").read_text())
            r["decision"] = {k: dec[k] for k in r["decision"] if k in dec} | {"recommended_title": r.get("option_titles", {}).get(dec.get("recommended_version_id")) if dec.get("recommended_version_id") else None}
            r["report"] = (run_dir / "report.md").read_text()
            r["rereported"] = (run_dir / "decision.prev.json").exists()
        r["checks"] = check_expected(by_id[r["case"]], r, spec["resource_limits"])
        r["primary_passed"] = primary_passed(by_id[r["case"]], r["checks"])
    return runs


def run_evaluations(spec: dict, cases: list[dict], systems: list[dict], runs: list[dict], evaluator: str, eval_repeats: int,
                    rng: random.Random, existing: list[dict] | None = None) -> list[dict]:
    """Blinded A/B rubric for every rubric case: pairs the k-th repeat of each system; skips pairs already evaluated."""
    evaluations: list[dict] = list(existing or [])
    done = {(e["case"], e.get("repeat_index", 1), frozenset((e["first"], e["second"]))) for e in evaluations if e.get("winner")}
    for case in cases:
        if not case["expected"].get("rubric"):
            continue
        reps = sorted({r.get("repeat_index", 1) for r in runs if r["case"] == case["id"]})
        for k in reps:
            by_sys = {r["system"]: r for r in runs if r["case"] == case["id"] and r.get("decision") and r.get("repeat_index", 1) == k}
            ids = [s["id"] for s in systems if s["id"] in by_sys]
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    if (case["id"], k, frozenset((ids[i], ids[j]))) in done:
                        continue
                    for rep in range(eval_repeats):
                        ev = evaluate_pair(case["question"], by_sys[ids[i]], by_sys[ids[j]], evaluator, rng)
                        ev.update({"case": case["id"], "repeat": rep + 1, "repeat_index": k,
                                   "runs": {ids[i]: by_sys[ids[i]]["run_id"], ids[j]: by_sys[ids[j]]["run_id"]}})
                        evaluations.append(ev)
                        print(f"    eval {case['id']} r{k} {ids[i]} vs {ids[j]} rep {rep + 1}: winner={ev.get('winner')} err={ev.get('error')}", flush=True)
    return evaluations


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases")
    ap.add_argument("--systems")
    ap.add_argument("--model", default="claude-agent/haiku")
    ap.add_argument("--evaluator", default="claude-agent/sonnet")
    ap.add_argument("--max-runs", type=int, default=None)
    ap.add_argument("--repeat", type=int, default=1, help="run every case/system N times (variability)")
    ap.add_argument("--out")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--eval-repeats", type=int, default=2)
    ap.add_argument("--rescore", help="recompute checks and summary for an existing results folder (no model calls)")
    ap.add_argument("--reload-reports", action="store_true", help="with --rescore: reload decision/report from the run dirs (after `council rereport`)")
    ap.add_argument("--reevaluate", action="store_true", help="with --rescore: run the blinded rubric again as a new evaluation pass (model calls)")
    ap.add_argument("--merge", help="comma-separated results folders to consolidate into --out (re-checked; missing rubric evaluations are run)")
    ap.add_argument("--note", default="", help="free-text note recorded at the top of the summary")
    args = ap.parse_args()
    spec = load_spec()
    cases = [c for c in spec["cases"] if not args.cases or c["id"] in args.cases.split(",")]
    systems = [s for s in spec["systems"] if not args.systems or s["id"] in args.systems.split(",")]
    limits = spec["resource_limits"]
    rng = random.Random(args.seed)

    if args.rescore:
        out_dir = Path(args.rescore)
        runs = recheck(spec, json.loads((out_dir / "runs.json").read_text()), reload_reports=args.reload_reports)
        evals_path = out_dir / "evaluations.json"
        evaluations = json.loads(evals_path.read_text()) if evals_path.exists() else []
        if args.reevaluate:
            prev_pass = max([e.get("pass", 1) for e in evaluations] or [0])
            for e in evaluations:
                e.setdefault("pass", 1)
            new = run_evaluations(spec, spec["cases"], spec["systems"], runs, args.evaluator, args.eval_repeats, rng, existing=None)
            for e in new:
                e["pass"] = prev_pass + 1
                e["note"] = args.note
            evaluations += new
            evals_path.write_text(json.dumps(evaluations, indent=1))
        (out_dir / "runs.json").write_text(json.dumps(runs, indent=1))
        summary = render_summary(spec, runs, evaluations, "n/a (rescored)", args)
        (out_dir / "summary.md").write_text(summary)
        print(summary)
        return 0

    if args.merge:
        out_dir = Path(args.out) if args.out else ROOT / "benchmarks" / "results" / ("merged_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        out_dir.mkdir(parents=True, exist_ok=True)
        runs, evaluations = [], []
        for d in args.merge.split(","):
            p = Path(d)
            runs += json.loads((p / "runs.json").read_text())
            if (p / "evaluations.json").exists():
                evaluations += json.loads((p / "evaluations.json").read_text())
        runs = recheck(spec, runs)
        evaluations = run_evaluations(spec, spec["cases"], spec["systems"], runs, args.evaluator, args.eval_repeats, rng, existing=evaluations)
        (out_dir / "runs.json").write_text(json.dumps(runs, indent=1))
        (out_dir / "evaluations.json").write_text(json.dumps(evaluations, indent=1))
        summary = render_summary(spec, runs, evaluations, f"n/a (merged from {args.merge})", args)
        (out_dir / "summary.md").write_text(summary)
        print(summary)
        return 0

    max_runs = args.max_runs or limits["max_runs_per_campaign"]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) if args.out else ROOT / "benchmarks" / "results" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    runs: list[dict] = []
    stopped = None
    for k in range(1, args.repeat + 1):
        for case in cases:
            for system in systems:
                if len(runs) >= max_runs:
                    stopped = f"max_runs_per_campaign ({max_runs}) reached"
                    break
                run_id = f"bench_{stamp}_{case['id']}_{system['id']}" + (f"_r{k}" if args.repeat > 1 else "")
                print(f"[{len(runs) + 1}] {case['id']} / {system['id']} (repeat {k}) -> {run_id}", flush=True)
                r = run_case(case, system, args.model, run_id, limits)
                r["repeat_index"] = k
                r["checks"] = check_expected(case, r, limits)
                r["primary_passed"] = primary_passed(case, r["checks"])
                runs.append(r)
                (out_dir / "runs.json").write_text(json.dumps(runs, indent=1))
                print(f"    state={r.get('state')} calls={(r.get('budget') or {}).get('model_calls_used')}/{r['call_cap']} elapsed={r['elapsed_seconds']}s checks={r['checks']}", flush=True)
                if r["provider_quota_error"] and limits.get("stop_on_provider_quota_error"):
                    stopped = "provider quota error"
                    break
            if stopped:
                break
        if stopped:
            break
    evaluations: list[dict] = []
    if not stopped or stopped.startswith("max_runs"):
        evaluations = run_evaluations(spec, cases, systems, runs, args.evaluator, args.eval_repeats, rng)
    (out_dir / "evaluations.json").write_text(json.dumps(evaluations, indent=1))
    summary = render_summary(spec, runs, evaluations, stopped, args)
    (out_dir / "summary.md").write_text(summary)
    print(summary)
    return 0


def _mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def aggregate(spec: dict, runs: list[dict]) -> list[dict]:
    """Per case × system: n, primary pass rate, mean/min/max calls, tokens, elapsed, budget-truncated count, challenge reached."""
    rows = []
    for case in spec["cases"]:
        for system in spec["systems"]:
            rs = [r for r in runs if r["case"] == case["id"] and r["system"] == system["id"]]
            if not rs:
                continue
            calls = [(r.get("budget") or {}).get("model_calls_used") for r in rs]
            toks = [(r.get("budget") or {}).get("tokens_measured") for r in rs]
            el = [r.get("elapsed_seconds") for r in rs]
            prim = [r.get("primary_passed") for r in rs]
            rows.append({
                "case": case["id"], "system": system["id"], "n": len(rs),
                "primary_pass": (f"{sum(1 for p in prim if p)}/{len(prim)}" if any(p is not None for p in prim) else "rubric"),
                "calls": f"{_mean(calls)} [{min(calls)}–{max(calls)}]" if len(rs) > 1 else str(calls[0]),
                "tokens": f"{_mean(toks)} [{min(toks)}–{max(toks)}]" if len(rs) > 1 else str(toks[0]),
                "elapsed_s": f"{_mean(el)} [{min(el)}–{max(el)}]" if len(rs) > 1 else str(el[0]),
                "budget_truncated": sum(1 for r in rs if str(((r.get("decision") or {}).get("stop_reason") or "")).startswith("budget")),
                "challenge_reached": sum(1 for r in rs if "CHALLENGING" in (r.get("completed_phases") or [])),
                "over_campaign_limits": sum(1 for r in rs if r.get("checks", {}).get("within_campaign_limits") is False),
            })
    return rows


def render_summary(spec: dict, runs: list[dict], evaluations: list[dict], stopped, args) -> str:
    lines = [f"# Benchmark campaign {datetime.now().isoformat(timespec='minutes')}", ""]
    if getattr(args, "note", ""):
        lines += [f"> {args.note}", ""]
    lines += [f"Cases spec version: {spec.get('version')}. In-run model: {args.model} (OpenCode restricted agent, all roles, isolation `isolated`). "
              f"Evaluator: {args.evaluator} (blinded A/B, {args.eval_repeats} repeats, order randomised).",
              f"Runs: {len(runs)}. Stopped early: {stopped or 'no'}. Declared per-run limits: ≤ {spec['resource_limits']['max_calls_per_run']} calls (never above a preset's own cap), "
              f"≤ {spec['resource_limits']['max_tokens_estimate_per_run']} measured tokens (enforced before each request; one reply may overshoot), ≤ {spec['resource_limits']['max_elapsed_seconds_per_run']} s.", "",
              "## Per-run results",
              "| case | system | rep | state | kind | stop | calls/cap | tokens (measured) | elapsed s | cost | primary | checks |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in runs:
        b = r.get("budget") or {}
        d = r.get("decision") or {}
        lines.append(f"| {r['case']} | {r['system']} | {r.get('repeat_index', 1)} | {r.get('state')} | {d.get('kind')} | {d.get('stop_reason')} | {b.get('model_calls_used')}/{r.get('call_cap', '?')} | {b.get('tokens_measured')} | {r['elapsed_seconds']} | {b.get('cost_status', 'unavailable')} | {r.get('primary_passed')} | {r['checks']} |")
    lines += ["", "## Aggregate per case × system (n, primary-measure pass rate, usage mean [min–max])",
              "| case | system | n | primary pass | calls | tokens | elapsed s | budget-truncated | leader challenge reached | over campaign limits |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for a in aggregate(spec, runs):
        lines.append(f"| {a['case']} | {a['system']} | {a['n']} | {a['primary_pass']} | {a['calls']} | {a['tokens']} | {a['elapsed_s']} | {a['budget_truncated']} | {a['challenge_reached']} | {a['over_campaign_limits']} |")
    lines.append("")
    if evaluations:
        passes = sorted({e.get("pass", 1) for e in evaluations})
        for p in passes:
            evs = [e for e in evaluations if e.get("pass", 1) == p]
            note = next((e.get("note") for e in evs if e.get("note")), "")
            lines.append(f"## Blinded rubric evaluations (open cases){f' — pass {p}' if len(passes) > 1 else ''}")
            if note:
                lines.append(f"> {note}")
            lines.append("| case | runs rep | pair (order shown) | eval repeat | winner | scores | reason |")
            lines.append("|---|---|---|---|---|---|---|")
            for e in evs:
                lines.append(f"| {e['case']} | {e.get('repeat_index', 1)} | {e['first']} vs {e['second']} | {e['repeat']} | {e.get('winner', 'n/a')} | {json.dumps(e.get('scores'))} | {e.get('reason', e.get('error') or e.get('parse_error', ''))} |")
            wins: dict[str, int] = {}
            sums: dict[str, dict[str, list[int]]] = {}
            for e in evs:
                w = e.get("winner")
                if w:
                    wins[w] = wins.get(w, 0) + 1
                for sysid, sc in (e.get("scores") or {}).items():
                    for crit, val in sc.items():
                        sums.setdefault(sysid, {}).setdefault(crit, []).append(val)
            lines.append("")
            lines.append(f"Wins/ties/losses (evaluator verdicts): {wins}")
            for sysid, crits in sums.items():
                lines.append(f"- mean rubric {sysid}: " + ", ".join(f"{c} {_mean(v)}" for c, v in crits.items()) + f" (n={len(next(iter(crits.values())))})")
            lines.append("")
    lines.append("")
    lines.append("## Reference systems status")
    for ref, status in REFERENCE_STATUS.items():
        lines.append(f"- {ref}: {status}")
    return "\n".join(lines)


REFERENCE_STATUS = {
    "llm-council-main (first-pass workflow)": "PROXY comparison only: the engine's own `first_pass` preset (frame, policy, baseline, lenses, judge, report; no review, verification or challenge) stands in for the reference; the original Claude Code agents were not run. They are runnable unattended through `claude -p` at roughly US$ 3 per case (new spend, user's decision)",
    "council-review-main": "not run: a prompt-only Claude Code skill; runnable unattended through `claude -p` at roughly US$ 3-4 per case (new spend, user's decision)",
    "council-master": "blocked by credentials: needs OPENAI_API_KEY-style keys for OpenAI-compatible endpoints (Gemini/xAI) in the environment; none present (the OpenAI access on this machine is a ChatGPT-account OAuth held inside OpenCode, not an API key); Google quota depleted (402)",
    "LLM-Council-Decide-master": "blocked by credentials and dependencies: OPENROUTER_API_KEY and Typst not available",
    "neuralhats-main": "live comparison ATTEMPTED on local Ollama (gemma4) with the engine's typo case; outcome, model match and evaluator result recorded in docs/llm_council.md section 16.5",
    "llm-as-a-verifier-main": "blocked by dependencies (possibly unblockable): needs a log-probability backend (DeepSeek, Vertex or OpenAI-compatible with logprobs); none configured; the local Ollama server may expose logprobs but this was not tested",
}


if __name__ == "__main__":
    sys.exit(main())
