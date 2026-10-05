import { useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

const THEME_KEY = 'planar.theme'

function stored(): Theme | null {
  try {
    const value = window.localStorage.getItem(THEME_KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    return null
  }
}

function systemTheme(): Theme {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** Follows the system until the user picks a theme; the pick is remembered. */
export function useTheme(): [Theme, () => void] {
  const [picked, setPicked] = useState<Theme | null>(stored)
  const [system, setSystem] = useState<Theme>(systemTheme)

  useEffect(() => {
    const query = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!query) {
      return
    }
    const onChange = () => setSystem(query.matches ? 'dark' : 'light')
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    const root = document.documentElement
    if (picked) {
      root.dataset.theme = picked
    } else {
      delete root.dataset.theme
    }
  }, [picked])

  const theme = picked ?? system
  const toggle = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    setPicked(next)
    try {
      window.localStorage.setItem(THEME_KEY, next)
    } catch {
      // Not remembered across reloads; the toggle still works.
    }
  }
  return [theme, toggle]
}
