import * as React from 'react'
import { Check, Copy } from 'lucide-react'
import { Button } from './ui/button'

function copyText(text) {
  if (navigator.clipboard && window.isSecureContext !== false) {
    return navigator.clipboard.writeText(text)
  }
  return new Promise((resolve, reject) => {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.left = '-9999px'
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy') ? resolve() : reject(new Error('copy refused'))
    } catch (err) {
      reject(err)
    } finally {
      document.body.removeChild(ta)
    }
  })
}

// The prompt to paste into the chat once the report is out. Click anywhere on the box, or the button, to copy it.
export default function FollowUp({ text, compact }) {
  const [state, setState] = React.useState('idle')
  const preRef = React.useRef(null)
  if (!text) return null
  const doCopy = () => {
    copyText(text)
      .then(() => { setState('copied'); setTimeout(() => setState('idle'), 1800) })
      .catch(() => {
        setState('failed')
        if (preRef.current) {
          const range = document.createRange()
          range.selectNodeContents(preRef.current)
          const sel = window.getSelection()
          sel.removeAllRanges()
          sel.addRange(range)
        }
      })
  }
  return (
    <section className="overflow-hidden rounded-2xl border border-primary/30 bg-card shadow-sm" aria-labelledby="followup-h">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-primary/5 px-5 py-3">
        <div>
          <h2 id="followup-h" className="text-base font-semibold">Continue in the chat</h2>
          <p className="text-xs text-muted-foreground">
            Paste this prompt into your chat (Claude, ChatGPT, Gemini, any model) to plan the recommended action. It carries the question, the decision, what is still open and the ask.
          </p>
        </div>
        <Button size="sm" onClick={doCopy} aria-live="polite" variant={state === 'copied' ? 'secondary' : 'default'}>
          {state === 'copied' ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          {state === 'copied' ? 'Copied' : state === 'failed' ? 'Select and copy' : 'Copy prompt'}
        </Button>
      </div>
      <pre
        ref={preRef}
        onClick={doCopy}
        title="Click to copy"
        className={`cursor-copy whitespace-pre-wrap break-words px-5 py-4 font-sans text-[13.5px] leading-relaxed ${compact ? 'max-h-72 overflow-y-auto' : ''}`}
      >
        {text}
      </pre>
    </section>
  )
}
