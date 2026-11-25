import * as React from 'react'
import RunDashboard from './components/RunDashboard'
import HomeDashboard from './components/HomeDashboard'

function readState(id) {
  const el = document.getElementById(id)
  return el ? JSON.parse(el.textContent) : null
}

export default function App() {
  const run = readState('council-state')
  const home = readState('council-home-state')
  if (run) return <RunDashboard state={run} />
  if (home) return <HomeDashboard state={home} />
  return <p className="p-6 text-sm text-muted-foreground">No council state found on this page.</p>
}
