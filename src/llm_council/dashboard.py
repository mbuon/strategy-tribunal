"""Graphical dashboard: a self-contained ``index.html`` per run folder, rendered as a
React single-page app (React 18 UMD + htm, inlined — no build step, no downloads).

The Python controller computes ``dashboard_state()`` (plain JSON-serializable data) from the
committed records; ``app.js`` renders tabs (ARIA tablist), tables, expandable discussion
entries and a Markdown modal (role=dialog, focus trap, focus return, Esc) client-side.
Run folders stay portable and readable offline: vendor runtime, app and pre-rendered
Markdown are all inline. ``council ui`` serves the same pages plus a settings editor.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .ontology import TERMINAL_STATES
from .settings import describe

if TYPE_CHECKING:  # pragma: no cover
    from .engine import Engine

REFRESH_SECONDS = 5

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2330;--mute:#5d6673;--line:#e2e6ec;--ok:#1d7f4f;--warn:#b26a00;--bad:#b3261e;--acc:#2a5db0}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}
header{background:#fff;border-bottom:1px solid var(--line);padding:18px 28px}h1{margin:0 0 4px;font-size:22px}h2{font-size:17px;margin:28px 0 10px}
.sub{color:var(--mute)}main{padding:0 28px 48px;max-width:1280px}nav a{margin-right:14px;color:var(--acc);text-decoration:none}
.skip-link{position:absolute;left:-9999px;top:0;background:#fff;padding:8px 14px;z-index:100;border:1px solid var(--line);border-radius:0 0 6px 0}
.skip-link:focus{left:8px;top:8px}
a:focus-visible,button:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.badge{display:inline-block;padding:2px 9px;border-radius:12px;font-size:12px;font-weight:600;background:#e8edf5;color:var(--acc);margin-right:6px}
.badge.ok{background:#e3f3ea;color:var(--ok)}.badge.warn{background:#fff1dc;color:var(--warn)}.badge.bad{background:#fbe4e2;color:var(--bad)}
.kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-top:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}.kpi .v{font-size:20px;font-weight:650}.kpi .l{font-size:12px;color:var(--mute)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden;font-size:14px}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{background:#f0f2f6;font-weight:600}tr:last-child td{border-bottom:none}
code,pre{font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}code{background:#eef1f5;padding:1px 5px;border-radius:4px}
pre{background:#fff;border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto;white-space:pre-wrap}
details{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:8px 0}summary{cursor:pointer;font-weight:600}
.report h1,.report h2,.report h3{margin:18px 0 6px}.report h1{font-size:20px}.report h2{font-size:16px}.report li{margin:2px 0}
.muted{color:var(--mute)}.small{font-size:12px}
/* colour language: the kind of verdict is the hue */
:root{--k-firm:#0FA3A3;--k-cond:#F5A524;--k-short:#7C5CFF;--k-info:#2E8BFF;--k-none:#8A93A6;--k-fail:#FF5C6C;--k-run:#8AD425;--acc:#2E5BFF;--ink:#161A2E;--bg:#F3F5FA}
body{font-family:"Avenir Next","Segoe UI Variable Text","Segoe UI",ui-sans-serif,system-ui,sans-serif}
header h1{letter-spacing:-.01em}
nav a{display:inline-block;padding:7px 14px;border-radius:999px;background:#E9EEFF;color:var(--acc);font-weight:600;margin-right:8px;border:none}
nav a:hover{background:var(--acc);color:#fff}
.statbar{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 18px}
.stat{padding:6px 12px;border-radius:999px;background:#fff;border:1px solid var(--line);font-size:14px;color:var(--ink)}
.stat strong{font-size:16px;margin-right:4px}
.stat.k-firm{border-color:var(--k-firm);color:#0b7a7a}.stat.k-cond{border-color:var(--k-cond);color:#9a6400}.stat.k-short{border-color:var(--k-short);color:#5a3fd1}
.stat.k-info{border-color:var(--k-info);color:#1d62c2}.stat.k-none{border-color:var(--k-none);color:#5d6673}.stat.k-fail{border-color:var(--k-fail);color:#c23a47}.stat.k-run{border-color:var(--k-run);color:#4f8a0b}
.home{max-width:960px}
.worklist{display:flex;flex-direction:column;gap:12px}
.workbtn{display:grid;grid-template-columns:10px 1fr auto;gap:14px;align-items:stretch;width:100%;text-align:left;background:#fff;border:1px solid var(--line);border-radius:14px;padding:0;cursor:pointer;font:inherit;color:var(--ink);text-decoration:none;overflow:hidden;transition:transform .08s ease,box-shadow .12s ease}
.wb-rec{font-size:14px;color:#2b3345}
.workbtn:hover{transform:translateY(-1px);box-shadow:0 6px 18px rgba(22,26,46,.08)}
.workbtn:focus-visible{outline:3px solid var(--acc);outline-offset:2px}
.workbtn .stripe{display:block;background:var(--k-none)}
.workbtn.k-firm .stripe{background:var(--k-firm)}.workbtn.k-cond .stripe{background:var(--k-cond)}.workbtn.k-short .stripe{background:var(--k-short)}
.workbtn.k-info .stripe{background:var(--k-info)}.workbtn.k-fail .stripe{background:var(--k-fail)}.workbtn.k-run .stripe{background:var(--k-run)}
.workbtn.selected{border-color:var(--ink);box-shadow:0 0 0 2px var(--ink) inset}
.wb-body{display:flex;flex-direction:column;gap:6px;padding:14px 0 14px 2px;min-width:0}
.wb-title{font-weight:650;font-size:17px;line-height:1.3}
.wb-meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.wb-when{font-size:12px;color:var(--mute)}
.wb-arrow{align-self:center;color:var(--acc);font-weight:650;font-size:13px;padding:6px 14px;margin-right:12px;border:1px solid #D7DFFF;border-radius:999px;background:#EEF2FF}
.workbtn:hover .wb-arrow{background:var(--acc);color:#fff}
.chip{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:650;background:#EEF1F6;color:#4b5565;white-space:nowrap}
.chip.k-firm{background:#DDF5F5;color:#0b7a7a}.chip.k-cond{background:#FFF0D1;color:#9a6400}.chip.k-short{background:#EAE4FF;color:#5a3fd1}
.chip.k-info{background:#DFEBFF;color:#1d62c2}.chip.k-none{background:#EEF1F6;color:#5d6673}.chip.k-fail{background:#FFE1E4;color:#c23a47}.chip.k-run{background:#EAF8D6;color:#4f8a0b}
.chip.conf-high{background:#DDF5F5;color:#0b7a7a}.chip.conf-medium{background:#FFF0D1;color:#9a6400}.chip.conf-low{background:#FFE1E4;color:#c23a47}.chip.neutral{background:#EEF1F6}
.legacy-toggle{margin-top:6px;background:transparent;border:1px dashed var(--line);border-radius:12px;padding:10px;color:var(--mute);cursor:pointer;font:inherit;font-size:13px}
.legacy-toggle:hover{border-color:var(--acc);color:var(--acc)}
.legacy-list{list-style:none;padding:0;margin:4px 0 0;font-size:13px;display:flex;flex-direction:column;gap:4px}
.legacy-list a{color:var(--acc);text-decoration:none;word-break:break-all}
.workdetail{min-width:0}
.wd-head{background:#fff;border:1px solid var(--line);border-left:8px solid var(--k-none);border-radius:14px;padding:16px 18px;margin-bottom:14px}
.wd-head.k-firm{border-left-color:var(--k-firm)}.wd-head.k-cond{border-left-color:var(--k-cond)}.wd-head.k-short{border-left-color:var(--k-short)}
.wd-head.k-info{border-left-color:var(--k-info)}.wd-head.k-fail{border-left-color:var(--k-fail)}.wd-head.k-run{border-left-color:var(--k-run)}
.wd-title{margin:0 0 6px;font-size:21px;line-height:1.25;letter-spacing:-.01em}
.wd-q{margin:0 0 8px;color:var(--mute)}.wd-meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:0}.wd-replay{display:block;white-space:normal;margin:6px 0}
.empty{background:#fff;border:1px dashed var(--line);border-radius:14px;padding:20px;color:var(--mute)}
.work .kpi{border-radius:12px}.work .kpi .v{color:var(--ink)}
@media (prefers-reduced-motion:reduce){.workbtn{transition:none}.workbtn:hover{transform:none}}
/* run page */
header{padding:14px 28px}
main{padding:0 28px 48px;max-width:1240px}
#council-root{padding:0 28px 48px;max-width:1240px}
.run-head{background:#fff;border:1px solid var(--line);border-left:10px solid var(--k-none);border-radius:16px;padding:18px 22px;margin:14px 0 16px}
.run-head.k-firm{border-left-color:var(--k-firm)}.run-head.k-cond{border-left-color:var(--k-cond)}.run-head.k-short{border-left-color:var(--k-short)}
.run-head.k-info{border-left-color:var(--k-info)}.run-head.k-fail{border-left-color:var(--k-fail)}.run-head.k-run{border-left-color:var(--k-run)}
.run-title{font-size:24px;line-height:1.25;letter-spacing:-.01em;margin:0 0 6px;max-width:68ch;overflow-wrap:anywhere}
.run-q{margin:0 0 10px;color:var(--mute);max-width:80ch}
.run-chips{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 10px}
.run-meta{margin:0;font-size:12px;color:var(--mute);overflow-wrap:anywhere}
.run-meta code{font-size:11px}
.verdict{display:grid;grid-template-columns:1fr;background:#fff;border:1px solid var(--line);border-radius:16px;overflow:hidden;margin:10px 0 16px}
.verdict-main{padding:20px 24px;border-left:10px solid var(--k-none)}
.verdict.k-firm .verdict-main{border-left-color:var(--k-firm)}.verdict.k-cond .verdict-main{border-left-color:var(--k-cond)}.verdict.k-short .verdict-main{border-left-color:var(--k-short)}
.verdict.k-info .verdict-main{border-left-color:var(--k-info)}.verdict.k-fail .verdict-main{border-left-color:var(--k-fail)}.verdict.k-run .verdict-main{border-left-color:var(--k-run)}
.verdict-side{padding:12px 24px 20px;background:#F8F9FC;border-top:1px solid var(--line);display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0 28px}
@media (max-width:900px){.verdict-side{grid-template-columns:1fr}}
.verdict h2.verdict-kind{margin:0 0 10px;font-size:14px;display:flex;gap:6px;flex-wrap:wrap}
.verdict h3{margin:14px 0 4px;font-size:13px;color:var(--mute);font-weight:650}
.verdict-title{margin:0;font-size:22px;line-height:1.3;font-weight:700;letter-spacing:-.01em}
.verdict-summary{margin:8px 0 0;font-size:15px;line-height:1.5;color:#2b3345}
.verdict-basis{margin:10px 0 0;font-size:13px;color:var(--mute)}
.verdict-next{margin:0;font-size:15px;line-height:1.5}
.verdict ul{margin:0;padding-left:18px;font-size:14px;line-height:1.45}.verdict li{margin:3px 0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(104px,1fr));gap:8px;margin:0 0 10px}
.stats.signals{grid-template-columns:repeat(auto-fit,minmax(200px,1fr));margin-bottom:18px}
.stat-tile{background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px 12px;display:flex;flex-direction:column;gap:2px;min-height:64px}
.stat-tile .sv{font-size:19px;font-weight:700;line-height:1.1}.stat-tile .sl{font-size:12px;color:var(--mute)}.stat-tile .ss{font-size:11px;color:#8a93a6;line-height:1.3}
.stats.signals .stat-tile{background:#F8F9FC}
h2{font-size:16px;margin:24px 0 8px;letter-spacing:-.005em}
th{background:#F8F9FC;font-weight:650;font-size:12px;color:#3d475a}td{font-size:13.5px}
tbody tr:nth-child(even) td{background:#FBFCFE}
details{border-radius:12px}
.tabs{display:flex;flex-wrap:wrap;gap:4px;border-bottom:2px solid var(--line);margin:16px 0 18px;position:sticky;top:0;background:var(--bg);z-index:2;padding-top:6px}
.tabs button{border:1px solid var(--line);border-bottom:none;background:#eef1f5;color:var(--ink);padding:8px 14px;border-radius:8px 8px 0 0;cursor:pointer;font:inherit;font-size:14px}
.tabs button.active{background:var(--card);font-weight:650;color:var(--acc);box-shadow:0 2px 0 var(--card)}
.tabs button .n{display:inline-block;margin-left:6px;padding:0 7px;border-radius:10px;background:#e2e6ec;font-size:11px;color:var(--mute)}
section.tab{display:none}section.tab.active{display:block}section.tab>h2:first-child{margin-top:6px}
a.md-link{cursor:zoom-in}a.md-link::after{content:' ◧';color:var(--mute);font-size:11px}
.mdmodal{position:fixed;inset:0;background:rgba(20,26,36,.55);display:none;z-index:50;padding:32px 16px;overflow:auto}
.mdmodal.open{display:block}
.mdmodal .box{background:#fff;border-radius:10px;max-width:900px;margin:0 auto;padding:18px 24px;box-shadow:0 12px 40px rgba(0,0,0,.25)}
.mdmodal .bar{display:flex;justify-content:space-between;align-items:center;gap:12px;border-bottom:1px solid var(--line);padding-bottom:8px;margin-bottom:12px}
.mdmodal .bar button{border:1px solid var(--line);background:#eef1f5;border-radius:6px;padding:6px 12px;cursor:pointer;font:inherit;font-size:13px}
.mdmodal .bar a{margin-right:10px;font-size:13px}
.mdmodal .content{max-height:70vh;overflow:auto}
.tabs{border-bottom:none;gap:6px;padding:8px 0}
.tabs button{border:1px solid var(--line);background:#fff;color:var(--ink);padding:8px 16px;border-radius:999px;font-weight:600}
.tabs button.active{background:var(--ink);color:#fff;border-color:var(--ink);box-shadow:none}
.tabs button .n{background:rgba(255,255,255,.25);color:inherit}
.tabs button:not(.active) .n{background:#EEF1F6;color:var(--mute)}
"""

TAB_JS = """
<script>
(function(){
  var tabs=document.querySelectorAll('.tabs button'),secs=document.querySelectorAll('section.tab');
  function show(id){
    var found=false;
    secs.forEach(function(s){var on=('tab-'+id===s.id);s.classList.toggle('active',on);found=found||on;});
    tabs.forEach(function(b){b.classList.toggle('active',b.dataset.tab===id);});
    if(!found&&secs.length){secs[0].classList.add('active');tabs[0].classList.add('active');}
  }
  tabs.forEach(function(b){b.addEventListener('click',function(){history.replaceState(null,'','#'+b.dataset.tab);show(b.dataset.tab);});});
  show((location.hash||'#').slice(1));
  window.addEventListener('hashchange',function(){show(location.hash.slice(1));});
})();
</script>
"""


def tabify(chunks: list[str], layout: list[tuple[str, str, list[str]]]) -> str:
    """Reorganise a flat list of HTML chunks into tabs.

    ``layout`` is ``[(tab_id, tab_label, [h2 prefixes that belong to this tab]), …]``; a chunk starting with
    ``<h2>`` opens the tab whose prefix list matches it, and every following chunk belongs to that tab until the
    next ``<h2>``. Chunks before the first ``<h2>`` go to the first tab. Unmatched headings go to the last tab.
    The active tab is kept in the URL hash, so the page's auto-refresh does not lose it.
    Kept for the server-rendered settings page; run dashboards render client-side now."""
    buckets: dict[str, list[str]] = {tid: [] for tid, _, _ in layout}
    current = layout[0][0]
    for chunk in chunks:
        if chunk.startswith("<h2>"):
            heading = chunk[4:chunk.find("</h2>")] if "</h2>" in chunk else chunk[4:]
            current = next((tid for tid, _, prefixes in layout if any(heading.startswith(p) for p in prefixes)), layout[-1][0])
        buckets[current].append(chunk)
    nav = "<div class='tabs'>" + "".join(
        f"<button type='button' data-tab='{tid}'>{html.escape(label)}{('<span class=' + chr(39) + 'n' + chr(39) + '>' + str(n) + '</span>') if (n := sum(1 for c in buckets[tid] if c.startswith('<h2>'))) > 1 else ''}</button>"
        for tid, label, _ in layout if buckets[tid]) + "</div>"
    sections = "".join(f"<section class='tab' id='tab-{tid}'>" + "\n".join(buckets[tid]) + "</section>" for tid, _, _ in layout if buckets[tid])
    return nav + sections + TAB_JS


def _bundle_text(name: str) -> str:
    """Built frontend asset (Vite output in ``static/``), inlined so pages stay self-contained."""
    return (Path(__file__).parent / "static" / name).read_text()


def _theme_init_js() -> str:
    return ("<script>try{var t=localStorage.getItem('council-theme');"
            "if(t==='dark'||(!t&&window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches))"
            "document.documentElement.classList.add('dark')}catch(e){}</script>")


def _e(x: Any) -> str:
    return html.escape("" if x is None else str(x))


def _fmt_num(x: Optional[float], nd: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def _badge(text: str, cls: str = "") -> str:
    return f'<span class="badge {cls}">{_e(text)}</span>'


def _state_class(state: str) -> str:
    return {"COMPLETE": "ok", "FAILED": "bad", "CANCELLED": "warn"}.get(state, "")


def _confidence_class(level: Optional[str]) -> str:
    return {"high": "ok", "medium": "warn", "low": "bad"}.get(level or "", "")


def md_to_html(md: str) -> str:
    """Small Markdown renderer for the controller-written report (headings, bullets, tables, bold, code)."""
    out: list[str] = []
    in_list = False
    table: list[str] = []

    def flush_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    def flush_table() -> None:
        nonlocal table
        if table:
            rows = [r for r in table if not re.match(r"^\|?\s*:?-{2,}", r)]
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            if cells:
                out.append("<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells[0]) + "</tr>")
                for row in cells[1:]:
                    out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
                out.append("</table>")
            table = []

    def inline(s: str) -> str:
        s = _e(s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        return s

    fence: Optional[list[str]] = None   # lines of an open ``` block
    for line in md.splitlines():
        if line.startswith("```"):
            flush_list()
            flush_table()
            if fence is None:
                fence = []
            else:
                out.append("<pre><code>" + _e("\n".join(fence)) + "</code></pre>")
                fence = None
            continue
        if fence is not None:
            fence.append(line)
            continue
        if line.startswith("|"):
            flush_list()
            table.append(line)
            continue
        flush_table()
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            flush_list()
            out.append(f"<h{len(m.group(1))}>{inline(m.group(2))}</h{len(m.group(1))}>")
        elif line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
        elif line.strip() == "":
            flush_list()
        else:
            flush_list()
            out.append(f"<p>{inline(line)}</p>")
    if fence is not None:
        out.append("<pre><code>" + _e("\n".join(fence)) + "</code></pre>")
    flush_list()
    flush_table()
    return "\n".join(out)


def _events(run_dir: Path) -> list[dict[str, Any]]:
    p = run_dir / "events.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _files(run_dir: Path) -> list[tuple[str, int, str]]:
    rows = []
    for p in sorted(run_dir.rglob("*")):
        if p.is_file() and p.name not in ("index.html", "state.json.tmp") and not p.name.startswith("."):
            st = p.stat()
            rows.append((p.relative_to(run_dir).as_posix(), st.st_size, datetime.fromtimestamp(st.st_mtime).strftime("%H:%M:%S")))
    return rows


def _leaf_items(d: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and v and not key.startswith("policy.weight_overrides") and not key.startswith("routing.opencode.model_fallbacks"):
            items += _leaf_items(v, key)
        else:
            items.append((key, v))
    return items


def req_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if e.get("kind") == "request_issued"]


def who_summary(d: Any) -> str:
    """'chat (claude-sonnet-5-5) ×16 · opencode (claude-agent/haiku) ×7' — providers and models that answered, with call counts."""
    agg: dict[str, int] = {}
    for p in d.participants.values():
        label = f"{p.provider} ({p.model_reported or p.model_requested or (d.chat_model if p.provider == 'chat' else None) or ('identity not declared' if p.provider == 'chat' else '?')})"
        agg[label] = agg.get(label, 0) + p.calls
    return " · ".join(f"{k} ×{v}" for k, v in agg.items()) or "nobody yet"


def title_of(store) -> str:
    brief = store.current_brief()
    if brief is not None and brief.decision_statement:
        return brief.decision_statement
    return store.data.question


MD_EMBED_MAX_FILE = 100_000
MD_EMBED_MAX_TOTAL = 1_000_000


def md_embed_map(run_dir: Path) -> dict[str, str]:
    """Pre-rendered Markdown files (rel path -> HTML) embedded in the dashboard.

    Embedded content makes the modal work offline from ``file://`` too; files over
    the per-file cap or past the total budget are still served raw and rendered
    client-side when the dashboard is served over HTTP."""
    out: dict[str, str] = {}
    total = 0
    for rel, size, _mtime in _files(run_dir):
        if not rel.endswith(".md") or size > MD_EMBED_MAX_FILE:
            continue
        try:
            rendered = md_to_html((run_dir / rel).read_text())
        except (OSError, UnicodeDecodeError):
            continue
        if total + len(rendered) > MD_EMBED_MAX_TOTAL:
            break
        out[rel] = rendered
        total += len(rendered)
    return out


CTX_KEYS = ['engine', 'store', 'd', 'run_dir', 'cfg', 'terminal', 'dec', 'inc', 'budget', 'events', 'title', 'stop', 'conf_level', 'promotions', 'rejected', 'open_ch', 'critical_open', 'details', 'replay']


def build_context(engine: "Engine") -> dict[str, Any]:
    """Everything the dashboard state needs, computed once."""
    store = engine.store
    d = store.data
    run_dir = store.run_dir
    cfg = engine.cfg
    terminal = d.state in TERMINAL_STATES
    dec = d.decision
    inc = d.option_versions.get(d.incumbent_version_id) if d.incumbent_version_id else None
    # a finished run must show the elapsed time at completion, not the time since it started
    budget = dec.budget if (dec is not None and d.state in TERMINAL_STATES) else d.budget.snapshot(cfg.limits)
    events = _events(run_dir)
    title = title_of(store)
    stop = (d.stop_reason.value if d.stop_reason else None) or (d.pending_stop_reason.value if d.pending_stop_reason else None)
    conf_level = dec.confidence.level.value if dec else None
    promotions = sum(1 for e in events if e.get("kind") == "incumbent_changed")
    rejected = sum(1 for e in events if e.get("kind") == "response_rejected")
    open_ch = [c for c in d.challenges.values() if c.status.value in ("open", "unresolved_final")]
    critical_open = sum(1 for c in open_ch if c.severity.value == "critical")
    from .report import answer_details, backfill_participant_usage, fixture_replay_note
    backfill_participant_usage(store)
    details = answer_details(store)
    replay = fixture_replay_note(d)

    return {k: v for k, v in locals().items() if k in CTX_KEYS}


def _kpis(ctx: dict[str, Any]) -> list[dict[str, str]]:
    d, budget, dec, conf_level = ctx["d"], ctx["budget"], ctx["dec"], ctx["conf_level"]
    kpis = [
        {"l": "Model calls", "v": f"{budget.model_calls_used}/{budget.model_calls_limit}", "s": "counted"},
        {"l": "Tokens", "v": f"{budget.tokens_measured + budget.tokens_estimated:,}",
         "s": f"measured {budget.tokens_measured:,} · est. {budget.tokens_estimated:,} · limit {budget.tokens_limit:,}"},
        {"l": "Elapsed", "v": f"{budget.elapsed_seconds:,.0f} s", "s": f"limit {budget.elapsed_limit:,.0f} s"},
        {"l": "Cost", "v": "n/a" if budget.cost_usd is None else f"${budget.cost_usd:.2f}", "s": budget.cost_status},
        {"l": "Rounds", "v": str(d.round), "s": f"stable streak {d.stable_streak}"},
        {"l": "Options", "v": str(len([v for v in d.option_versions.values() if v.status.value in ('active', 'reinstated')])),
         "s": f"{len(d.option_versions)} versions"},
        {"l": "Promotions", "v": str(ctx["promotions"]), "s": "incumbent changes"},
        {"l": "Open objections", "v": str(len(ctx["open_ch"])), "s": f"{ctx['critical_open']} critical"},
        {"l": "Rejected replies", "v": str(ctx["rejected"]), "s": "validated before commit"},
    ]
    if dec:
        kpis += [
            {"l": "Confidence", "v": conf_level or "n/a", "s": dec.confidence.basis[:90]},
            {"l": "Evidence quality", "v": _fmt_num(dec.signals.evidence_quality), "s": "share verified/user-supplied"},
            {"l": "Judge agreement", "v": _fmt_num(dec.signals.judge_agreement), "s": dec.signals.judge_agreement_note[:60] or "across judges"},
            {"l": "Ranking robustness", "v": _fmt_num(dec.signals.ranking_robustness), "s": f"{len(dec.signals.ranking_flips)} flip(s)"},
        ]
    return kpis


def _followup(ctx: dict[str, Any]) -> str:
    """The copy-to-chat follow-up prompt, once a decision exists."""
    dec = ctx["dec"]
    if dec is None or ctx["d"].state not in TERMINAL_STATES:
        return ""
    from .report import followup_prompt
    try:
        return followup_prompt(ctx["engine"], dec)
    except Exception:  # noqa: BLE001 - a dashboard must never fail on an optional block
        return ""


def _outcome(ctx: dict[str, Any]) -> Optional[dict[str, Any]]:
    d, dec, inc, stop, conf_level = ctx["d"], ctx["dec"], ctx["inc"], ctx["stop"], ctx["conf_level"]
    if not dec:
        pending = "No decision yet. "
        if d.pending_request:
            pending += (f"Waiting for {d.pending_request.request_id} "
                        f"({d.pending_request.kind}, role {d.pending_request.role}, provider {d.pending_request.provider}).")
        else:
            pending += "Controller is advancing."
        return {"pending": pending + (f" Current incumbent: {inc.title}" if inc else "")}
    rec = d.option_versions.get(dec.recommended_version_id) if dec.recommended_version_id else None
    return {
        "kind": dec.kind.value,
        "recTitle": rec.title if rec else "none", "recSummary": rec.summary if rec else "",
        "confLevel": conf_level, "confCls": _confidence_class(conf_level), "confBasis": dec.confidence.basis,
        "stop": stop, "next": dec.next_action,
        "alts": "; ".join(d.option_versions[a].title for a in dec.alternatives if a in d.option_versions),
        "reversal": dec.reversal_conditions, "unfinished": dec.unfinished_checks,
    }


def _rounds(ctx: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], list[dict[str, str]]]:
    from .report import chat_label  # noqa: F401
    d, events = ctx["d"], ctx["events"]
    taken = {"promoted": "challenger promoted to incumbent", "retained_tie": "incumbent kept (tie within materiality)",
             "retained_loss": "incumbent kept (challenger lost)", "inconclusive": "inconclusive comparison, incumbent kept",
             "baseline": "round-zero baseline set", "rejected_regression": "revision rejected, parent kept"}
    rows = []
    for rs in d.round_summaries.values():
        inc_v = d.option_versions.get(rs.incumbent_version_id) if rs.incumbent_version_id else None
        score = next((s for vid, s in rs.ranking if vid == rs.incumbent_version_id), None)
        outcome = rs.promotion_outcome.value
        rows.append({
            "round": rs.round, "incumbent": inc_v.title if inc_v else "—", "outcome": outcome,
            "outcomeCls": "ok" if outcome == "promoted" else "",
            "taken": taken.get(outcome, outcome),
            "score": _fmt_num(score),
            "deltaPrior": f"{rs.delta_vs_prior_incumbent.value:+.2f}" if rs.delta_vs_prior_incumbent.comparable and rs.delta_vs_prior_incumbent.value is not None else "n/a",
            "net0": f"{rs.net_vs_round0.value:+.2f}" if rs.net_vs_round0.comparable and rs.net_vs_round0.value is not None else "n/a",
            "comparable": rs.comparable, "openCritical": rs.open_critical_count,
            "stableStreak": rs.stable_streak, "calls": rs.budget.model_calls_used, "note": rs.note,
        })
    history = [f"r{h.get('round')} {(d.option_versions[h['version_id']].title if h.get('version_id') in d.option_versions else h.get('version_id'))} ({h.get('outcome')})" for h in d.incumbent_history]
    notable = [{"time": (e.get("created_at", "") or "")[11:19], "round": e.get("round"), "kind": e.get("kind"),
                "detail": json.dumps(e.get("payload", {}))[:300]}
               for e in events if e.get("kind") in ("incumbent_changed", "stop_decided", "reopened", "rescore_required",
                                                    "route_fallback", "route_substitution", "policy_weights_overridden", "budget_warning", "request_failed")]
    return rows, history, notable


def _objections(ctx: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    d = ctx["d"]
    out: dict[str, list[dict[str, str]]] = {"challenges": [], "leader": [], "dissents": []}
    for c in d.challenges.values():
        tgt = d.option_versions[c.target_ref].title if c.target_ref in d.option_versions else c.target_ref
        cls = "bad" if c.status.value in ("open", "unresolved_final") and c.severity.value == "critical" else ("warn" if c.status.value in ("open", "unresolved_final") else "ok")
        out["challenges"].append({"id": c.id, "status": c.status.value, "statusCls": cls, "severity": c.severity.value,
                                  "could": c.could_change.value, "target": tgt, "mechanism": c.mechanism,
                                  "resolution": c.resolution_condition})
    for lc in d.leader_challenges.values():
        out["leader"].append({"id": lc.id, "status": lc.status.value,
                              "statusCls": "warn" if lc.status.value != "resolved" else "ok",
                              "could": "action" if lc.could_alter_outcome else "none",
                              "target": d.option_versions[lc.leader_version_id].title if lc.leader_version_id in d.option_versions else "",
                              "mechanism": lc.losing_scenario, "resolution": lc.distinguishing_evidence})
    for ds in d.dissents.values():
        tgt = d.option_versions[ds.against_ref].title if ds.against_ref in d.option_versions else ds.against_ref
        out["dissents"].append({"id": ds.id, "target": tgt, "position": ds.position, "reason": ds.reason, "whatYouLose": ds.what_you_lose})
    return out


def _who(ctx: dict[str, Any]) -> tuple[list[dict[str, str]], str, str]:
    from .report import chat_label
    d = ctx["d"]
    rows = []
    for p in d.participants.values():
        model_txt = p.model_reported or p.model_requested or (chat_label(d) if p.provider == "chat" else "?")
        avg = f"{p.latency_seconds / p.calls:.1f} s" if p.calls and p.latency_seconds else "n/a"
        rows.append({"id": p.id, "role": p.role.value, "lens": p.lens_id or "", "provider": p.provider,
                     "provCls": "ok" if p.provider == "chat" else ("warn" if p.provider == "opencode" else "bad"),
                     "model": model_txt, "isolation": p.isolation.value, "calls": p.calls, "tokens": p.tokens,
                     "avg": avg, "effort": p.effort or ""})
    note = ("chat = the model of the conversation you type in: every role is played by that one model, so every row "
            "says chat; opencode = an isolated OpenCode session with the model shown. Fixture = recorded test transcript.")
    return rows, note, chat_label(d)


def _reasoning(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    from .trail import reasoning_trail
    store = ctx["store"]
    steps = []
    for s in reasoning_trail(store):
        if s["participant"] == "controller":
            by = '<span class="badge">controller</span>'
        else:
            cls = "ok" if s["provider"] == "chat" else ("warn" if s["provider"] == "opencode" else "bad")
            by = f'<span class="badge {cls}">{_e(s["role"])}</span> {_e(s["who"])}'
        steps.append({"round": s["round"], "phase": s["phase"], "kind": s["kind"], "byHtml": by,
                      "what": s["what"], "ids": ", ".join(s["ids"][:6]) + (" …" if len(s["ids"]) > 6 else "")})
    return steps


def _orchestration(ctx: dict[str, Any]) -> list[dict[str, str]]:
    from .report import chat_label  # noqa: F401
    d, details = ctx["d"], ctx["details"]
    rows = []
    for i, e in enumerate(req_events(ctx["events"])):
        p = e.get("payload") or {}
        rid = p.get("request_id", "")
        ap = details.get(rid) or {}
        prov = ap.get("provider") or p.get("provider") or ""
        model = ap.get("model") or (chat_label(d) if prov == "chat" else "")
        who = f"{prov} · {model}".strip(" ·")
        td = ap.get("tokens_detail") or {}
        toks = (f"{td.get('input', 0):,}/{td.get('output', 0):,}/{td.get('reasoning', 0):,}" + (f" +cache {td.get('cache_read', 0) + td.get('cache_write', 0):,}" if td else "")) if td else (f"≈{ap.get('tokens'):,} est." if ap.get("tokens") is not None else "")
        lat = f"{ap.get('latency_seconds'):.1f} s" if ap.get("latency_seconds") is not None else ""
        oc = ap.get("outcome")
        res = ("committed" if oc == "response_committed" else ("rejected: " + str(ap.get("error", ""))[:120] if oc == "response_rejected" else ("failed: " + str(ap.get("error", ""))[:120] if oc == "request_failed" else "pending")))
        lens = d.participants.get(p.get("participant", ""))
        lens_txt = f" / {lens.lens_id}" if lens is not None and lens.lens_id else ""
        cls = "bad" if res.startswith("failed") else ("warn" if res.startswith("rejected") else ("ok" if res == "committed" else ""))
        rows.append({"time": (e.get("created_at", "") or "")[11:19], "round": e.get("round"), "phase": e.get("state_after"),
                     "roleLens": f"{p.get('role')}{lens_txt}", "participant": p.get("participant"), "who": who + ((" · " + ap.get("effort")) if ap.get("effort") else ""),
                     "toks": toks, "lat": lat, "res": res.split(":")[0], "resCls": cls,
                     "resDetail": (" " + res.split(":", 1)[1]) if ":" in res else ""})
    return rows


def _log(ctx: dict[str, Any]) -> list[dict[str, str]]:
    d, run_dir, events = ctx["d"], ctx["run_dir"], ctx["events"]
    outcome_by_req: dict[str, list[str]] = {}
    for e in events:
        k = e.get("kind")
        rid = (e.get("payload") or {}).get("request_id")
        if rid and k in ("response_committed", "response_rejected", "response_duplicate", "request_failed", "route_fallback", "route_substitution"):
            txt = k + ((": " + str((e.get("payload") or {}).get("error", ""))[:160]) if k in ("response_rejected", "request_failed", "route_fallback") else "")
            outcome_by_req.setdefault(rid, []).append(txt)
    rows = []
    for e in req_events(events):
        p = e.get("payload") or {}
        rid = p.get("request_id", "")
        outs = outcome_by_req.get(rid, [])
        cls = "bad" if any(o.startswith("request_failed") for o in outs) else ("warn" if any(o.startswith("response_rejected") or o.startswith("route_fallback") for o in outs) else ("ok" if outs else ""))
        first = outs[-1] if outs else "pending"
        rows.append({"time": (e.get("created_at", "") or "")[11:19], "id": rid, "round": e.get("round"), "kind": p.get("kind"),
                     "role": p.get("role"), "participant": p.get("participant"), "attempt": p.get("attempt"), "provider": p.get("provider"),
                     "outcome": first.split(":")[0], "outcomeCls": cls,
                     "outcomeDetail": ("; ".join(outs) if len(outs) > 1 else (":" + outs[0].split(":", 1)[1] if outs and ":" in outs[0] else "")),
                     "filesHtml": ("<a href='requests/" + rid + ".json'>request</a>" if (run_dir / "requests" / f"{rid}.json").exists() else "")
                     + (" · <a href='responses/" + rid + ".json'>response</a>" if (run_dir / "responses" / f"{rid}.json").exists() else "")})
    return rows


def _discussion(ctx: dict[str, Any], *, with_html: bool) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]], str]:
    from .report import chat_label
    d, run_dir = ctx["d"], ctx["run_dir"]
    items = []
    for e in d.discussion:
        file_html = ""
        if with_html and e.get("file") and (run_dir / e["file"]).exists():
            text = (run_dir / e["file"]).read_text().split("<details>", 1)[0]
            file_html = md_to_html(text)
        items.append({"n": e["n"], "round": e["round"], "phase": e["phase"], "roleLens": e["role"] + ((" / " + e["lens"]) if e.get("lens") else ""),
                      "by": f"{e.get('provider')} · {e.get('model') or (chat_label(d) if e.get('provider') == 'chat' else '')}",
                      "outcome": e.get("outcome"), "error": e.get("error") or "", "summary": e.get("summary"),
                      "file": e.get("file") or "", "fileName": (e.get("file") or "").split("/")[-1], "fileHtml": file_html})
    docs = [{"evid": doc["evidence_id"], "name": doc["name"], "chars": doc["chars"], "path": doc["path"],
             "copy": doc["copy"], "isMd": doc["copy"].endswith(".md")} for doc in d.documents]
    policy_note = ""
    if d.discussion:
        policy_note = (f"Each request carries discussion_so_far: the full text of the current round's contributions "
                       f"and the controller's digest of earlier rounds (policy {(d.effective_config.get('discussion') or {}).get('include', 'current_round_and_summaries')}, "
                       f"cap {(d.effective_config.get('discussion') or {}).get('max_chars', 30000)} chars). "
                       f"Full transcript: discussion.md.")
    return items, policy_note, docs, "; ".join(d.document_notes)


def _settings(ctx: dict[str, Any]) -> list[dict[str, str]]:
    from .settings import describe as _describe
    d = ctx["d"]
    rows = []
    for key, val in _leaf_items(d.effective_config):
        layer = d.provenance.get(key, "defaults")
        if isinstance(val, dict):
            layer = next((v for k, v in d.provenance.items() if k.startswith(key + ".")), layer)
        cls = {"override": "warn", "saved": "ok"}.get(layer.split(":")[0], "")
        rows.append({"key": key, "value": json.dumps(val), "layer": layer, "layerCls": cls, "explanation": _describe(key)})
    return rows


def _file_rows(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    from .report import chat_label  # noqa: F401
    d, run_dir, details = ctx["d"], ctx["run_dir"], ctx["details"]
    fixed = {
        "discussion.md": ("controller (Python, no model)", "every step", "the whole discussion in order: every model contribution rendered as text with its raw JSON"),
        "inputs/INDEX.md": ("controller (Python, no model)", "start", "index of the user's input documents and what was skipped"),
        "report.md": ("controller (Python, no model)", "final", "human-readable decision record built from the committed state"),
        "decision.json": ("controller (Python, no model)", "final", "machine-readable decision record (same content, for tools)"),
        "decision.prev.json": ("controller (Python, no model)", "final", "the record as it was before the last `council rereport`"),
        "state.json": ("controller (Python, no model)", "every step", "full committed state: brief, policy, options, claims, evidence, challenges, judgements, budget (resume point)"),
        "events.jsonl": ("controller (Python, no model)", "every step", "append-only log: requests issued, replies committed/rejected, phase changes, incumbent changes, stops"),
        "TITLE.txt": ("controller (Python, no model)", "after framing", "the framed decision statement taken from the framer's reply"),
        "index.html": ("controller (Python, no model)", "every step", "this dashboard"),
    }
    kind_why = {"frame": "turn the question into a decision brief", "policy": "register gates, criteria, weights and scenarios before any ranking",
                "baseline": "produce the status quo and the most direct answer", "generate": "propose an option through one reasoning lens",
                "review": "challenge the options (typed objections, dissent, shared blind spots)", "verify": "check evidence behind a challenge",
                "respond": "owner answers a challenge: rebut, concede, revise, withdraw or reinstate", "judge": "score one option version on every gate and criterion",
                "compare": "pairwise tie-break between incumbent and challenger (swapped order)", "challenge": "sceptical pass against the leader",
                "challenge_reply": "leader's owner answers the sceptical pass"}
    out = []
    for rel, size, mtime in _files(run_dir):
        if rel in fixed:
            by, when, why = fixed[rel]
        elif rel.startswith("requests/") or rel.startswith("responses/"):
            rid = rel.split("/", 1)[1].rsplit(".", 1)[0]
            det = details.get(rid) or {}
            req = next((e for e in req_events(ctx["events"]) if (e.get("payload") or {}).get("request_id") == rid), None)
            rp = (req or {}).get("payload") or {}
            role, kind, participant = rp.get("role") or det.get("role") or "", rp.get("kind") or "", rp.get("participant") or det.get("participant") or ""
            part = d.participants.get(participant)
            lens = f" through lens {part.lens_id}" if part is not None and part.lens_id and kind in ("generate", "respond", "baseline") else ""
            when = f"round {(req or {}).get('round', det.get('round'))} · {(req or {}).get('state_after', det.get('phase'))}"
            attempt = rp.get("attempt") or 1
            if rel.startswith("requests/"):
                by = "controller (Python, no model)"
                why = f"asks the {role} ({participant}) to {kind_why.get(kind, kind)}{lens}" + (f"; retry attempt {attempt} after a rejected reply" if attempt > 1 else "") + "; contains instructions, data payload and response schema"
            else:
                prov = det.get("provider") or rp.get("provider") or ""
                model = det.get("model") or ""
                by = f"{prov} · {model}".strip(" ·") + (f" as {role}" if role else "")
                oc = det.get("outcome")
                why = f"raw reply to {rid}: {kind_why.get(kind, kind)}{lens}" + ("; validated and committed" if oc == "response_committed" else (f"; rejected: {str(det.get('error', ''))[:100]}" if oc == "response_rejected" else (f"; failed: {str(det.get('error', ''))[:100]}" if oc == "request_failed" else "")))
                if det.get("latency_seconds") is not None:
                    why += f"; {det['latency_seconds']:.0f} s" + (f", ≈{det.get('tokens'):,} tokens est." if det.get("tokens_kind") == "estimated" and det.get("tokens") else "")
        elif rel.startswith("discussion/"):
            m = re.match(r"discussion/(\d+)_r(\d+)_([A-Z_]+)_([a-z_]+?)(?:_([a-z_]+))?\.md$", rel)
            n = int(m.group(1)) if m else 0
            e = next((x for x in d.discussion if x.get("n") == n), {})
            from .report import chat_label as _chat_label
            prov = e.get("provider") or ""
            by = f"{prov} · {e.get('model') or (_chat_label(d) if prov == 'chat' else '')}".strip(" ·") + (f" as {e.get('role')}" if e.get("role") else "")
            when = f"round {e.get('round', m.group(2) if m else '?')} · {e.get('phase', m.group(3) if m else '')}"
            why = f"contribution D{n} ({e.get('kind', '')}{(' through lens ' + e['lens']) if e.get('lens') else ''}), {e.get('outcome', '')}: {str(e.get('summary', ''))[:140]}"
        elif rel.startswith("inputs/"):
            doc = next((x for x in d.documents if x.get("copy") == rel), None)
            by, when, why = ("controller (Python, no model)", "start", f"input document, evidence {doc['evidence_id']}" if doc else "input document")
        else:
            by, when, why = "", "", ""
        out.append({"rel": rel, "size": size, "mtime": mtime, "by": by, "when": when, "why": why, "isMd": rel.endswith(".md")})
    return out


SUMMARY_KEYS = ("runId", "createdAt", "state", "stateCls", "round", "preset", "stop", "title", "question",
                "folder", "answeredBy", "replay", "terminal", "kpis", "outcome", "rounds", "incumbentHistory",
                "events", "objections", "who", "chatNote", "reasoning")


def dashboard_state(ctx: dict[str, Any], *, served: bool = False, full: bool = True) -> dict[str, Any]:
    """Plain JSON-serializable dashboard data for the React app (``app.js``).

    With ``full=False`` only the home-page subset is built (no discussion texts,
    files, Markdown map or report HTML)."""
    engine, store, d, run_dir, terminal, dec = ctx["engine"], ctx["store"], ctx["d"], ctx["run_dir"], ctx["terminal"], ctx["dec"]
    rounds, history, notable = _rounds(ctx)
    who_rows, chat_note, chat_label_txt = _who(ctx)
    discussion, policy_note, documents, doc_notes = _discussion(ctx, with_html=full)
    rep = run_dir / "report.md"
    state: dict[str, Any] = {
        "runId": d.run_id, "createdAt": d.created_at, "state": d.state.value, "stateCls": _state_class(d.state.value),
        "round": d.round, "preset": d.preset or "standard", "stop": ctx["stop"], "title": ctx["title"],
        "question": d.question, "folder": str(run_dir), "answeredBy": who_summary(d),
        "replay": ctx["replay"], "terminal": terminal, "served": served,
        "kpis": _kpis(ctx), "outcome": _outcome(ctx), "rounds": rounds,
        "incumbentHistory": history, "events": notable, "objections": _objections(ctx),
        "who": who_rows, "chatNote": chat_note, "chatLabel": chat_label_txt, "reasoning": _reasoning(ctx),
        "orchestration": _orchestration(ctx) if full else [],
        "discussion": discussion, "discussionPolicyNote": policy_note,
        "documents": documents if full else [], "docNotes": doc_notes if full else "",
        "settings": _settings(ctx) if full else [], "files": _file_rows(ctx) if full else [],
        "log": _log(ctx) if full else [],
        "mdMap": md_embed_map(run_dir) if full else {},
        "reportHtml": md_to_html(rep.read_text()) if full and rep.exists() else "",
        "followUp": _followup(ctx) if full else "",
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "refreshSeconds": 0 if terminal else REFRESH_SECONDS,
    }
    if not full:
        state = {k: state[k] for k in SUMMARY_KEYS if k in state}
    return state


def _state_script(element_id: str, state: dict[str, Any]) -> str:
    payload = json.dumps(state, ensure_ascii=True).replace("</", "<\\/").replace("<!--", "<\\!--")
    return f'<script type="application/json" id="{element_id}">' + payload + "</script>"


def render_dashboard(engine: "Engine", *, served: bool = False) -> str:
    ctx = build_context(engine)
    ctx["served"] = served
    d = ctx["d"]
    state = dashboard_state(ctx, served=served, full=True)
    title = ctx["title"]
    nav = (("<nav class='mb-2 flex gap-2'>"
            "<a href='../../' class='inline-flex h-9 items-center gap-1 rounded-md border border-input bg-background px-3 text-sm font-medium shadow-sm hover:bg-accent hover:text-accent-foreground'>&larr; All works</a>"
            "<a href='../../settings' class='inline-flex h-9 items-center gap-1 rounded-md border border-input bg-background px-3 text-sm font-medium shadow-sm hover:bg-accent hover:text-accent-foreground'>Settings</a>"
            "</nav>") if served else "")
    refresh = "" if ctx["terminal"] else f"<meta http-equiv='refresh' content='{REFRESH_SECONDS}'>"
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>Strategy Tribunal — {_e(title)[:80]}</title>"
        f"{refresh}{_theme_init_js()}<style>{_bundle_text('dashboard.css')}</style></head><body>"
        "<a class='skip-link' href='#council-main'>Skip to content</a>"
        f"<header class='border-b bg-background px-7 py-4'>{nav}</header>"
        '<main id="council-main" class="mx-auto max-w-7xl px-7 pb-12"><div id="council-root"></div></main>'
        f"<noscript><p style='padding:20px'>This dashboard is a React app and needs JavaScript. The same decision is in <a href='report.md'>report.md</a>.</p></noscript>"
        + _state_script("council-state", state)
        + f"<script>{_bundle_text('dashboard.js')}</script>"
        + "</body></html>"
    )


def home_state(root, rows: list[dict[str, Any]], *, limit: int = 25) -> dict[str, Any]:
    """Home-page data: summary states per work plus the overview table."""
    from .cli import load_engine
    works = []
    for r in [x for x in rows if not x["legacy"]][:limit]:
        try:
            eng, _ = load_engine(root, r["run_id"])
            summary = dashboard_state(build_context(eng), served=True, full=False)
        except Exception as exc:  # noqa: BLE001 - one broken folder must not hide the others
            summary = None
            summary_error = f"could not load {r['run_id']}: {exc}"
        else:
            summary_error = ""
        works.append({"runId": r["run_id"], "href": f"/runs/{r['run_id']}/", "label": r["label"],
                      "stateMark": r["stateMark"], "summary": summary, "summaryError": summary_error})
    cols = ["created", "title", "state", "outcome", "confidence", "stop", "rounds", "calls", "tokens",
            "open objections", "promotions", "preset", "folder"]
    table_rows = []
    for r in rows:
        cls = {"COMPLETE": "ok", "FAILED": "bad", "CANCELLED": "warn"}.get(r["state"] or "", "")
        ccls = {"high": "ok", "medium": "warn", "low": "bad"}.get(r["confidence"] or "", "")
        table_rows.append([
            r["when"], {"html": f"<a href='/runs/{r['run_id']}/'>{_e((r['title'] or '')[:110])}</a>"},
            {"html": f"<span class=\"badge {cls}\">{_e(r['state'])}</span>"}, r["kind"] or "",
            ({"html": f"<span class=\"badge {ccls}\">{_e(r['confidence'])}</span>"} if r["confidence"] else ""),
            r["stop_reason"] or "", r["round"], r["calls"], f"{r['tokens']:,}",
            r["open_objections"], r["promotions"], r["preset"] or "standard",
            {"html": f"<span class=\"small muted\">{_e(r['run_id'])}{' (legacy)' if r['legacy'] else ''}</span>"}])
    kinds: dict[str, int] = {}
    for r in rows:
        kinds[r["kind"] or "running"] = kinds.get(r["kind"] or "running", 0) + 1
    kpis = [
        {"l": "Runs", "v": str(len(rows)), "s": ""},
        {"l": "Completed", "v": str(sum(1 for r in rows if r["state"] == "COMPLETE")), "s": ""},
        {"l": "Running", "v": str(sum(1 for r in rows if r["state"] not in ("COMPLETE", "FAILED", "CANCELLED"))), "s": ""},
        {"l": "Firm", "v": str(kinds.get("firm", 0)), "s": ""},
        {"l": "Conditional", "v": str(kinds.get("conditional", 0)), "s": ""},
        {"l": "Shortlist", "v": str(kinds.get("shortlist", 0)), "s": ""},
        {"l": "Info requests", "v": str(kinds.get("information_request", 0)), "s": ""},
        {"l": "Total calls", "v": f"{sum(r['calls'] or 0 for r in rows):,}", "s": ""},
    ]
    return {"works": works, "cols": cols, "tableRows": table_rows, "rows": rows,
            "kpis": kpis, "legacyCount": sum(1 for r in rows if r["legacy"])}


def write_dashboard(engine: "Engine", *, served: bool = False) -> Optional[Path]:
    """Write ``index.html`` (and ``TITLE.txt`` once a brief exists) into the run folder. Never raises into the controller."""
    try:
        if not engine.cfg.storage.dashboard:
            return None
        run_dir = engine.store.run_dir
        brief = engine.store.current_brief()
        if brief is not None and brief.decision_statement:
            tp = run_dir / "TITLE.txt"
            if not tp.exists() or tp.read_text() != brief.decision_statement + "\n":
                tp.write_text(brief.decision_statement + "\n")
        out = run_dir / "index.html"
        tmp = run_dir / ".index.html.tmp"
        tmp.write_text(render_dashboard(engine, served=served))
        tmp.replace(out)
        return out
    except Exception as exc:  # noqa: BLE001 - the dashboard must never break a run
        try:
            (engine.store.run_dir / ".dashboard_error.txt").write_text(f"{type(exc).__name__}: {exc}\n")
        except Exception:  # noqa: BLE001
            pass
        return None
