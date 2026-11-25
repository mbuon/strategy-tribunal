import * as React from 'react'
import { Moon, Sun } from 'lucide-react'
import { Button } from './ui/button'

export function useTheme() {
  const [dark, setDark] = React.useState(() => {
    try {
      const saved = window.localStorage.getItem('council-theme')
      if (saved) return saved === 'dark'
      return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
    } catch {
      return false
    }
  })
  React.useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    try { window.localStorage.setItem('council-theme', dark ? 'dark' : 'light') } catch { /* file:// may refuse */ }
  }, [dark])
  return [dark, () => setDark((d) => !d)]
}

export function ThemeToggle({ dark, onToggle }) {
  return (
    <Button variant="outline" size="icon" onClick={onToggle} title={dark ? 'Light mode' : 'Dark mode'} aria-label="Toggle theme">
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  )
}
