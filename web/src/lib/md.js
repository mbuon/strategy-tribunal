// Client-side Markdown fallback: renders raw .md fetched over HTTP when the
// file was not embedded in the page (offline file:// use is served embedded).
// Kept equivalent to dashboard.md_to_html (headings, bullets, tables, bold, code).
export function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

export function inlineMd(s) {
  s = esc(s)
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>')
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  return s
}

export function mdRender(md) {
  const out = []
  let inList = false
  let table = []
  const flushList = () => { if (inList) { out.push('</ul>'); inList = false } }
  const flushTable = () => {
    if (!table.length) return
    const rows = table.filter((r) => !/^\|?\s*:?-{2,}/.test(r))
    const cells = rows.map((r) => r.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim()))
    if (cells.length) {
      out.push('<table><tr>' + cells[0].map((c) => `<th>${inlineMd(c)}</th>`).join('') + '</tr>')
      for (let i = 1; i < cells.length; i++) {
        out.push('<tr>' + cells[i].map((c) => `<td>${inlineMd(c)}</td>`).join('') + '</tr>')
      }
      out.push('</table>')
    }
    table = []
  }
  for (const line of String(md).split('\n')) {
    if (line.charAt(0) === '|') { flushList(); table.push(line); continue }
    flushTable()
    const m = /^(#{1,3})\s+(.*)$/.exec(line)
    if (m) { flushList(); out.push(`<h${m[1].length}>${inlineMd(m[2])}</h${m[1].length}>`) }
    else if (line.indexOf('- ') === 0) {
      if (!inList) { out.push('<ul>'); inList = true }
      out.push(`<li>${inlineMd(line.slice(2))}</li>`)
    }
    else if (line.trim() === '') { flushList() }
    else { flushList(); out.push(`<p>${inlineMd(line)}</p>`) }
  }
  flushList(); flushTable()
  return out.join('\n')
}
