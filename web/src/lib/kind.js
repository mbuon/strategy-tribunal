// Verdict colour language, shared by the home list and the run page.
// Every class string is a literal so Tailwind's scanner keeps it in the bundle.
export const TONE = {
  firm: {
    label: 'firm',
    stripe: 'bg-firm',
    chip: 'bg-firm/15 text-firm-ink dark:text-firm',
    border: 'border-l-firm',
    stat: 'border-firm/40 text-firm-ink dark:text-firm',
  },
  cond: {
    label: 'conditional',
    stripe: 'bg-cond',
    chip: 'bg-cond/20 text-cond-ink dark:text-cond',
    border: 'border-l-cond',
    stat: 'border-cond/50 text-cond-ink dark:text-cond',
  },
  short: {
    label: 'shortlist',
    stripe: 'bg-short',
    chip: 'bg-short/15 text-short-ink dark:text-short',
    border: 'border-l-short',
    stat: 'border-short/40 text-short-ink dark:text-short',
  },
  info: {
    label: 'needs information',
    stripe: 'bg-info',
    chip: 'bg-info/15 text-info-ink dark:text-info',
    border: 'border-l-info',
    stat: 'border-info/40 text-info-ink dark:text-info',
  },
  none: {
    label: 'no eligible option',
    stripe: 'bg-none',
    chip: 'bg-none/20 text-none-ink dark:text-none',
    border: 'border-l-none',
    stat: 'border-none/50 text-none-ink dark:text-none',
  },
  fail: {
    label: 'failed',
    stripe: 'bg-fail',
    chip: 'bg-fail/15 text-fail-ink dark:text-fail',
    border: 'border-l-fail',
    stat: 'border-fail/40 text-fail-ink dark:text-fail',
  },
  run: {
    label: 'running',
    stripe: 'bg-run',
    chip: 'bg-run/20 text-run-ink dark:text-run',
    border: 'border-l-run',
    stat: 'border-run/50 text-run-ink dark:text-run',
  },
}

const BY_KIND = { firm: 'firm', conditional: 'cond', shortlist: 'short', information_request: 'info', no_eligible_option: 'none' }

// Tone key for a dashboard state (full run state or home summary).
export function toneKey(s) {
  if (!s) return 'fail'
  if (s.state === 'FAILED') return 'fail'
  if (s.state === 'CANCELLED') return 'none'
  const o = s.outcome
  if (!o || o.pending || !o.kind) return 'run'
  return BY_KIND[o.kind] || 'none'
}

export function toneOf(s) {
  const key = toneKey(s)
  const t = TONE[key]
  if (key === 'none' && s && s.state === 'CANCELLED') return { ...t, label: 'cancelled' }
  return t
}

export const CONF = {
  high: 'bg-firm/15 text-firm-ink dark:text-firm',
  medium: 'bg-cond/20 text-cond-ink dark:text-cond',
  low: 'bg-fail/15 text-fail-ink dark:text-fail',
}

export function localWhen(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString(undefined, { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}
