import { formatClock } from '../formatElapsed'

export interface ForgeStage {
  label: string
  step: number
  total: number
  tokens: number
}

export function ForgeClock({
  elapsedMs,
  compact = false,
  stage = null,
  message = 'Local model is extracting the record. This is not a chat — large transcripts can take several minutes.',
  onCancel,
}: {
  elapsedMs: number
  compact?: boolean
  stage?: ForgeStage | null
  message?: string
  onCancel?: () => void
}) {
  const percent =
    stage && stage.total > 0
      ? Math.round(((Math.max(stage.step, 1) - 1) / stage.total) * 100)
      : null

  return (
    <div className={compact ? 'forge-clock compact' : 'forge-clock'}>
      <time dateTime={`PT${Math.floor(elapsedMs / 1000)}S`}>
        {formatClock(elapsedMs)}
      </time>
      {stage && stage.total > 0 ? (
        <div className="forge-stage">
          <p role="status" aria-live="polite">
            <strong>
              Step {Math.max(stage.step, 1)} of {stage.total}
            </strong>{' '}
            · {stage.label}
            {stage.tokens > 0 ? (
              <span className="forge-tokens"> · {stage.tokens} tokens written</span>
            ) : null}
          </p>
          <span
            className="stage-bar"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent ?? 0}
          >
            <span style={{ width: `${percent ?? 0}%` }} />
          </span>
        </div>
      ) : (
        <p role="status" aria-live="polite">
          {stage?.label ?? message}
        </p>
      )}
      <span className="scan" aria-hidden="true">
        <span />
      </span>
      {onCancel ? (
        <button type="button" className="button-ghost forge-cancel" onClick={onCancel}>
          Cancel
        </button>
      ) : null}
    </div>
  )
}
