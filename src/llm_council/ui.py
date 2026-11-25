"""Local web UI (standard library only): runs overview with KPIs, per-run dashboards, settings editor.

    council ui [--port 8765] [--no-open]

Binds to 127.0.0.1 only. Pages:
  /                     all runs (new and legacy folders) with kind, confidence, stop reason, rounds, calls, date
  /runs/<run_id>/       the run's dashboard (index.html, regenerated on each request) and its files
  /settings             every configuration key with value, layer and explanation; a form to set / unset / reset
                        saved settings through the same validation as `council settings` (nothing is written
                        when a value is invalid)
  /api/runs.json        the runs overview as JSON
"""

from __future__ import annotations

import html
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

from . import settings as settings_mod
from .config import load_effective_config
from .dashboard import CSS, _bundle_text, _state_script, _theme_init_js, home_state, tabify, write_dashboard
from .ontology import TERMINAL_STATES
from .settings import PRESET_DOCS, SETTINGS_DOCS, allowed_values, describe

APP_ID = "strategy-tribunal"

MIME = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8", ".md": "text/plain; charset=utf-8",
        ".jsonl": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".log": "text/plain; charset=utf-8"}


def _e(x: Any) -> str:
    return html.escape("" if x is None else str(x))


def run_roots(root: Path) -> list[Path]:
    cfg = load_effective_config(root).config
    roots = [root / cfg.storage.runs_root, root / cfg.storage.legacy_runs_root]
    return [r for r in roots if r.exists()]


def run_rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for rr in run_roots(root):
        for p in sorted(rr.iterdir(), reverse=True):
            sp = p / "state.json"
            if not sp.exists():
                continue
            try:
                s = json.loads(sp.read_text())
            except json.JSONDecodeError:
                continue
            dec = s.get("decision") or {}
            title = (p / "TITLE.txt").read_text().strip() if (p / "TITLE.txt").exists() else s.get("question", "")
            b = s.get("budget") or {}
            rows.append({
                "run_id": p.name, "folder": str(p), "title": title, "question": s.get("question", ""), "created_at": s.get("created_at", ""),
                "state": s.get("state"), "round": s.get("round"), "preset": s.get("preset"), "stop_reason": s.get("stop_reason"),
                "kind": dec.get("kind"), "confidence": ((dec.get("confidence") or {}).get("level")),
                "calls": b.get("model_calls_used"), "tokens": (b.get("tokens_measured") or 0) + (b.get("tokens_estimated") or 0),
                "open_objections": sum(1 for c in (s.get("challenges") or {}).values() if c.get("status") in ("open", "unresolved_final")),
                "promotions": sum(1 for h in (s.get("incumbent_history") or []) if h.get("outcome") == "promoted"),
                "legacy": rr.name == "runs",
            })
    return rows


NAV = ("<nav style='margin-bottom:10px'>"
       "<a href='/' style='display:inline-block;padding:6px 12px;border:1px solid var(--line);border-radius:6px;background:#fff;margin-right:8px'>&#9776; Works</a>"
       "<a href='/settings' style='display:inline-block;padding:6px 12px;border:1px solid var(--line);border-radius:6px;background:#fff'>&#9881; Settings</a>"
       "</nav>")

NAV_TW = ("<nav class='mb-2 flex gap-2'>"
          "<a href='/' class='inline-flex h-9 items-center gap-1 rounded-md border border-input bg-background px-3 text-sm font-medium shadow-sm hover:bg-accent hover:text-accent-foreground'>&#9776; Works</a>"
          "<a href='/settings' class='inline-flex h-9 items-center gap-1 rounded-md border border-input bg-background px-3 text-sm font-medium shadow-sm hover:bg-accent hover:text-accent-foreground'>&#9881; Settings</a>"
          "</nav>")


def page(title: str, body: str, nav: str = "") -> str:
    """Server-rendered page (settings): the bundle's base styles for the chrome, the legacy rules for the body."""
    # the settings page is server-rendered with the legacy stylesheet: it stays in light mode whatever the theme toggle says
    return (f"<!doctype html><html lang='en' style='color-scheme:light'><head><meta charset='utf-8'><title>{_e(title)}</title>"
            f"<style>{_bundle_text('dashboard.css')}</style><style>{CSS}"
            "body{background:var(--bg);color:var(--ink)}header{background:#fff;border-color:var(--line)}"
            "main{max-width:80rem;margin:0 auto;padding:0 1.75rem 3rem}"
            ".work header{border:none;padding:0 0 10px;background:transparent}.work h1{font-size:19px}</style></head><body>"
            f"<header class='border-b bg-background px-7 py-4'>{NAV_TW}<h1 class='text-xl font-semibold'>{_e(title)}</h1>{nav}</header><main>{body}</main></body></html>")


def local_time(iso: Optional[str]) -> str:
    """ISO timestamp (UTC, as stored) rendered in the machine's local time, minute precision."""
    if not iso:
        return ""
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso[:16].replace("T", " ")


def runs_page(root: Path) -> str:
    """Home page: a React single-page app with one tab per work plus the overview table."""
    rows = run_rows(root)
    for r in rows:
        r["when"] = local_time(r["created_at"])
        r["label"] = f"{r['when']} · {r['title'][:38]}" if r["title"] else r["when"]
        r["stateMark"] = {"COMPLETE": "", "FAILED": " ✖", "CANCELLED": " ⊘"}.get(r["state"] or "", " ⏳")
    state = home_state(root, rows)
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Strategy Tribunal — works</title>"
            f"{_theme_init_js()}<style>{_bundle_text('dashboard.css')}</style></head><body>"
            f"<header class='border-b bg-background px-7 py-4'>{NAV_TW}<h1 class='text-xl font-semibold'>Strategy Tribunal — works</h1></header>"
            "<a class='skip-link' href='#council-main'>Skip to content</a>"
            '<main id="council-main" class="mx-auto max-w-7xl px-7 pb-12"><div id="council-root"></div></main>'
            "<noscript><p style='padding:20px'>The overview needs JavaScript; the per-run dashboards are listed in <a href='/api/runs.json'>/api/runs.json</a>.</p></noscript>"
            + _state_script("council-home-state", state)
            + f"<script>{_bundle_text('dashboard.js')}</script></body></html>")


ROLES = ("framer", "policy_setter", "strategist", "reviewer", "verifier", "judge", "challenger")
_MODELS_CACHE: dict[str, Any] = {"at": 0.0, "models": []}


def opencode_models(binary: str = "opencode", max_age: float = 300.0) -> list[str]:
    """Models OpenCode can reach (`opencode models`), cached for a few minutes; empty when OpenCode is absent."""
    if time.time() - _MODELS_CACHE["at"] < max_age and _MODELS_CACHE["models"]:
        return _MODELS_CACHE["models"]
    try:
        proc = subprocess.run([binary, "models"], capture_output=True, text=True, timeout=20)
        models = sorted({l.strip() for l in proc.stdout.splitlines() if "/" in l and " " not in l.strip()})
    except Exception:  # noqa: BLE001 - no OpenCode, no list
        models = []
    _MODELS_CACHE.update(at=time.time(), models=models)
    return models


def _select(name: str, options: list[tuple[str, str]], current: Optional[str], allow_free: bool = False) -> str:
    opts = "".join(f"<option value='{_e(v)}'{' selected' if v == (current or '') else ''}>{_e(label)}</option>" for v, label in options)
    free = f" <input name='{_e(name)}__free' placeholder='or type provider/model' style='width:220px;font:13px ui-monospace,monospace'>" if allow_free else ""
    return f"<select name='{_e(name)}'>{opts}</select>{free}"


def defaults_panel(root: Path, eff) -> str:
    """The questions people change most, as a form: default route, default model, model per role, default preset, chat identity."""
    cfg = eff.config
    models = opencode_models(cfg.routing.opencode.binary)
    model_opts = [("", "(use routing.opencode.default_model)")] + [(m, m) for m in models]
    route = "opencode" if cfg.routing.default_provider == "opencode" else "chat"
    rows = [
        "<form method='post' action='/settings/defaults'>",
        "<table><tr><th style='width:260px'>setting</th><th>value</th><th>explanation</th></tr>",
        f"<tr><td>Default route for every role</td><td>{_select('route', [('chat', 'chat — the Claude Code conversation model (one model, shared context)'), ('opencode', 'opencode — external models in isolated sessions')], route)}</td>"
        "<td class='small'>routing.default_provider. <strong>chat</strong>: every role is played by the model of the Claude Code conversation you type in; one model, shared context, tokens estimated, no cost reported. "
        "<strong>opencode</strong>: every role runs in a fresh isolated OpenCode session with the model chosen below; identity, tokens and latency are measured; choosing it also sets routing.opencode.enabled=true. "
        "Per-role choices below override this for single roles.</td></tr>",
        f"<tr><td>Default OpenCode model</td><td>{_select('default_model', [(m, m) for m in models] or [(cfg.routing.opencode.default_model or '', cfg.routing.opencode.default_model or '(none)')], cfg.routing.opencode.default_model, allow_free=True)}</td>"
        f"<td class='small'>routing.opencode.default_model — used by every OpenCode-routed role without its own model. {len(models)} models listed by `opencode models`" + ("" if models else " (OpenCode not reachable: type the id)") + ".</td></tr>",
        f"<tr><td>Default preset</td><td>{_select('preset', [('', '(none: standard project limits)'), ('quick', 'quick'), ('standard', 'standard'), ('deep', 'deep'), ('first_pass', 'first_pass')], cfg.defaults.preset)}</td>"
        "<td class='small'>defaults.preset — the bundle of rounds, call cap, reviewers, verifications and lenses a run uses when /council or the CLI names no --preset. "
        + " ".join(f"<br><strong>{k}</strong>: {_e(v)}." for k, v in PRESET_DOCS.items()) + "</td></tr>",
        f"<tr><td>Chat model identity</td><td><input name='chat_model' value='{_e(cfg.defaults.chat_model or '')}' placeholder='e.g. claude-sonnet-5-5' style='width:260px'></td>"
        "<td class='small'>defaults.chat_model — the name recorded as 'who answered' for chat-routed roles when a run does not pass --chat-model (the /council skill passes its own id, so this is a fallback for runs started by hand). It does not change which model answers: that is decided by the Claude Code session.</td></tr>",
        "</table>",
        "<h3 style='margin:14px 0 6px'>Model per role</h3>",
        "<table><tr><th style='width:160px'>role</th><th>provider</th><th>model (OpenCode)</th><th>explanation</th></tr>",
    ]
    why = {"framer": "turns the question into the brief", "policy_setter": "registers gates, criteria and weights", "strategist": "proposes options through the lenses",
           "reviewer": "raises typed objections and dissent", "verifier": "checks evidence behind objections", "judge": "scores every option version", "challenger": "argues the strongest case against the leader"}
    for role in ROLES:
        rr = cfg.routing.roles.get(role)
        prov = (rr.provider if rr and rr.provider else "")
        model = (rr.model if rr and rr.model else "")
        rows.append(f"<tr><td><code>{role}</code></td><td>{_select(f'role.{role}.provider', [('', 'inherit default route'), ('chat', 'chat'), ('opencode', 'opencode')], prov)}</td>"
                    f"<td>{_select(f'role.{role}.model', model_opts, model, allow_free=True)}</td><td class='small'>{_e(why[role])}</td></tr>")
    rows += ["</table>",
             "<p><button type='submit'>Save defaults</button> <span class='small muted'>Writes the saved layer (.council/settings.json) through the same validation as `council settings set`; per-run flags still override.</span></p></form>"]
    return "\n".join(rows)


def defaults_to_items(form: dict[str, str]) -> tuple[list[str], list[str]]:
    """Translate the defaults form into (`key=value` items to set, keys to unset) for the saved layer."""
    items: list[str] = []
    unset: list[str] = []
    route = form.get("route")
    if route in ("chat", "opencode"):
        items.append(f'routing.default_provider="{route}"')
        if route == "opencode":
            items.append("routing.opencode.enabled=true")
    model = (form.get("default_model__free") or form.get("default_model") or "").strip()
    if model:
        items.append(f'routing.opencode.default_model="{model}"')
    preset = form.get("preset", "")
    (items.append(f'defaults.preset="{preset}"') if preset else unset.append("defaults.preset"))
    chat_model = (form.get("chat_model") or "").strip()
    (items.append(f'defaults.chat_model="{chat_model}"') if chat_model else unset.append("defaults.chat_model"))
    for role in ROLES:
        prov = form.get(f"role.{role}.provider", "")
        m = (form.get(f"role.{role}.model__free") or form.get(f"role.{role}.model") or "").strip()
        (items.append(f'routing.roles.{role}.provider="{prov}"') if prov else unset.append(f"routing.roles.{role}.provider"))
        (items.append(f'routing.roles.{role}.model="{m}"') if m else unset.append(f"routing.roles.{role}.model"))
        if prov == "opencode":
            items.append("routing.opencode.enabled=true")
    return items, unset


def apply_defaults_form(root: Path, form: dict[str, str]) -> None:
    items, unset = defaults_to_items(form)
    saved = settings_mod.read_saved(root)

    def present(key: str) -> bool:
        cur: Any = saved
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return False
            cur = cur[part]
        return True

    to_unset = [k for k in unset if present(k)]
    if to_unset:
        settings_mod.unset_values(root, to_unset)
    if items:
        settings_mod.set_values(root, items)


def settings_page(root: Path, message: str = "", error: str = "") -> str:
    eff = load_effective_config(root)
    saved = settings_mod.read_saved(root)
    dump = eff.config.model_dump(mode="json")
    rows = []

    def walk(d: dict, prefix: str = "") -> None:
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict) and v and key not in ("policy.weight_overrides", "routing.opencode.model_fallbacks") and not key.startswith("routing.roles."):
                walk(v, key)
            else:
                rows.append((key, v))

    walk(dump)
    for role in ("framer", "policy_setter", "strategist", "reviewer", "verifier", "judge", "challenger"):
        if role not in dump["routing"]["roles"]:
            rows.append((f"routing.roles.{role}.provider", None))
            rows.append((f"routing.roles.{role}.model", None))
    body = []
    if message:
        body.append(f"<p><span class='badge ok'>saved</span> {_e(message)}</p>")
    if error:
        body.append(f"<p><span class='badge bad'>refused</span> {_e(error)} — nothing written.</p>")
    body.append(f"<p class='small muted'>Saved file: <code>{_e(settings_mod.saved_path(root))}</code> ({'present' if saved else 'absent'}). "
                "Precedence: defaults &lt; council.config.json &lt; saved &lt; preset &lt; per-run flags. Values are JSON (true, 3, 0.5, \"text\", null, {...}). "
                "Every change is validated against the whole configuration before it is written.</p>")
    body.append("<h2>Defaults — which model to use in general</h2>")
    body.append(defaults_panel(root, eff))
    body.append("<h2>All settings</h2>")
    body.append("<p class='small muted'>Every key, what it means, the values it accepts, where its current value comes from, and a field to change it. Type a JSON value and press Save; an invalid value is refused with the reason.</p>")
    body.append("<form method='post' action='/settings'><table><tr><th>key</th><th>effective value</th><th>layer</th><th>allowed values</th><th>new value (JSON)</th><th>explanation</th></tr>")
    for key, val in rows:
        layer = eff.provenance.get(key) or next((v for k, v in eff.provenance.items() if k.startswith(key + ".")), "defaults" if val is not None else "unset")
        cls = {"override": "warn", "saved": "ok"}.get(layer.split(":")[0], "")
        body.append(f"<tr><td><code>{_e(key)}</code></td><td><code>{_e(json.dumps(val))}</code></td><td><span class='badge {cls}'>{_e(layer)}</span></td><td class='small muted'>{_e(allowed_values(key))}</td>"
                    f"<td><input name='{_e(key)}' placeholder='leave empty to keep' style='width:100%;font:13px ui-monospace,monospace'></td><td class='small'>{_e(describe(key))}</td></tr>")
    body.append("</table><p><button type='submit' name='action' value='set'>Save changed values</button> "
                "<button type='submit' name='action' value='unset' title='removes the saved value of every key you filled with anything'>Unset filled keys</button> "
                "<button type='submit' name='action' value='reset' onclick=\"return confirm('Delete the saved settings file?')\">Reset saved settings</button></p></form>")
    body.append("<h2>Saved layer</h2><pre>" + _e(json.dumps(saved, indent=2, sort_keys=True) if saved else "(none)") + "</pre>")
    body.append("<h2>Presets explained</h2><table><tr><th>preset</th><th>what it means</th><th>exact overrides</th></tr>")
    for name, body_ov in settings_mod.describe_presets().items():
        body.append(f"<tr><td><code>{_e(name)}</code></td><td class='small'>{_e(PRESET_DOCS.get(name, ''))}</td><td class='small muted'><code>{_e(json.dumps(body_ov))}</code></td></tr>")
    body.append("</table>")
    # the form that spans "All settings" must stay inside one tab: it does, because tabify splits only at <h2>
    notices = [c for c in body if c.startswith("<p><span class='badge")]
    rest = [c for c in body if not c.startswith("<p><span class='badge")]
    layout = [("defaults", "Defaults", ["Defaults"]), ("all", "All settings", ["All settings"]),
              ("presets", "Presets", ["Presets explained"]), ("saved", "Saved layer", ["Saved layer"])]
    return page("Strategy Tribunal — settings", "\n".join(notices) + tabify(rest, layout))


# Settings the web form may never write: they name executables or file locations the server would then use.
WEB_FORM_DENIED = ("routing.opencode.binary", "routing.opencode.config_dir", "routing.opencode.agent", "routing.opencode.standalone",
                   "routing.opencode.env", "storage.runs_root", "storage.legacy_runs_root", "fixture_path")
_FORM_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)*")


def _leaf_paths(key: str, value: Any) -> list[str]:
    """Every dotted leaf a form field would write: `routing.opencode={"binary": "x"}` → routing.opencode.binary."""
    parsed: Any = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = value
    if isinstance(parsed, dict):
        out: list[str] = []
        for k, v in parsed.items():
            out.extend(_leaf_paths(f"{key}.{k}", v))
        return out or [key]
    return [key]


def web_form_allowed(form: dict[str, Any]) -> Optional[str]:
    """None when every field may be written from the browser; otherwise the message to show.
    Checks the leaves a field would write, and refuses writing any ancestor of a denied path as a whole object."""
    bad: set[str] = set()
    for key, value in form.items():
        if not _FORM_KEY.fullmatch(key):
            return f"{key!r}: not a setting name (letters, digits, underscores and dots only)"
        for leaf in _leaf_paths(key, value):
            if any(leaf == d or leaf.startswith(d + ".") or d.startswith(leaf + ".") for d in WEB_FORM_DENIED):
                bad.add(key)
    if bad:
        return f"{', '.join(sorted(bad))}: not settable from the web form (use `council settings set` in the terminal)"
    return None


class Handler(BaseHTTPRequestHandler):
    root: Path = Path(".")
    token: Optional[str] = None      # required on every request when the server is bound to a non-loopback address
    extra_hosts: set[str] = set()    # extra Host values this server answers to (COUNCIL_UI_HOSTS); loopback is always accepted

    def _host_allowed(self, value: str) -> bool:
        """DNS-rebinding and CSRF guard: the Host (or Origin) must name this machine, the bind address, or a listed host."""
        netloc = value.lower().strip()
        if not netloc:
            return False
        hostname = netloc.rsplit(":", 1)[0] if netloc.count(":") == 1 or netloc.startswith("[") else netloc
        hostname = hostname.strip("[]")
        if hostname in ("127.0.0.1", "localhost", "::1"):
            return True
        bind = str(self.server.server_address[0]).lower()
        if hostname == bind and bind not in ("0.0.0.0", "::"):
            return True
        return netloc in self.extra_hosts or hostname in self.extra_hosts

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet
        return

    def _cookie(self, name: str) -> Optional[str]:
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return None

    def _gate(self, mutating: bool) -> bool:
        """Token check (non-loopback binds) and Origin check (state-changing requests). False = response already sent."""
        if not self._host_allowed(self.headers.get("Host") or ""):
            self._send(HTTPStatus.FORBIDDEN, b"forbidden: unexpected Host header")
            return False
        if self.token:
            url = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(url.query).get("token", [""])[0]
            auth = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            if secrets.compare_digest(q, self.token) and not mutating:
                # first visit with ?token=…: set the cookie and continue without the token in the address bar
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Set-Cookie", f"council_token={self.token}; HttpOnly; SameSite=Strict; Path=/")
                self.send_header("Location", url.path or "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return False
            if not (secrets.compare_digest(self._cookie("council_token") or "", self.token) or secrets.compare_digest(auth, self.token)):
                self._send(HTTPStatus.UNAUTHORIZED, b"unauthorized: open the interface with the ?token=... link printed at start")
                return False
        if mutating:
            origin = self.headers.get("Origin") or ""
            host = (self.headers.get("Host") or "").lower()
            if origin and urllib.parse.urlparse(origin).netloc.lower() != host:
                self._send(HTTPStatus.FORBIDDEN, b"forbidden: cross-origin request")
                return False
            fetch_site = self.headers.get("Sec-Fetch-Site")
            if fetch_site and fetch_site not in ("same-origin", "none"):
                self._send(HTTPStatus.FORBIDDEN, b"forbidden: cross-site request")
                return False
        return True

    def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _locate(self, run_id: str) -> Optional[Path]:
        for rr in run_roots(self.root):
            p = (rr / run_id).resolve()
            if p.parent == rr.resolve() and (p / "state.json").exists():
                return p
        return None

    def do_GET(self) -> None:  # noqa: N802
        if not self._gate(mutating=False):
            return None
        url = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(url.path)
        if path == "/":
            return self._send(HTTPStatus.OK, runs_page(self.root).encode())
        if path == "/settings":
            return self._send(HTTPStatus.OK, settings_page(self.root).encode())
        if path == "/favicon.ico":
            return self._send(HTTPStatus.NO_CONTENT, b"", "image/x-icon")
        if path == "/api/health":
            return self._send(HTTPStatus.OK, json.dumps({"app": APP_ID, "root": str(self.root)}).encode(), MIME[".json"])
        if path == "/api/runs.json":
            return self._send(HTTPStatus.OK, json.dumps(run_rows(self.root), indent=1).encode(), MIME[".json"])
        if path.startswith("/runs/"):
            parts = path[len("/runs/"):].split("/", 1)
            run_dir = self._locate(parts[0])
            if run_dir is None:
                return self._send(HTTPStatus.NOT_FOUND, b"unknown run")
            rel = parts[1] if len(parts) > 1 else ""
            if rel in ("", "index.html"):
                try:
                    from .cli import load_engine
                    engine, _ = load_engine(self.root, parts[0])
                    write_dashboard(engine, served=True)
                except Exception:  # noqa: BLE001 - fall back to the file on disk
                    pass
                rel = "index.html"
            target = (run_dir / rel).resolve()
            if run_dir.resolve() not in target.parents or not target.is_file():
                return self._send(HTTPStatus.NOT_FOUND, b"not found")
            return self._send(HTTPStatus.OK, target.read_bytes(), MIME.get(target.suffix, "application/octet-stream"))
        return self._send(HTTPStatus.NOT_FOUND, b"not found")

    def do_DELETE(self) -> None:  # noqa: N802
        """Delete one work: `DELETE /runs/<run_id>/` removes the run folder after the same checks as GET."""
        if not self._gate(mutating=True):
            return None
        url = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(url.path)
        if path.startswith("/runs/"):
            parts = path[len("/runs/"):].split("/", 1)
            if len(parts) == 1 or parts[1] in ("", "/"):
                run_dir = self._locate(parts[0])
                if run_dir is None:
                    return self._send(HTTPStatus.NOT_FOUND, b"unknown run")
                try:
                    shutil.rmtree(run_dir)
                except OSError as exc:
                    return self._send(HTTPStatus.INTERNAL_SERVER_ERROR, json.dumps({"error": f"could not delete {parts[0]}: {exc}"}).encode(), MIME[".json"])
                return self._send(HTTPStatus.OK, json.dumps({"deleted": parts[0]}).encode(), MIME[".json"])
        return self._send(HTTPStatus.NOT_FOUND, b"not found")

    def do_POST(self) -> None:  # noqa: N802
        if not self._gate(mutating=True):
            return None
        path = urllib.parse.urlparse(self.path).path
        if path == "/settings/defaults":
            length = int(self.headers.get("Content-Length", "0"))
            form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(length).decode(), keep_blank_values=True).items()}
            try:
                denied = web_form_allowed(form)
                if denied:
                    return self._send(HTTPStatus.OK, settings_page(self.root, error=denied).encode())
                apply_defaults_form(self.root, form)
                return self._send(HTTPStatus.OK, settings_page(self.root, message="defaults saved").encode())
            except (settings_mod.SettingsError, ValueError) as e:
                return self._send(HTTPStatus.OK, settings_page(self.root, error=str(e)).encode())
        if path != "/settings":
            return self._send(HTTPStatus.NOT_FOUND, b"not found")
        length = int(self.headers.get("Content-Length", "0"))
        form = urllib.parse.parse_qs(self.rfile.read(length).decode(), keep_blank_values=False)
        action = (form.get("action") or ["set"])[0]
        filled = {k: v[0].strip() for k, v in form.items() if k != "action" and v and v[0].strip()}
        try:
            if action == "reset":
                settings_mod.reset(self.root)
                return self._send(HTTPStatus.OK, settings_page(self.root, message="saved settings removed").encode())
            if action == "unset":
                if not filled:
                    return self._send(HTTPStatus.OK, settings_page(self.root, error="fill the keys to unset").encode())
                settings_mod.unset_values(self.root, list(filled))
                return self._send(HTTPStatus.OK, settings_page(self.root, message=f"removed {sorted(filled)}").encode())
            if not filled:
                return self._send(HTTPStatus.OK, settings_page(self.root, error="no value entered").encode())
            denied = web_form_allowed(filled)
            if denied:
                return self._send(HTTPStatus.OK, settings_page(self.root, error=denied).encode())
            items = [f"{k}={v}" for k, v in filled.items()]
            settings_mod.set_values(self.root, items)
            return self._send(HTTPStatus.OK, settings_page(self.root, message=f"saved {sorted(filled)}").encode())
        except (settings_mod.SettingsError, ValueError) as e:
            return self._send(HTTPStatus.OK, settings_page(self.root, error=str(e)).encode())


def serve(root: Path, port: int, open_browser: bool = True, open_path: str = "/", host: str = "127.0.0.1",
          token: Optional[str] = None) -> int:
    """Serve on host:port (127.0.0.1 by default; 0.0.0.0 inside a container). Returns 2 when the port is taken.
    A non-loopback bind requires a token on every request (``token`` or ``COUNCIL_UI_TOKEN``, else one is generated)."""
    Handler.root = root
    loopback = host in ("127.0.0.1", "localhost", "::1")
    Handler.token = None if loopback else (token or os.environ.get("COUNCIL_UI_TOKEN") or secrets.token_urlsafe(24))
    # Host/Origin allowlist: loopback names and the bind address always; other names via COUNCIL_UI_HOSTS (comma-separated)
    Handler.extra_hosts = {h.strip().lower() for h in os.environ.get("COUNCIL_UI_HOSTS", "").split(",") if h.strip()}
    try:
        httpd = ThreadingHTTPServer((host, port), Handler)
    except OSError as e:
        owner = "another council ui" if is_ours(port) else "another program"
        print(f"error: port {port} is in use by {owner} ({e}); pick one with --port or set storage.ui_port", file=sys.stderr)
        return 2
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}{open_path}"
    print(f"council ui at {url} (Ctrl-C to stop)", flush=True)
    if Handler.token:
        print(f"bound to {host}: every request needs the token. Open {url}?token={Handler.token} once (sets a cookie), "
              f"or send 'Authorization: Bearer {Handler.token}'. Set COUNCIL_UI_TOKEN to choose it. Publish to loopback where "
              "possible (docker run -p 127.0.0.1:8771:8771 …).", flush=True)
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def is_up(port: int) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def is_ours(port: int, root: Optional[Path] = None) -> bool:
    """True when the program on the port is a council ui (same project root when ``root`` is given)."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as r:
            data = json.loads(r.read().decode())
    except Exception:  # noqa: BLE001 - anything else on the port is not ours
        return False
    return data.get("app") == APP_ID and (root is None or Path(data.get("root", "")).resolve() == root.resolve())


def pick_port(root: Path, preferred: int, attempts: int = 20) -> tuple[int, str]:
    """First port from ``preferred`` upwards that is free or already runs our ui for this root.

    Returns (port, status) with status ``ours`` (reuse), ``free`` (start) — raises RuntimeError when none is usable.
    A port held by any other program (for example another local web app on 8765) is skipped, which is what made the
    browser show that program's "not found" page before this check existed."""
    for port in range(preferred, preferred + attempts):
        if not is_up(port):
            return port, "free"
        if is_ours(port, root):
            return port, "ours"
    raise RuntimeError(f"no free port between {preferred} and {preferred + attempts - 1}")


def ensure_server(root: Path, port: int) -> str:
    """Start `council ui` detached if our server is not already running for this root; return the base URL.

    If ``port`` is taken by another program the next free port is used and reported."""
    chosen, status = pick_port(root, port)
    if chosen != port:
        print(f"note: port {port} is used by another program; council ui uses {chosen}", file=sys.stderr)
    if status == "free":
        log = root / load_effective_config(root).config.storage.runs_root / ".ui.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as fh:
            subprocess.Popen([sys.executable, "-m", "llm_council.cli", "ui", "--port", str(chosen), "--no-open", "--root", str(root)],
                             stdout=fh, stderr=fh, stdin=subprocess.DEVNULL, start_new_session=True, cwd=str(root),
                             env=dict(os.environ, PYTHONPATH=str(root / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")))
        for _ in range(50):
            if is_ours(chosen, root):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError(f"council ui did not come up on port {chosen}; see {log}")
    return f"http://127.0.0.1:{chosen}"
