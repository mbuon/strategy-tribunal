import * as React from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from './ui/dialog'
import { mdRender } from '../lib/md'

const ModalCtx = React.createContext(() => {})

export function useOpenDoc() {
  return React.useContext(ModalCtx)
}

export function ModalHost({ doc, mdMap, onClose }) {
  const [fetched, setFetched] = React.useState(null)
  React.useEffect(() => { setFetched(null) }, [doc && doc.href])
  React.useEffect(() => {
    if (!doc || doc.html || fetched) return
    let cancelled = false
    fetch(doc.href, { headers: { Accept: 'text/plain' } })
      .then((r) => { if (!r.ok) throw new Error('fetch failed'); return r.text() })
      .then((t) => { if (!cancelled) setFetched(mdRender(t)) })
      .catch(() => { window.location.href = doc.href })
    return () => { cancelled = true }
  }, [doc, fetched])
  React.useEffect(() => {
    if (!doc) return
    const mr = document.querySelector("meta[http-equiv='refresh']")
    if (mr && mr.parentNode) mr.parentNode.removeChild(mr)
  }, [doc])
  const html = doc ? (doc.html || (mdMap && mdMap[doc.key]) || fetched) : null
  return (
    <Dialog open={!!doc} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle className="font-mono text-sm">{doc ? doc.title : ''}</DialogTitle>
        </DialogHeader>
        <div className="flex justify-end">
          <a href={doc ? doc.href : '#'} className="text-sm text-primary underline-offset-4 hover:underline">
            open raw
          </a>
        </div>
        {html
          ? <div className="report" dangerouslySetInnerHTML={{ __html: html }} />
          : <p className="text-sm text-muted-foreground">Loading…</p>}
      </DialogContent>
    </Dialog>
  )
}

export function ModalProvider({ mdMap, children }) {
  const [doc, setDoc] = React.useState(null)
  const openDoc = React.useCallback((d) => setDoc(d), [])
  const close = React.useCallback(() => setDoc(null), [])
  return (
    <ModalCtx.Provider value={openDoc}>
      {children}
      <ModalHost doc={doc} mdMap={mdMap} onClose={close} />
    </ModalCtx.Provider>
  )
}

export function MdLink({ docKey, href, title, preHtml, children }) {
  const openDoc = useOpenDoc()
  return (
    <a
      href={href}
      className="text-primary underline-offset-4 hover:underline after:ml-0.5 after:text-xs after:text-muted-foreground after:content-['◧']"
      onClick={(ev) => { ev.preventDefault(); openDoc({ title, href, key: docKey, html: preHtml || null }) }}
    >
      {children}
    </a>
  )
}
