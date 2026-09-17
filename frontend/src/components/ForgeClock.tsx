import { formatClock } from '../formatElapsed'

export function ForgeClock({
  elapsedMs,
  compact = false,
  message = 'Local model is extracting the record. This is not a chat — large transcripts can take several minutes.',
}: {
  elapsedMs: number
  compact?: boolean
  message?: string
}) {
  return (
    <div className={compact ? 'forge-clock compact' : 'forge-clock'}>
      <time dateTime={`PT${Math.floor(elapsedMs / 1000)}S`}>
        {formatClock(elapsedMs)}
      </time>
      <p role="status" aria-live="polite">
        {message}
      </p>
      <span className="scan" aria-hidden="true">
        <span />
      </span>
    </div>
  )
}
