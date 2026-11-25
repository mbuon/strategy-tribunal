import * as React from 'react'
import { ThemeToggle, useTheme } from './theme'
import { Button } from './ui/button'
import DeleteWork from './DeleteWork'
import { TONE, CONF, toneOf, toneKey, localWhen } from '../lib/kind'

function Chip({ cls, children }) {
  return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${cls}`}>{children}</span>
}

function WorkButton({ work, index }) {
  const s = work.summary || {}
  const tone = toneOf(work.summary)
  const o = s.outcome && !s.outcome.pending ? s.outcome : null
  const rec = o && o.recTitle && o.recTitle !== 'none' ? o.recTitle : ''
  const calls = (s.kpis || []).find((k) => k.l === 'Model calls')
  const title = s.title || (work.label || '').split(' · ').slice(1).join(' · ') || work.runId
  return (
    <a
      href={work.href}
      id={`workbtn-${index}`}
      className="group grid min-w-0 flex-1 grid-cols-[10px_1fr_auto] items-stretch overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition hover:-translate-y-px hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none motion-reduce:hover:translate-y-0"
    >
      <span className={tone.stripe} aria-hidden="true" />
      <span className="flex min-w-0 flex-col gap-1.5 py-4 pl-3 pr-3">
        <span className="text-[17px] font-semibold leading-snug tracking-tight">{title}</span>
        {work.summaryError ? <span className="text-sm text-fail-ink dark:text-fail">{work.summaryError}</span> : null}
        {rec ? <span className="text-sm text-foreground/80">{rec}</span> : null}
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <Chip cls={tone.chip}>{tone.label}</Chip>
          {o && o.confLevel ? <Chip cls={CONF[o.confLevel] || 'bg-muted'}>confidence {o.confLevel}</Chip> : null}
          {s.stop ? <Chip cls="bg-muted text-muted-foreground">stopped: {s.stop}</Chip> : null}
          <span>{localWhen(s.createdAt) || (work.label || '').split(' · ')[0]}</span>
          {s.preset ? <span>{s.preset}</span> : null}
          {s.round !== undefined ? <span>{s.round} round{s.round === 1 ? '' : 's'}</span> : null}
          {calls ? <span>{calls.v} calls</span> : null}
          {s.answeredBy ? <span className="truncate">{s.answeredBy}</span> : null}
        </span>
      </span>
      <span className="mr-3 self-center rounded-full border border-primary/30 bg-primary/10 px-3.5 py-1.5 text-xs font-semibold text-primary transition group-hover:bg-primary group-hover:text-primary-foreground">
        Open
      </span>
    </a>
  )
}

function StatPill({ cls, n, label }) {
  return (
    <span className={`inline-flex items-baseline gap-1.5 rounded-full border bg-card px-3.5 py-1.5 text-sm ${cls || 'text-foreground'}`}>
      <strong className="text-base font-bold">{n}</strong>
      <span>{label}</span>
    </span>
  )
}

export default function HomeDashboard({ state: st }) {
  const [dark, toggle] = useTheme()
  const [showLegacy, setShowLegacy] = React.useState(false)
  const [removed, setRemoved] = React.useState([])
  const [deleteError, setDeleteError] = React.useState(null)
  const works = (st.works || []).filter((w) => !removed.includes(w.runId))
  const legacy = (st.rows || []).filter((r) => r.legacy && !removed.includes(r.run_id))
  const counts = {}
  works.forEach((w) => { const k = toneKey(w.summary); counts[k] = (counts[k] || 0) + 1 })
  const onDeleted = (id) => { setRemoved((rs) => [...rs, id]); setDeleteError(null) }
  const onDeleteError = (msg) => setDeleteError(msg)

  function onListKey(ev) {
    if (ev.key !== 'ArrowDown' && ev.key !== 'ArrowUp') return
    const items = Array.from(ev.currentTarget.querySelectorAll('a[id^="workbtn-"]'))
    const idx = items.indexOf(document.activeElement)
    if (idx < 0 || !items.length) return
    ev.preventDefault()
    items[(ev.key === 'ArrowDown' ? idx + 1 : idx - 1 + items.length) % items.length].focus()
  }

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2" aria-label="Summary">
          <StatPill n={works.length} label={works.length === 1 ? 'work' : 'works'} />
          {Object.keys(counts).map((k) => <StatPill key={k} cls={TONE[k].stat} n={counts[k]} label={TONE[k].label} />)}
          {legacy.length ? <StatPill cls="text-muted-foreground" n={legacy.length} label="older runs" /> : null}
        </div>
        <ThemeToggle dark={dark} onToggle={toggle} />
      </div>
      {deleteError ? (
        <p className="mb-3 rounded-xl border border-destructive/50 bg-destructive/10 px-4 py-2 text-sm text-destructive" role="alert">{deleteError}</p>
      ) : null}
      <nav className="flex flex-col gap-3" aria-label="Works" onKeyDown={onListKey}>
        {works.length ? null : (
          <p className="rounded-2xl border border-dashed p-6 text-sm text-muted-foreground">
            No work yet. Start one in Claude Code with <code>/council your question</code>.
          </p>
        )}
        {works.map((w, i) => (
          <div key={w.runId} className="flex items-stretch gap-2">
            <WorkButton work={w} index={i} />
            <div className="flex items-center">
              <DeleteWork runId={w.runId} title={(w.summary && w.summary.title) || w.runId} onDeleted={onDeleted} onError={onDeleteError} />
            </div>
          </div>
        ))}
        {legacy.length ? (
          <Button variant="outline" className="mt-2 w-full border-dashed text-muted-foreground" aria-expanded={showLegacy} onClick={() => setShowLegacy(!showLegacy)}>
            {showLegacy ? 'Hide' : 'Show'} {legacy.length} older runs (in .council/runs)
          </Button>
        ) : null}
        {showLegacy ? (
          <ul className="grid grid-cols-1 gap-1 rounded-2xl border bg-card p-4 text-sm sm:grid-cols-2">
            {legacy.map((r) => (
              <li key={r.run_id} className="flex items-center gap-1">
                <a href={`/runs/${encodeURIComponent(r.run_id)}/`} className="min-w-0 flex-1 truncate text-primary underline-offset-4 hover:underline">{r.run_id}</a>
                <span className="shrink-0 text-xs text-muted-foreground">{r.kind || r.state || ''}{r.confidence ? ` · ${r.confidence}` : ''}</span>
                <DeleteWork runId={r.run_id} title={r.run_id} onDeleted={onDeleted} onError={onDeleteError} />
              </li>
            ))}
          </ul>
        ) : null}
      </nav>
    </div>
  )
}
