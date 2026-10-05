import { useTheme } from '../theme'
import type { Readiness } from '../types/run'
import { MoonIcon, SunIcon } from './icons'
import { Logo } from './Logo'

export function Header({
  readiness,
  onHome,
}: {
  readiness: Readiness | null
  onHome: () => void
}) {
  const [theme, toggleTheme] = useTheme()
  const ready = readiness?.status === 'ok'

  return (
    <header className="topbar">
      <button type="button" className="brand" onClick={onHome} aria-label="Planar home">
        <span className="brand-mark">
          <Logo size={22} />
        </span>
        <span className="brand-name">Planar</span>
      </button>
      <div className="topbar-right">
        {readiness ? (
          <span
            className={`status-pill ${ready ? 'is-ok' : 'is-down'}`}
            title={ready ? 'Local model is ready' : readiness.detail ?? 'Model not ready'}
          >
            <span className="status-dot" aria-hidden="true" />
            {ready ? readiness.model : 'Model offline'}
          </span>
        ) : null}
        <button
          type="button"
          className="icon-button"
          onClick={toggleTheme}
          aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          title={theme === 'dark' ? 'Light theme' : 'Dark theme'}
        >
          {theme === 'dark' ? <SunIcon size={18} /> : <MoonIcon size={18} />}
        </button>
      </div>
    </header>
  )
}
