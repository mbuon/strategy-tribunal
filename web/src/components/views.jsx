import * as React from 'react'
import { Badge } from './ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from './ui/accordion'
import { MdLink } from './modal'

export function Html({ h }) {
  return <span dangerouslySetInnerHTML={{ __html: h }} />
}

export function StateBadge({ value, cls }) {
  const variant = cls === 'ok' ? 'ok' : cls === 'warn' ? 'warn' : cls === 'bad' ? 'bad' : 'secondary'
  return <Badge variant={variant}>{value}</Badge>
}

export function Kpis({ items }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {items.map((k, i) => (
        <Card key={i}>
          <CardContent className="p-4">
            <div className="text-xl font-semibold">{k.v}</div>
            <div className="text-xs text-muted-foreground">{k.l}</div>
            {k.s ? <div className="text-xs text-muted-foreground">{k.s}</div> : null}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

export function GenTable({ cols, rows }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>{cols.map((c, i) => <TableHead key={i}>{c}</TableHead>)}</TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r, i) => (
          <TableRow key={i}>
            {r.map((c, j) => (
              <TableCell key={j}>{c && typeof c === 'object' && 'html' in c ? <Html h={c.html} /> : c}</TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

export function OutcomeView({ outcome }) {
  if (!outcome) return <p className="text-sm text-muted-foreground">No decision yet.</p>
  if (outcome.pending) return <p className="text-sm text-muted-foreground">{outcome.pending}</p>
  return (
    <Card>
      <CardHeader>
        <CardTitle>{outcome.recTitle}</CardTitle>
        <CardDescription>{outcome.recSummary}</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableBody>
            <TableRow><TableCell className="w-44 font-medium">Decision kind</TableCell><TableCell>{outcome.kind}</TableCell></TableRow>
            <TableRow>
              <TableCell className="font-medium">Confidence</TableCell>
              <TableCell><StateBadge value={outcome.confLevel} cls={outcome.confCls} /> <span className="text-sm text-muted-foreground">{outcome.confBasis}</span></TableCell>
            </TableRow>
            <TableRow><TableCell className="font-medium">Stopping reason</TableCell><TableCell>{outcome.stop}</TableCell></TableRow>
            <TableRow><TableCell className="font-medium">Next action</TableCell><TableCell>{outcome.next}</TableCell></TableRow>
            <TableRow><TableCell className="font-medium">Strongest alternatives</TableCell><TableCell>{outcome.alts || <span className="text-muted-foreground">none</span>}</TableCell></TableRow>
            <TableRow><TableCell className="font-medium">Reverse when</TableCell><TableCell>{outcome.reversal.map((r, i) => <div key={i}>{r}</div>)}</TableCell></TableRow>
            <TableRow><TableCell className="font-medium">Unfinished checks</TableCell><TableCell>{outcome.unfinished.map((r, i) => <div key={i}>{r}</div>)}</TableCell></TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

export function RoundsView({ rounds, incumbentHistory, events }) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Rounds, confidence and decisions taken</h2>
      <GenTable
        cols={['round', 'incumbent', 'decision taken', 'score', 'Δ vs prior incumbent', 'net vs round 0', 'comparable', 'open critical', 'stable streak', 'calls', 'note']}
        rows={rounds.map((r) => [
          String(r.round), r.incumbent,
          <span key="t"><StateBadge value={r.outcome} cls={r.outcomeCls} /> {r.taken}</span>,
          r.score, r.deltaPrior, r.net0, String(r.comparable), String(r.openCritical),
          String(r.stableStreak), String(r.calls), r.note,
        ])}
      />
      {incumbentHistory.length > 0 && (
        <p className="text-xs text-muted-foreground">Incumbent history: {incumbentHistory.join(' → ')}</p>
      )}
      {events.length > 0 && (
        <Accordion type="single" collapsible>
          <AccordionItem value="events">
            <AccordionTrigger>Controller decisions and events ({events.length})</AccordionTrigger>
            <AccordionContent>
              <GenTable
                cols={['time', 'round', 'event', 'detail']}
                rows={events.map((x) => [x.time, String(x.round), <code key="k">{x.kind}</code>, x.detail])}
              />
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      )}
    </div>
  )
}

export function ObjectionsView({ objections }) {
  const o = objections
  if (!o.challenges.length && !o.leader.length && !o.dissents.length) {
    return <div><h2 className="text-lg font-semibold">Objections, dissent and leader challenge</h2><p className="text-sm text-muted-foreground">None yet.</p></div>
  }
  const rows = []
  o.challenges.forEach((c) => rows.push([c.id, <StateBadge key="s" value={c.status} cls={c.statusCls} />, c.severity, c.could, c.target, c.mechanism, c.resolution]))
  o.leader.forEach((c) => rows.push([`${c.id} (leader challenge)`, <StateBadge key="s" value={c.status} cls={c.statusCls} />, 'critical', c.could, c.target, c.mechanism, c.resolution]))
  o.dissents.forEach((c) => rows.push([`${c.id} (dissent)`, <Badge key="s" variant="secondary">recorded</Badge>, '—', '—', c.target, `${c.position} — ${c.reason}`, c.whatYouLose]))
  return (
    <div>
      <h2 className="text-lg font-semibold">Objections, dissent and leader challenge</h2>
      <GenTable cols={['id', 'status', 'severity', 'could change', 'target', 'mechanism', 'resolution condition']} rows={rows} />
    </div>
  )
}

export function WhoView({ who, chatNote }) {
  return (
    <div>
      <h2 className="text-lg font-semibold">Who answered — participants</h2>
      <GenTable
        cols={['participant', 'role', 'lens', 'answered by', 'isolation', 'calls', 'tokens', 'avg latency', 'effort']}
        rows={who.map((p) => [
          <code key="i">{p.id}</code>, p.role, p.lens || '',
          <span key="w"><StateBadge value={p.provider} cls={p.provCls} /> {p.model}</span>,
          p.isolation, String(p.calls), String(p.tokens), p.avg, p.effort || '',
        ])}
      />
      <p className="mt-2 text-xs text-muted-foreground">{chatNote}</p>
    </div>
  )
}

export function ReasoningView({ steps }) {
  return (
    <div>
      <h2 className="text-lg font-semibold">Reasoning workflow — what the models did in their roles</h2>
      <p className="text-xs text-muted-foreground">
        The <strong>reasoning workflow</strong> is the content: how the question was framed, which gates and criteria were registered,
        which options came from which lens, which objections were raised and answered, how the judge scored, whether a challenger
        displaced the incumbent, what the leader challenge argued, what was decided. Rows marked <em>controller</em> are
        adjudications the Python controller computed from the models’ records (no model call).
      </p>
      <GenTable
        cols={['#', 'round', 'phase', 'step', 'by (role · provider · model)', 'what was produced', 'records']}
        rows={steps.map((s, i) => [
          String(i + 1), String(s.round), s.phase, <code key="k">{s.kind}</code>,
          <Html key="b" h={s.byHtml} />, s.what, <span key="d" className="text-xs text-muted-foreground">{s.ids}</span>,
        ])}
      />
    </div>
  )
}

export function DiscussionView({ items, policyNote, documents, docNotes, mdMap }) {
  return (
    <div>
      <h2 className="text-lg font-semibold">Discussion — every contribution in order, as the other roles read it</h2>
      {policyNote ? <p className="text-xs text-muted-foreground">{policyNote}</p> : null}
      {items.length ? (
        <GenTable
          cols={['#', 'round', 'phase', 'role / lens', 'answered by', 'outcome', 'what it says (summary)', 'file']}
          rows={items.map((x) => [
            `D${x.n}`, String(x.round), x.phase, x.roleLens, x.by,
            <span key="o"><StateBadge value={x.outcome} cls={x.outcome === 'committed' ? 'ok' : 'warn'} />{x.error ? ` ${x.error}` : ''}</span>,
            x.summary,
            x.file ? <MdLink key="f" href={x.file} docKey={x.file} title={x.fileName} preHtml={(mdMap && mdMap[x.file]) || x.fileHtml || null}>{x.fileName}</MdLink> : '',
          ])}
        />
      ) : <p className="text-sm text-muted-foreground">No contribution yet.</p>}
      {items.filter((x) => x.fileHtml).map((x) => (
        <Accordion key={x.n} type="single" collapsible className="mt-2">
          <AccordionItem value={`d${x.n}`}>
            <AccordionTrigger>D{x.n} · round {x.round} · {x.roleLens} · {x.outcome}</AccordionTrigger>
            <AccordionContent><div className="report" dangerouslySetInnerHTML={{ __html: x.fileHtml }} /></AccordionContent>
          </AccordionItem>
        </Accordion>
      ))}
      <h2 className="mt-6 text-lg font-semibold">Input documents</h2>
      {documents.length ? (
        <GenTable
          cols={['evidence id', 'name', 'chars', 'original path', 'copy']}
          rows={documents.map((x) => [
            <code key="e">{x.evid}</code>, x.name, String(x.chars),
            <span key="p" className="text-xs text-muted-foreground">{x.path}</span>,
            x.isMd
              ? <MdLink key="c" href={x.copy} docKey={x.copy} title={x.copy} preHtml={(mdMap && mdMap[x.copy]) || null}>{x.copy}</MdLink>
              : <a key="c" href={x.copy} className="text-primary underline-offset-4 hover:underline">{x.copy}</a>,
          ])}
        />
      ) : <p className="text-sm text-muted-foreground">None supplied (use <code>/council … --docs path,folder</code>).</p>}
      {docNotes ? <p className="text-xs text-muted-foreground">Notes: {docNotes}</p> : null}
    </div>
  )
}

export function SettingsView({ settings, served }) {
  return (
    <div>
      <h2 className="text-lg font-semibold">Settings in effect</h2>
      <p className="text-xs text-muted-foreground">
        Precedence: defaults &lt; council.config.json (project) &lt; .council/settings.json (saved) &lt; preset &lt; per-run overrides. {served ? 'Change saved settings with /council-settings, council settings … or the settings page.' : 'Change saved settings with /council-settings, council settings … or council ui.'}
      </p>
      <Accordion type="single" collapsible defaultValue="all">
        <AccordionItem value="all">
          <AccordionTrigger>All keys with provenance and explanation</AccordionTrigger>
          <AccordionContent>
            <GenTable
              cols={['key', 'value', 'layer', 'explanation']}
              rows={settings.map((s) => [
                <code key="k">{s.key}</code>, <code key="v">{s.value}</code>,
                <StateBadge key="l" value={s.layer} cls={s.layerCls} />, s.explanation,
              ])}
            />
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  )
}

export function LogView({ rows }) {
  return (
    <div>
      <h2 className="text-lg font-semibold">Request / response log</h2>
      <Accordion type="single" collapsible>
        <AccordionItem value="log">
          <AccordionTrigger>{rows.length} requests</AccordionTrigger>
          <AccordionContent>
            <GenTable
              cols={['time', 'id', 'round', 'kind', 'role', 'participant', 'attempt', 'provider', 'outcome', 'files']}
              rows={rows.map((r) => [
                r.time, <code key="i">{r.id}</code>, String(r.round), r.kind, r.role, r.participant,
                String(r.attempt), r.provider,
                <span key="o"><StateBadge value={r.outcome} cls={r.outcomeCls} />{r.outcomeDetail}</span>,
                <Html key="f" h={r.filesHtml} />,
              ])}
            />
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  )
}

export function FilesView({ files, mdMap }) {
  return (
    <div>
      <h2 className="text-lg font-semibold">Files generated — who wrote them, in which round and phase, and why</h2>
      <GenTable
        cols={['file', 'written by', 'round · phase', 'why / content', 'size', 'time']}
        rows={files.map((f) => [
          f.isMd
            ? <MdLink key="f" href={f.rel} docKey={f.rel} title={f.rel} preHtml={(mdMap && mdMap[f.rel]) || null}>{f.rel}</MdLink>
            : <a key="f" href={f.rel} className="text-primary underline-offset-4 hover:underline">{f.rel}</a>,
          f.by, f.when, <span key="w" className="text-xs text-muted-foreground">{f.why}</span>,
          String(f.size), f.mtime,
        ])}
      />
    </div>
  )
}

export function ReportView({ reportHtml }) {
  if (!reportHtml) return null
  return (
    <div>
      <h2 className="text-lg font-semibold">Report</h2>
      <div className="report" dangerouslySetInnerHTML={{ __html: reportHtml }} />
    </div>
  )
}

export function OrchestrationView({ rows }) {
  return (
    <div>
      <h2 className="text-lg font-semibold">Orchestration workflow — what the controller did, request by request</h2>
      <p className="text-xs text-muted-foreground">
        The <strong>orchestration workflow</strong> is the state machine: it issues one validated request at a time to a role,
        checks the reply against the protocol, commits or rejects it, charges the budget, decides promotions and stops.
        It never reasons about the question.
      </p>
      <GenTable
        cols={['#', 'time', 'round', 'phase', 'role / lens', 'participant', 'answered by', 'tokens (in/out/reasoning)', 'latency', 'result']}
        rows={rows.map((r, i) => [
          String(i + 1), r.time, String(r.round), r.phase, r.roleLens, r.participant, r.who, r.toks, r.lat,
          <span key="r"><StateBadge value={r.res} cls={r.resCls} />{r.resDetail}</span>,
        ])}
      />
    </div>
  )
}
