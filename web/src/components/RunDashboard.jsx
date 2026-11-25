import * as React from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs'
import { ThemeToggle, useTheme } from './theme'
import { ModalProvider } from './modal'
import FollowUp from './FollowUp'
import { CONF, toneOf, localWhen } from '../lib/kind'
import {
  RoundsView, ObjectionsView, WhoView, ReasoningView,
  OrchestrationView, DiscussionView, SettingsView, LogView, FilesView, ReportView,
} from './views'

function Chip({ cls, children }) {
  return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${cls}`}>{children}</span>
}

function Header({ s, dark, onToggle }) {
  const tone = toneOf(s)
  const o = s.outcome && !s.outcome.pending ? s.outcome : null
  return (
    <div className={`mb-4 rounded-2xl border border-l-[10px] bg-card p-5 text-card-foreground shadow-sm ${tone.border}`}>
      <div className="flex items-start justify-between gap-3">
        <h1 className="max-w-[68ch] text-2xl font-bold leading-tight tracking-tight [overflow-wrap:anywhere]">{s.title}</h1>
        <ThemeToggle dark={dark} onToggle={onToggle} />
      </div>
      {s.title !== s.question && <p className="mt-1 max-w-[80ch] text-sm text-muted-foreground">{s.question}</p>}
      {s.replay && (
        <p className="mt-3 rounded-lg bg-fail/15 px-3 py-2 text-sm font-medium text-fail-ink dark:text-fail">⚠ {s.replay}</p>
      )}
      <div className="mt-3 flex flex-wrap gap-1.5">
        <Chip cls={tone.chip}>{tone.label}</Chip>
        {o && o.confLevel ? <Chip cls={CONF[o.confLevel] || 'bg-muted'}>confidence {o.confLevel}</Chip> : null}
        <Chip cls="bg-muted text-muted-foreground">{String(s.state).toLowerCase()}</Chip>
        <Chip cls="bg-muted text-muted-foreground">round {s.round}</Chip>
        <Chip cls="bg-muted text-muted-foreground">{s.stop ? `stopped: ${s.stop}` : 'running'}</Chip>
        <Chip cls="bg-muted text-muted-foreground">{s.preset || 'standard'}</Chip>
      </div>
      <p className="mt-3 text-xs text-muted-foreground [overflow-wrap:anywhere]">
        Answered by {s.answeredBy}. Started {localWhen(s.createdAt)}. Run <code>{s.runId}</code>, folder <code>{s.folder}</code>.
      </p>
    </div>
  )
}

function Verdict({ s }) {
  const o = s.outcome
  if (!o) return <div className="rounded-2xl border p-5 text-sm text-muted-foreground">No decision yet.</div>
  if (o.pending) return <div className={`rounded-2xl border border-l-[10px] ${toneOf(s).border} bg-card p-5 text-sm text-muted-foreground`}>{o.pending}</div>
  const tone = toneOf(s)
  const alts = (o.alts || '').split('; ').filter(Boolean)
  const Block = ({ title, items, empty }) => (
    <div>
      <h3 className="mb-1 mt-2 text-xs font-semibold text-muted-foreground">{title}</h3>
      {items.length
        ? <ul className="list-disc space-y-1 pl-4 text-sm leading-snug">{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
        : <p className="text-sm text-muted-foreground">{empty}</p>}
    </div>
  )
  return (
    <section className="overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm" aria-labelledby="verdict-h">
      <div className={`border-l-[10px] px-6 py-5 ${tone.border}`}>
        <h2 id="verdict-h" className="mb-2 flex flex-wrap gap-1.5 text-sm">
          <Chip cls={tone.chip}>{tone.label}</Chip>
          <Chip cls={CONF[o.confLevel] || 'bg-muted'}>confidence {o.confLevel}</Chip>
        </h2>
        <p className="text-[22px] font-bold leading-tight tracking-tight">{o.recTitle}</p>
        {o.recSummary ? <p className="mt-2 text-[15px] leading-relaxed text-foreground/85">{o.recSummary}</p> : null}
        <p className="mt-2 text-xs text-muted-foreground">{o.confBasis}</p>
        <h3 className="mb-1 mt-4 text-xs font-semibold text-muted-foreground">Next action</h3>
        <p className="text-[15px] leading-relaxed">{o.next}</p>
      </div>
      <div className="grid grid-cols-1 gap-x-7 border-t bg-muted/40 px-6 pb-5 pt-3 md:grid-cols-3">
        <Block title="Reverse or reopen when" items={o.reversal} empty="No reversal condition recorded." />
        <Block title="Strongest alternatives" items={alts} empty="None." />
        <Block title="Unfinished checks" items={o.unfinished} empty="None." />
      </div>
    </section>
  )
}

function StatStrip({ items }) {
  const by = {}
  items.forEach((k) => { by[k.l] = k })
  const pick = (labels) => labels.map((l) => by[l]).filter(Boolean)
  const usage = pick(['Model calls', 'Tokens', 'Elapsed', 'Cost', 'Rounds', 'Options', 'Promotions', 'Open objections', 'Rejected replies'])
  const signals = pick(['Evidence quality', 'Judge agreement', 'Ranking robustness'])
  const Tile = ({ k, muted }) => (
    <div className={`flex min-h-16 flex-col gap-0.5 rounded-xl border px-3 py-2.5 ${muted ? 'bg-muted/40' : 'bg-card'}`} title={k.s || ''}>
      <span className="text-lg font-bold leading-tight">{k.v}</span>
      <span className="text-xs text-muted-foreground">{k.l}</span>
      {k.s ? <span className="text-[11px] leading-tight text-muted-foreground/80">{k.s}</span> : null}
    </div>
  )
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-9">{usage.map((k) => <Tile key={k.l} k={k} />)}</div>
      {signals.length ? <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">{signals.map((k) => <Tile key={k.l} k={k} muted />)}</div> : null}
    </div>
  )
}

const TAB_IDS = ['overview', 'reasoning', 'orchestration', 'settings', 'discussion', 'files', 'report']

function useHashTab() {
  const read = () => {
    const h = (window.location.hash || '').replace('#', '')
    return TAB_IDS.includes(h) ? h : 'overview'
  }
  const [tab, setTab] = React.useState(read)
  React.useEffect(() => {
    const onHash = () => setTab(read())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const choose = (v) => {
    setTab(v)
    try { window.history.replaceState(null, '', v === 'overview' ? window.location.pathname + window.location.search : `#${v}`) } catch { /* file:// */ }
  }
  return [tab, choose]
}

const pill = 'rounded-full border bg-card px-4 py-2 text-sm font-semibold text-foreground shadow-none data-[state=active]:border-foreground data-[state=active]:bg-foreground data-[state=active]:text-background'

export default function RunDashboard({ state: s }) {
  const [dark, toggle] = useTheme()
  const [tab, setTab] = useHashTab()
  return (
    <ModalProvider mdMap={s.mdMap}>
      <Header s={s} dark={dark} onToggle={toggle} />
      <Tabs value={tab} onValueChange={setTab} className="w-full">
        <TabsList aria-label="Run dashboard tabs" className="flex h-auto flex-wrap justify-start gap-1.5 bg-transparent p-0">
          <TabsTrigger value="overview" className={pill}>Overview</TabsTrigger>
          <TabsTrigger value="reasoning" className={pill}>Reasoning workflow</TabsTrigger>
          <TabsTrigger value="orchestration" className={pill}>Orchestration</TabsTrigger>
          <TabsTrigger value="settings" className={pill}>Settings</TabsTrigger>
          <TabsTrigger value="discussion" className={pill}>
            Discussion{s.discussion.length ? <span className="ml-1.5 rounded-full bg-muted px-1.5 text-xs text-muted-foreground data-[state=active]:bg-background/20">{s.discussion.length}</span> : null}
          </TabsTrigger>
          <TabsTrigger value="files" className={pill}>Files</TabsTrigger>
          <TabsTrigger value="report" className={pill}>Report</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="space-y-5">
          <Verdict s={s} />
          <StatStrip items={s.kpis} />
          <RoundsView rounds={s.rounds} incumbentHistory={s.incumbentHistory} events={s.events} />
          <FollowUp text={s.followUp} compact />
        </TabsContent>
        <TabsContent value="reasoning">
          <div className="space-y-6">
            <ReasoningView steps={s.reasoning} />
            <ObjectionsView objections={s.objections} />
          </div>
        </TabsContent>
        <TabsContent value="orchestration">
          <div className="space-y-6">
            <WhoView who={s.who} chatNote={s.chatNote} />
            <OrchestrationView rows={s.orchestration} />
            <LogView rows={s.log} />
          </div>
        </TabsContent>
        <TabsContent value="settings">
          <SettingsView settings={s.settings} served={s.served} />
        </TabsContent>
        <TabsContent value="discussion">
          <DiscussionView items={s.discussion} policyNote={s.discussionPolicyNote} documents={s.documents} docNotes={s.docNotes} mdMap={s.mdMap} />
        </TabsContent>
        <TabsContent value="files">
          <FilesView files={s.files} mdMap={s.mdMap} />
        </TabsContent>
        <TabsContent value="report" className="space-y-6">
          <ReportView reportHtml={s.reportHtml} />
          <FollowUp text={s.followUp} />
        </TabsContent>
      </Tabs>
      <p className="mt-6 text-xs text-muted-foreground">
        Generated {s.generatedAt}{s.refreshSeconds ? ` · auto-refresh every ${s.refreshSeconds} s while running` : ''}
      </p>
    </ModalProvider>
  )
}
