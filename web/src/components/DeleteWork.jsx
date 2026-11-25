import * as React from 'react'
import { Trash2 } from 'lucide-react'
import { Button } from './ui/button'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from './ui/alert-dialog'

async function deleteRun(runId) {
  const r = await fetch(`/runs/${encodeURIComponent(runId)}/`, { method: 'DELETE', headers: { Accept: 'application/json' } })
  if (!r.ok) {
    let msg = r.statusText || `HTTP ${r.status}`
    try { const j = await r.json(); if (j && j.error) msg = j.error } catch { /* keep status text */ }
    throw new Error(msg)
  }
  return r.json()
}

export default function DeleteWork({ runId, title, onDeleted, onError }) {
  const [busy, setBusy] = React.useState(false)
  const doDelete = async () => {
    setBusy(true)
    try {
      await deleteRun(runId)
      onDeleted(runId)
    } catch (e) {
      onError(`Could not delete ${runId}: ${e.message}`)
    } finally {
      setBusy(false)
    }
  }
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Delete work ${title || runId}`} title="Delete this work">
          <Trash2 className="h-4 w-4" />
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this work?</AlertDialogTitle>
          <AlertDialogDescription>
            “{title || runId}” ({runId}) and all its files will be permanently removed. This cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep</AlertDialogCancel>
          <AlertDialogAction onClick={doDelete} disabled={busy}>Delete</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
