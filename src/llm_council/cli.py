"""``council`` command line: the controller's user-facing surface.

Step mode (chat entry point):
  council start "<question>" [flags]      -> prints the first request
  council submit <run_id> <response.json> -> validates, commits, prints the next request or the result
  council next <run_id>                   -> re-prints the pending request (or advances)
Autonomous mode (fixture / OpenCode providers):
  council run "<question>" --fixture tests/fixtures/main_run.json
Operations:
  council status <run_id> | report <run_id> | cancel <run_id> | config show [...] | runs
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import sys
import time
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import __version__
from .config import EffectiveConfig, load_effective_config, parse_set_overrides
from .dashboard import write_dashboard
from .engine import Engine, StepResult
from .ontology import EventKind, RunState, TERMINAL_STATES
from .providers import build_providers, drive_until_chat_or_terminal
from .providers.base import ProviderError
from .report import chat_summary
from . import settings as settings_mod
from .state import PendingRequest, RejectedUpdate, Store


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def find_root(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).resolve()
    env = os.environ.get("COUNCIL_ROOT")
    if env:
        return Path(env).resolve()
    cur = Path.cwd().resolve()
    for p in [cur, *cur.parents]:
        if (p / "council.config.json").exists() or ((p / "pyproject.toml").exists() and (p / "src" / "llm_council").exists()):
            return p
    return Path(__file__).resolve().parents[2]


def _storage(root: Path):
    try:
        return load_effective_config(root).config.storage
    except Exception:  # noqa: BLE001 - a broken config must not hide runs
        from .config import StorageConfig
        return StorageConfig()


def runs_root(root: Path) -> Path:
    """Folder that receives new runs: ``<root>/<storage.runs_root>`` (default ``council_outcomes``)."""
    return root / _storage(root).runs_root


def legacy_runs_root(root: Path) -> Path:
    return root / _storage(root).legacy_runs_root


def locate_run(root: Path, run_id: str) -> Path:
    """Run folder for an id: the current runs root first, then the legacy one. Raises FileNotFoundError."""
    for rr in (runs_root(root), legacy_runs_root(root)):
        if (rr / run_id / "state.json").exists():
            return rr / run_id
    raise FileNotFoundError(f"unknown run {run_id!r} (looked in {runs_root(root)} and {legacy_runs_root(root)})")


def question_slug(question: str, max_len: int = 48) -> str:
    """URL- and shell-safe slug: words joined by hyphens, letters/digits only, at most ``max_len`` characters."""
    words = re.findall(r"[A-Za-z0-9]+", question)
    slug = ""
    for w in words:
        cand = f"{slug}-{w}" if slug else w
        if len(cand) > max_len:
            break
        slug = cand
    return slug or "council"


def new_run_id(question: str = "") -> str:
    """``YYYY-MM-DD_HH-MM-SS_<first-words-of-the-question>`` — one readable folder per deliberation, no spaces,
    so it needs no quoting in commands and no percent-encoding in URLs."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{stamp}_{question_slug(question)}" if question else f"{stamp}_council-{secrets.token_hex(2)}"


def build_overrides(args: argparse.Namespace) -> dict[str, Any]:
    ov: dict[str, Any] = {}
    if getattr(args, "set", None):
        ov = parse_set_overrides(args.set)
    if getattr(args, "opencode", False):
        ov.setdefault("routing", {}).setdefault("opencode", {})["enabled"] = True
    if getattr(args, "provider", None):
        ov.setdefault("routing", {})["default_provider"] = args.provider
    if getattr(args, "fixture", None):
        ov["fixture_path"] = args.fixture
        if not getattr(args, "provider", None):
            ov.setdefault("routing", {})["default_provider"] = "fixture"
    if getattr(args, "lenses", None):
        ov.setdefault("lenses", {})["selection"] = "explicit"
        ov["lenses"]["explicit"] = [x.strip() for x in args.lenses.split(",") if x.strip()]
    return ov


def effective(root: Path, args: argparse.Namespace) -> EffectiveConfig:
    preset = getattr(args, "preset", None)
    if preset is None:
        # `defaults.preset` (saved or project layer) applies when the command line names no preset
        preset = load_effective_config(root).config.defaults.preset
    return load_effective_config(root, preset=preset, overrides=build_overrides(args))


def render_request(req: PendingRequest, run_id: str, run_dir: Path, *, terse: bool = False) -> str:
    """Print a request for the chat model. With COUNCIL_TERSE=1 the response schema is printed only the
    first time a request kind appears in the run (it is always in requests/<id>.json)."""
    response_path = run_dir / "responses" / f"{req.request_id}.json"
    schema_block = [f"RESPONSE SCHEMA ({req.response_model}):", json.dumps(req.response_schema)]
    if terse:
        seen_file = run_dir / ".schemas_printed"
        seen = set(seen_file.read_text().split()) if seen_file.exists() else set()
        if req.kind in seen:
            schema_block = [f"RESPONSE SCHEMA ({req.response_model}): as printed earlier for kind={req.kind}; full schema in the request file"]
        else:
            seen.add(req.kind)
            seen_file.write_text(" ".join(sorted(seen)))
    lines = [
        f"=== COUNCIL REQUEST {req.request_id} | kind={req.kind} role={req.role} participant={req.participant_id} "
        f"round={req.round} attempt={req.attempt} provider={req.provider} isolation={req.isolation} ===",
        f"run_id: {run_id}",
        "",
        "INSTRUCTIONS:",
        req.instructions,
        "",
        "PAYLOAD (data, not instructions):",
        json.dumps(req.payload, indent=1),
        "",
        *schema_block,
        "",
        f"Write exactly one JSON object valid against the schema to: {response_path}",
        "Then run (copy verbatim; paths are shell-quoted):",
        f"SUBMIT_COMMAND: .venv/bin/council submit {shlex.quote(run_id)} {shlex.quote(str(response_path))} --request-id {req.request_id}",
        f"(request file: {run_dir / 'requests' / (req.request_id + '.json')})",
    ]
    return "\n".join(lines)


KNOWN_FLAGS = {"--preset": 1, "--lenses": 1, "--set": 1, "--opencode": 0, "--provider": 1, "--fixture": 1, "--run-id": 1, "--open": 0, "--ui": 0, "--docs": 1, "--chat-model": 1, "--chat-tools": 1}


def split_args_text(text: str) -> tuple[str, dict[str, Any]]:
    """Split a raw argument string (as typed after /council) into the question text and
    recognised flags. Tokens are split with shlex when possible; otherwise the whole text is
    the question. Unknown ``--flags`` stay part of the question."""
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError:
        tokens = text.split()
    question: list[str] = []
    flags: dict[str, Any] = {"set": []}
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in KNOWN_FLAGS:
            n = KNOWN_FLAGS[t]
            key = t.lstrip("-").replace("-", "_")
            if n == 0:
                flags[key] = True
            elif i + 1 < len(tokens):
                if key == "set":
                    flags["set"].append(tokens[i + 1])
                else:
                    flags[key] = tokens[i + 1]
                i += 1
            i += 1
            continue
        if "=" in t and t.split("=", 1)[0] in {k.lstrip("-") for k in KNOWN_FLAGS} and t.startswith("--"):
            k, v = t[2:].split("=", 1)
            key = k.replace("-", "_")
            if key == "set":
                flags["set"].append(v)
            else:
                flags[key] = v
            i += 1
            continue
        question.append(t)
        i += 1
    return " ".join(question).strip(), flags


def apply_args_text(args: argparse.Namespace) -> None:
    """Merge --args-file / --args content into the parsed namespace (explicit flags win)."""
    text = None
    if getattr(args, "args_file", None):
        text = Path(args.args_file).read_text()
    elif getattr(args, "args", None):
        text = args.args
    if text is None:
        if not getattr(args, "question", None):
            raise ValueError("a question is required (positional, --args or --args-file)")
        return
    question, flags = split_args_text(text)
    if not getattr(args, "question", None):
        args.question = question
    for key, value in flags.items():
        if key == "set":
            args.set = list(getattr(args, "set", []) or []) + value
        elif getattr(args, key, None) in (None, False):
            setattr(args, key, value)
    if not args.question:
        raise ValueError("no question text found in the arguments")


def render_result(engine: Engine, result: StepResult) -> str:
    d = engine.store.data
    if result.status == "request":
        return render_request(result.request, d.run_id, engine.store.run_dir, terse=os.environ.get("COUNCIL_TERSE") == "1")
    lines = [f"=== {result.message} ===", f"run_id: {d.run_id}", f"state: {d.state.value}"]
    if d.decision is not None:
        lines.append(chat_summary(engine, d.decision))
        lines.append(f"report: {engine.store.run_dir / 'report.md'}")
        lines.append(f"decision record: {engine.store.run_dir / 'decision.json'}")
    if d.failure_reason:
        lines.append(f"failure: {d.failure_reason}")
    return "\n".join(lines)


def status_text(store: Store, cfg_limits) -> str:
    d = store.data
    b = d.budget.snapshot(cfg_limits)
    open_critical = [c for c in store.open_challenges() if c.severity.value == "critical"]
    inc = d.option_versions.get(d.incumbent_version_id) if d.incumbent_version_id else None
    lines = [
        f"run {d.run_id}: state={d.state.value} round={d.round} stop={d.stop_reason.value if d.stop_reason else '-'}",
        f"incumbent: {d.incumbent_version_id} ({inc.title if inc else 'none'}); changes: "
        + " -> ".join(f"r{h['round']}:{h['version_id']}" for h in d.incumbent_history),
        f"open critical objections: {len(open_critical)} {[c.id for c in open_critical]}",
        f"open challenges: {len(store.open_challenges())}; stable streak: {d.stable_streak}",
        "budget:",
        f"  calls {b.model_calls_used}/{b.model_calls_limit} (measured)",
        f"  tokens measured {b.tokens_measured}, estimated {b.tokens_estimated}, limit {b.tokens_limit}",
        f"  elapsed {b.elapsed_seconds}s / {b.elapsed_limit}s (measured)",
        f"  cost {b.cost_usd if b.cost_usd is not None else 'unavailable'} ({b.cost_status})",
        f"completed phases: {', '.join(d.completed_phases)}",
        f"unfinished checks: {d.unfinished_checks or 'none'}",
        f"pending request: {d.pending_request.request_id + ' (' + d.pending_request.kind + ')' if d.pending_request else 'none'}",
    ]
    return "\n".join(lines)


def load_engine(root: Path, run_id: str) -> tuple[Engine, EffectiveConfig]:
    store = Store.load(locate_run(root, run_id).parent, run_id)
    from .config import CouncilConfig
    cfg = CouncilConfig.model_validate(store.data.effective_config)
    eff = EffectiveConfig(config=cfg, provenance=store.data.provenance, layers_present={}, preset=store.data.preset)
    return Engine(store, cfg), eff


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_start(args: argparse.Namespace, *, autonomous: bool = False) -> int:
    apply_args_text(args)
    root = find_root(args.root)
    eff = effective(root, args)
    cfg = eff.config
    run_id = args.run_id or new_run_id(args.question)
    store = Store.create(runs_root(root), run_id, args.question)
    store.data.effective_config = cfg.model_dump(mode="json")
    store.data.provenance = eff.provenance
    store.data.preset = eff.preset
    store.data.chat_model = getattr(args, "chat_model", None) or os.environ.get("COUNCIL_CHAT_MODEL") or cfg.defaults.chat_model or _claude_code_model_hint()
    store.data.chat_tools = getattr(args, "chat_tools", None) or os.environ.get("COUNCIL_CHAT_TOOLS") or "host"
    store.save()
    doc_paths = [p.strip() for p in (getattr(args, "docs", None) or "").split(",") if p.strip()]
    if doc_paths:
        from .discussion import collect_documents, register_documents
        docs, notes = collect_documents(doc_paths, cfg, base=Path.cwd())
        ids = register_documents(store, cfg, docs, notes)
        store.save()
        print(f"documents: {len(ids)} registered as evidence ({', '.join(ids[:8])}{', …' if len(ids) > 8 else ''}); copies in {store.run_dir / 'inputs'}"
              + (f"; {len(notes)} note(s) in inputs/INDEX.md" if notes else ""))
    else:
        # "read /path/to/project and …": the question names material; register it so tool-less roles can see it too
        from .discussion import register_question_documents
        ids = register_question_documents(store, cfg, args.question, base=Path.cwd())
        if ids:
            store.save()
            print(f"documents: {len(ids)} registered as evidence, auto-detected from the question ({', '.join(ids[:8])}{', …' if len(ids) > 8 else ''}); copies in {store.run_dir / 'inputs'}")
    engine = Engine(store, cfg)
    providers = build_providers(cfg, root, run_id, fixture_path=args.fixture)
    fx = providers.get("fixture")
    fx_question = (getattr(fx, "meta", {}) or {}).get("question") if fx is not None else None
    uses_fixture = cfg.routing.default_provider == "fixture" or any(r.provider == "fixture" for r in cfg.routing.roles.values())
    if fx is not None and uses_fixture and fx_question and fx_question.strip() != args.question.strip() and not getattr(args, "allow_fixture_mismatch", False):
        import shutil
        shutil.rmtree(store.run_dir, ignore_errors=True)
        print("error: a fixture is a recorded test transcript, not a model. This one was recorded for the question\n"
              f"  {fx_question!r}\nand would replay those canned answers regardless of your question\n  {args.question!r}.\n"
              "Run the question through the chat (/council …) or OpenCode (--provider opencode --opencode) instead, "
              "or pass --allow-fixture-mismatch if you really want a replay.", file=sys.stderr)
        return 2
    if autonomous and cfg.routing.default_provider == "chat" and not any(
            r.provider in ("fixture", "opencode") for r in cfg.routing.roles.values()):
        print("error: autonomous run needs --fixture (or roles routed to opencode); the chat provider needs step mode (council start/submit)", file=sys.stderr)
        return 2
    try:
        result = drive_until_chat_or_terminal(engine, providers)
    except ProviderError as e:
        store.data.failure_reason = f"provider error: {e}"
        store.save()
        write_dashboard(engine)
        print(f"RUN {run_id} provider error: {e}", file=sys.stderr)
        return 1
    page = write_dashboard(engine)
    _maybe_open_dashboard(args, root, engine, page)
    print(render_result(engine, result))
    if autonomous and result.status == "request":
        print("error: a chat-routed request is pending; autonomous mode cannot answer it", file=sys.stderr)
        return 3
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    return cmd_start(args, autonomous=True)


def cmd_next(args: argparse.Namespace) -> int:
    root = find_root(args.root)
    engine, eff = load_engine(root, args.run_id)
    if getattr(args, "set", None):
        # operational override on resume (e.g. a longer provider timeout); recorded as an event
        from .config import CouncilConfig, _deep_merge
        merged = _deep_merge(engine.store.data.effective_config, parse_set_overrides(args.set), {}, "resume_override")
        cfg = CouncilConfig.model_validate(merged)
        engine.store.data.effective_config = cfg.model_dump(mode="json")
        for k in args.set:
            engine.store.data.provenance[k.split("=", 1)[0]] = "resume_override"
        engine.cfg = cfg
        eff = EffectiveConfig(config=cfg, provenance=engine.store.data.provenance, layers_present={}, preset=engine.store.data.preset)
        engine.store.event(EventKind.BUDGET_WARNING, {"resume_override": args.set})
        engine.store.save()
    providers = build_providers(eff.config, root, args.run_id)
    try:
        result = drive_until_chat_or_terminal(engine, providers)
    except ProviderError as e:
        print(f"provider error: {e}", file=sys.stderr)
        return 1
    _clear_recovered_failure(engine)
    write_dashboard(engine)
    print(render_result(engine, result))
    return 0


def _claude_code_effort() -> Optional[str]:
    """Claude Code exports CLAUDE_EFFORT (low|medium|high|…) to the commands it runs: recorded as the chat reply's effort."""
    eff = os.environ.get("CLAUDE_EFFORT")
    return f"claude-code effort {eff}" if eff else None


def _claude_code_model_hint() -> Optional[str]:
    """Model configured in Claude Code's user settings, when present (a hint; --chat-model is authoritative)."""
    for p in (Path.home() / ".claude" / "settings.local.json", Path.home() / ".claude" / "settings.json"):
        try:
            m = json.loads(p.read_text()).get("model")
            if isinstance(m, str) and m:
                return f"{m} (from Claude Code settings)"
        except Exception:  # noqa: BLE001
            continue
    return None


def _maybe_open_dashboard(args: argparse.Namespace, root: Path, engine: Engine, page: Optional[Path]) -> None:
    """``--ui`` starts (or reuses) the local server and opens the served dashboard; ``--open`` opens the file."""
    try:
        if getattr(args, "ui", False):
            from .ui import ensure_server
            base = ensure_server(root, engine.cfg.storage.ui_port)
            url = f"{base}/runs/{urllib.parse.quote(engine.store.data.run_id)}/"
            print(f"dashboard: {url}")
            webbrowser.open(url)
        elif getattr(args, "open", False) and page is not None:
            print(f"dashboard: {page}")
            webbrowser.open(page.resolve().as_uri())
        elif page is not None:
            print(f"dashboard: {page}")
    except Exception as e:  # noqa: BLE001 - never block the run on a browser problem
        print(f"dashboard could not be opened: {e}", file=sys.stderr)


def _clear_recovered_failure(engine: Engine) -> None:
    """A provider error recorded by an earlier `start`/`next` is stale once the run advanced past it.

    The error stays in events.jsonl (route_fallback / request_failed); only the run-level flag is cleared,
    so a COMPLETE run no longer prints `failure: provider error …`."""
    d = engine.store.data
    if d.failure_reason and d.state != RunState.FAILED and d.failure_reason.startswith("provider error"):
        engine.store.event(EventKind.BUDGET_WARNING, {"recovered_from": d.failure_reason})
        d.failure_reason = None
        engine.store.save()


def cmd_submit(args: argparse.Namespace) -> int:
    root = find_root(args.root)
    engine, eff = load_engine(root, args.run_id)
    d = engine.store.data
    if args.response == "-":
        raw = sys.stdin.read()   # copy-paste mode: `council submit <run> - --request-id req_x < reply.json` or a pasted heredoc
    else:
        path = Path(args.response)
        if not path.exists():
            print(f"error: response file {path} not found", file=sys.stderr)
            return 2
        raw = path.read_text()
    from .providers.base import parse_reply_json
    submission = parse_reply_json(raw)
    if args.request_id and (d.pending_request is None or d.pending_request.request_id != args.request_id):
        prior = [v for k, v in d.dedup.items() if v.get("request_id") == args.request_id]
        if prior:
            print(f"duplicate submission for {args.request_id}: already {prior[-1]['outcome']} (idempotent, no change)")
            return 0
        print(f"error: request {args.request_id} is not pending and has no recorded outcome", file=sys.stderr)
        return 2
    if d.pending_request is None:
        print("error: no pending request; run `council next` to see the current state", file=sys.stderr)
        return 2
    pending_id = d.pending_request.request_id
    # keep a copy of the response next to the request for audit
    (engine.store.run_dir / "responses" / f"{pending_id}.json").write_text(raw)
    from .engine import ReplyMeta
    if getattr(args, "chat_model", None):
        d.chat_model = args.chat_model
    req_file = engine.store.run_dir / "requests" / f"{pending_id}.json"
    latency = round(max(0.0, time.time() - req_file.stat().st_mtime), 1) if req_file.exists() else None
    try:
        result = engine.step(submission if isinstance(submission, dict) else {"__not_an_object__": submission},
                             ReplyMeta(provider="chat", raw_text=raw, model_reported=d.chat_model, latency_seconds=latency,
                                       effort=getattr(args, "effort", None) or _claude_code_effort()))
    except RejectedUpdate as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if result.status == "request":
        providers = build_providers(eff.config, root, args.run_id)
        try:
            result = drive_until_chat_or_terminal(engine, providers)
        except ProviderError as e:
            print(f"provider error: {e}", file=sys.stderr)
            return 1
    _clear_recovered_failure(engine)
    write_dashboard(engine)
    last_events = [json.loads(l) for l in (engine.store.run_dir / "events.jsonl").read_text().splitlines()[-3:]]
    rejected = [e for e in last_events if e.get("kind") == EventKind.RESPONSE_REJECTED.value and e["payload"].get("request_id") == pending_id]
    if rejected:
        print(f"NOTE: submission for {pending_id} was rejected: {rejected[-1]['payload'].get('error')}")
    print(render_result(engine, result))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = find_root(args.root)
    engine, eff = load_engine(root, args.run_id)
    print(status_text(engine.store, eff.config.limits))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    root = find_root(args.root)
    p = runs_root(root) / args.run_id / "report.md"
    if not p.exists():
        print("no report yet", file=sys.stderr)
        return 1
    print(p.read_text())
    return 0


def cmd_rereport(args: argparse.Namespace) -> int:
    """Rebuild decision.json and report.md from the committed state of a finished run (no model calls).
    The previous record is kept as decision.prev.json."""
    from .report import build_decision, render_report
    root = find_root(args.root)
    engine, eff = load_engine(root, args.run_id)
    d = engine.store.data
    if d.state not in TERMINAL_STATES:
        print("run is not finished", file=sys.stderr)
        return 2
    run_dir = engine.store.run_dir
    if (run_dir / "decision.json").exists():
        (run_dir / "decision.prev.json").write_text((run_dir / "decision.json").read_text())
    d.decision = None
    decision = build_decision(engine)
    d.decision = decision
    (run_dir / "report.md").write_text(render_report(engine, decision))
    (run_dir / "decision.json").write_text(decision.model_dump_json(indent=1))
    engine.store.event(EventKind.RUN_FINISHED, {"rereport": True, "decision": decision.kind.value})
    engine.store.save()
    write_dashboard(engine)
    print(chat_summary(engine, decision))
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Regenerate <run>/index.html from the committed state (no model calls) and optionally open it."""
    root = find_root(args.root)
    engine, _ = load_engine(root, args.run_id)
    page = write_dashboard(engine)
    if page is None:
        print("dashboard disabled (storage.dashboard=false) or could not be written", file=sys.stderr)
        return 2
    print(page)
    if args.open:
        webbrowser.open(page.resolve().as_uri())
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    """Serve the local web UI: runs overview with KPIs, per-run dashboards, settings editor (127.0.0.1 only)."""
    from .ui import pick_port, serve
    root = find_root(args.root)
    port = args.port or load_effective_config(root).config.storage.ui_port
    if not args.port:
        chosen, status = pick_port(root, port)
        if status == "ours":
            print(f"council ui already running at http://127.0.0.1:{chosen}/")
            if not args.no_open:
                webbrowser.open(f"http://127.0.0.1:{chosen}/")
            return 0
        if chosen != port:
            print(f"note: port {port} is used by another program; using {chosen}", file=sys.stderr)
        port = chosen
    return serve(root, port, open_browser=not args.no_open, host=getattr(args, "host", None) or "127.0.0.1",
                 token=getattr(args, "token", None))


def cmd_mcp(args: argparse.Namespace) -> int:
    """MCP server over stdio for chat applications with tool support (Claude Desktop)."""
    from .mcp import serve_stdio
    return serve_stdio(find_root(args.root) if args.root or os.environ.get("COUNCIL_ROOT") else None)


def cmd_cancel(args: argparse.Namespace) -> int:
    root = find_root(args.root)
    try:
        run_dir = locate_run(root, args.run_id)
    except FileNotFoundError:
        print("unknown run", file=sys.stderr)
        return 2
    (run_dir / ".cancel").write_text("cancel requested\n")
    engine, eff = load_engine(root, args.run_id)
    if engine.store.data.state in TERMINAL_STATES:
        print("run already finished")
        return 0
    engine.store.data.cancel_requested = True
    engine.store.data.pending_request = None
    result = engine.result()
    write_dashboard(engine)
    print(render_result(engine, result))
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    root = find_root(args.root)
    from .ui import run_rows
    rows = run_rows(root)
    if not rows:
        print(f"no runs under {runs_root(root)} or {legacy_runs_root(root)}")
        return 0
    print(f"{'run id':<60} {'state':<10} {'outcome':<20} {'conf':<7} {'stop':<16} {'rnd':>3} {'calls':>5}  title")
    for r in rows:
        print(f"{r['run_id'][:60]:<60} {str(r['state']):<10} {str(r['kind'] or ''):<20} {str(r['confidence'] or ''):<7} {str(r['stop_reason'] or ''):<16} "
              f"{str(r['round']):>3} {str(r['calls'] or ''):>5}  {r['title'][:60]}{' (legacy)' if r['legacy'] else ''}")
    return 0


def print_effective(root: Path, eff: EffectiveConfig, *, only_prefix: Optional[str] = None) -> None:
    cfg = eff.config
    print(f"root: {root}")
    print(f"layers present: {eff.layers_present}  preset: {eff.preset}")
    print("effective configuration (value  <- layer):")
    dump = cfg.model_dump(mode="json")

    def walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}" if path else k)
        else:
            if only_prefix and not path.startswith(only_prefix):
                return
            print(f"  {path} = {json.dumps(obj)}  <- {eff.provenance.get(path, 'defaults')}")

    walk(dump)
    print("external routes: " + ("opencode ENABLED" if cfg.routing.opencode.enabled else "none (opencode disabled; binary never spawned)"))
    print("per-role routing:")
    for row in settings_mod.routes_table(cfg):
        print(f"  {row['role']}: {row['provider']} {row['model']} {('(' + row['note'] + ')') if row['note'] else ''}")
    print("limit enforcement:")
    for row in eff.enforcement_table():
        print(f"  {row['limit']}: {row['value']} -> {row['enforcement']}")


def cmd_config_show(args: argparse.Namespace) -> int:
    root = find_root(args.root)
    if getattr(args, "run_id", None):
        engine, eff = load_engine(root, args.run_id)
    else:
        eff = effective(root, args)
    print_effective(root, eff)
    return 0


# ---------------------------------------------------------------------------
# settings interface (saved layer: .council/settings.json)
# ---------------------------------------------------------------------------


def cmd_settings_show(args: argparse.Namespace) -> int:
    root = find_root(args.root)
    saved = settings_mod.read_saved(root)
    print(f"saved settings file: {settings_mod.saved_path(root)} ({'present' if saved else 'absent'})")
    print(json.dumps(saved, indent=2, sort_keys=True) if saved else "  (no saved settings; project defaults apply)")
    print()
    eff = load_effective_config(root)
    print_effective(root, eff, only_prefix=getattr(args, "section", None))
    print("precedence: defaults < council.config.json (project) < .council/settings.json (saved) < --preset < per-run overrides")
    return 0


def cmd_settings_set(args: argparse.Namespace) -> int:
    root = find_root(args.root)
    try:
        saved, eff = settings_mod.set_values(root, args.items)
    except (settings_mod.SettingsError, ValueError) as e:
        print(f"error: {e}\nnothing written", file=sys.stderr)
        return 2
    print(f"saved {len(args.items)} value(s) to {settings_mod.saved_path(root)}:")
    for item in args.items:
        key = item.split("=", 1)[0]
        print(f"  {key} = {json.dumps(_lookup(eff.config.model_dump(mode='json'), key))}  <- saved")
    print("external routes: " + ("opencode ENABLED" if eff.config.routing.opencode.enabled else "none (opencode disabled)"))
    return 0


def _lookup(d: Any, path: str) -> Any:
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def cmd_settings_unset(args: argparse.Namespace) -> int:
    root = find_root(args.root)
    try:
        saved, eff = settings_mod.unset_values(root, args.keys)
    except (settings_mod.SettingsError, ValueError) as e:
        print(f"error: {e}\nnothing written", file=sys.stderr)
        return 2
    print(f"removed {args.keys} from saved settings; effective values now:")
    for key in args.keys:
        print(f"  {key} = {json.dumps(_lookup(eff.config.model_dump(mode='json'), key))}  <- {eff.provenance.get(key, 'defaults')}")
    return 0


def cmd_settings_reset(args: argparse.Namespace) -> int:
    root = find_root(args.root)
    if not args.yes:
        print("refusing to delete saved settings without --yes", file=sys.stderr)
        return 2
    removed = settings_mod.reset(root)
    print("saved settings removed" if removed else "no saved settings to remove")
    return 0


def cmd_settings_validate(args: argparse.Namespace) -> int:
    root = find_root(args.root)
    candidate = json.loads(Path(args.file).read_text()) if args.file else settings_mod.read_saved(root)
    try:
        eff = settings_mod.validate_candidate(root, candidate)
    except settings_mod.SettingsError as e:
        print(f"INVALID: {e}", file=sys.stderr)
        return 2
    print("VALID: effective configuration accepted")
    print(f"external routes: {'opencode ENABLED' if eff.config.routing.opencode.enabled else 'none'}")
    return 0


def cmd_settings_routes(args: argparse.Namespace) -> int:
    root = find_root(args.root)
    eff = load_effective_config(root)
    print("role routing (effective):")
    for row in settings_mod.routes_table(eff.config):
        print(f"  {row['role']:<14} provider={row['provider']:<9} model={row['model']} sampling={row['sampling']} {row['note']}")
    oc = eff.config.routing.opencode
    print(f"opencode: enabled={oc.enabled} binary={oc.binary} agent={oc.agent} standalone={oc.standalone} fallback={oc.fallback} default_model={oc.default_model}")
    return 0


def cmd_settings_presets(args: argparse.Namespace) -> int:  # noqa: D401
    from .settings import PRESET_DOCS
    for name, body in settings_mod.describe_presets().items():
        print(f"{name}: {PRESET_DOCS.get(name, '')}")
        print(f"    overrides: {json.dumps(body) if body else '(project defaults)'}")
    return 0


def _cmd_settings_presets_old(args: argparse.Namespace) -> int:
    for name, body in settings_mod.describe_presets().items():
        print(f"{name}: {json.dumps(body) if body else '(project defaults)'}")
    return 0


def cmd_settings_wizard(args: argparse.Namespace) -> int:
    """Guided configuration. Prints each question with the current value; answers are given as
    --answer key=value (repeatable) and applied through the same validated path as `set`."""
    root = find_root(args.root)
    eff = load_effective_config(root)
    plan = settings_mod.wizard_plan(eff.config)
    if not args.answer:
        print("settings wizard — current effective values (answer with --answer key=value, repeatable):")
        for row in plan:
            print(f"  {row['key']}: {row['question']} [current {row['current']}, default {row['default']}]")
        return 0
    unknown = [a.split('=', 1)[0] for a in args.answer if a.split('=', 1)[0] not in {r['key'] for r in plan}]
    if unknown:
        print(f"error: not wizard keys: {unknown} (use `council settings set` for other keys)", file=sys.stderr)
        return 2
    try:
        saved, eff2 = settings_mod.set_values(root, args.answer)
    except (settings_mod.SettingsError, ValueError) as e:
        print(f"error: {e}\nnothing written", file=sys.stderr)
        return 2
    print(f"saved {len(args.answer)} answer(s); effective configuration:")
    print_effective(root, eff2)
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--root", help="project root (default: auto-detect)")


def _config_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--preset", choices=["standard", "quick", "deep", "first_pass"])
    p.add_argument("--opencode", action="store_true", help="explicit per-run override enabling the OpenCode route")
    p.add_argument("--provider", choices=["chat", "fixture", "opencode"], help="default provider override")
    p.add_argument("--fixture", help="deterministic fixture file (sets default provider to fixture)")
    p.add_argument("--lenses", help="comma-separated explicit lens ids")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override a config key (JSON value)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="council", description="Strategy Tribunal decision engine")
    ap.add_argument("--version", action="version", version=f"council {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("start", help="start a run in step mode (chat entry point)")
    p.add_argument("question", nargs="?")
    p.add_argument("--args-file", help="file holding the raw arguments typed after /council (question + flags)")
    p.add_argument("--args", help="raw argument string (question + flags)")
    p.add_argument("--run-id")
    p.add_argument("--open", action="store_true", help="open the run's dashboard (index.html) in the browser")
    p.add_argument("--ui", action="store_true", help="start/reuse the local web UI and open the served dashboard")
    p.add_argument("--allow-fixture-mismatch", action="store_true", help="replay a test fixture even if it was recorded for another question")
    p.add_argument("--chat-model", help="identity of the conversation model answering chat requests (recorded as who answered)")
    p.add_argument("--chat-tools", choices=["host", "none"], help="whether the chat host has file/shell tools (host, default) or not (none: copy-paste chats such as claude.ai or ChatGPT)")
    p.add_argument("--docs", help="comma-separated files/folders the council must read (copied to <run>/inputs, registered as evidence)")
    _config_flags(p)
    _common(p)
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("run", help="run autonomously with fixture/opencode providers")
    p.add_argument("question", nargs="?")
    p.add_argument("--args-file")
    p.add_argument("--args")
    p.add_argument("--run-id")
    p.add_argument("--open", action="store_true", help="open the run's dashboard (index.html) in the browser")
    p.add_argument("--ui", action="store_true", help="start/reuse the local web UI and open the served dashboard")
    p.add_argument("--allow-fixture-mismatch", action="store_true", help="replay a test fixture even if it was recorded for another question")
    p.add_argument("--chat-model")
    p.add_argument("--docs", help="comma-separated files/folders the council must read (copied to <run>/inputs, registered as evidence)")
    _config_flags(p)
    _common(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("dashboard", help="regenerate <run>/index.html from committed state (no model calls)")
    p.add_argument("run_id")
    p.add_argument("--open", action="store_true")
    _common(p)
    p.set_defaults(func=cmd_dashboard)

    p = sub.add_parser("ui", help="local web UI: runs overview, dashboards, settings editor (127.0.0.1)")
    p.add_argument("--port", type=int, help="default: storage.ui_port (8771)")
    p.add_argument("--no-open", action="store_true")
    p.add_argument("--host", help="bind address (default 127.0.0.1; 0.0.0.0 inside a container)")
    p.add_argument("--token", help="access token required on every request when --host is not loopback (default: $COUNCIL_UI_TOKEN or generated)")
    _common(p)
    p.set_defaults(func=cmd_ui)

    p = sub.add_parser("mcp", help="MCP server over stdio (Claude Desktop and other tool-using chat apps)")
    p.add_argument("--root", help="project root (default: auto-detect or $COUNCIL_ROOT)")
    p.set_defaults(func=cmd_mcp)
    p = sub.add_parser("next", help="print the pending request (or advance controller-only steps)")
    p.add_argument("run_id")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="operational config override on resume (recorded)")
    _common(p)
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("resume", help="alias of next")
    p.add_argument("run_id")
    _common(p)
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("submit", help="submit a JSON response to the pending request")
    p.add_argument("run_id")
    p.add_argument("response", help="path of the JSON reply, or - to read it from stdin")
    p.add_argument("--request-id", help="request id the response answers (enables idempotent duplicate detection)")
    p.add_argument("--chat-model", help="identity of the conversation model that wrote this response (recorded on the participant)")
    p.add_argument("--effort", help="effort label for this response (e.g. 'extended thinking'), recorded with the reply")
    _common(p)
    p.set_defaults(func=cmd_submit)

    p = sub.add_parser("status", help="phase, round, open critical objections, incumbent changes, budget")
    p.add_argument("run_id")
    _common(p)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("report", help="print report.md")
    p.add_argument("run_id")
    _common(p)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("rereport", help="rebuild decision.json and report.md from committed state (no model calls)")
    p.add_argument("run_id")
    _common(p)
    p.set_defaults(func=cmd_rereport)

    p = sub.add_parser("cancel", help="cancel a run (partial report)")
    p.add_argument("run_id")
    _common(p)
    p.set_defaults(func=cmd_cancel)

    p = sub.add_parser("runs", help="list runs")
    _common(p)
    p.set_defaults(func=cmd_runs)

    pc = sub.add_parser("config", help="configuration")
    sc = pc.add_subparsers(dest="config_cmd", required=True)
    p = sc.add_parser("show", help="effective configuration with provenance and enforcement")
    p.add_argument("--run-id", dest="run_id")
    _config_flags(p)
    _common(p)
    p.set_defaults(func=cmd_config_show)

    ps = sub.add_parser("settings", help="saved settings interface (.council/settings.json)")
    ss = ps.add_subparsers(dest="settings_cmd", required=True)
    p = ss.add_parser("show", help="saved settings and the resulting effective configuration")
    p.add_argument("--section", help="only print keys under this prefix, e.g. limits")
    _common(p)
    p.set_defaults(func=cmd_settings_show)
    p = ss.add_parser("set", help="validate and save key=value pairs (JSON values)")
    p.add_argument("items", nargs="+", metavar="KEY=VALUE")
    _common(p)
    p.set_defaults(func=cmd_settings_set)
    p = ss.add_parser("unset", help="remove keys from the saved layer")
    p.add_argument("keys", nargs="+")
    _common(p)
    p.set_defaults(func=cmd_settings_unset)
    p = ss.add_parser("reset", help="delete the saved settings file")
    p.add_argument("--yes", action="store_true")
    _common(p)
    p.set_defaults(func=cmd_settings_reset)
    p = ss.add_parser("validate", help="validate the saved settings (or a candidate file)")
    p.add_argument("file", nargs="?")
    _common(p)
    p.set_defaults(func=cmd_settings_validate)
    p = ss.add_parser("routes", help="per-role provider/model routing and external routes")
    _common(p)
    p.set_defaults(func=cmd_settings_routes)
    p = ss.add_parser("presets", help="list presets")
    _common(p)
    p.set_defaults(func=cmd_settings_presets)
    p = ss.add_parser("wizard", help="guided configuration (prints questions; answer with --answer key=value)")
    p.add_argument("--answer", action="append", default=[], metavar="KEY=VALUE")
    _common(p)
    p.set_defaults(func=cmd_settings_wizard)
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (RejectedUpdate, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
