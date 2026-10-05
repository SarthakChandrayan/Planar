import type { KeyboardEvent } from 'react'

interface MeetingInputProps {
  value: string
  disabled: boolean
  elapsedLabel: string | null
  error: string | null
  estimateLabel?: string | null
  onChange: (value: string) => void
  onSubmit: () => void
}

export const MIN_TRANSCRIPT_CHARS = 40

export function MeetingInput({
  value,
  disabled,
  elapsedLabel,
  error,
  estimateLabel = null,
  onChange,
  onSubmit,
}: MeetingInputProps) {
  const count = value.length
  const tooShort = value.trim().length > 0 && value.trim().length < MIN_TRANSCRIPT_CHARS

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault()
      onSubmit()
    }
  }

  return (
    <section className="panel" aria-labelledby="transcript-heading">
      <div className="panel-heading">
        <h2 id="transcript-heading">Transcript</h2>
        <span className="kbd">Ctrl + Enter</span>
      </div>

      <label className="sr-only" htmlFor="meeting-transcript">
        Meeting transcript
      </label>
      <textarea
        id="meeting-transcript"
        name="transcript"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Meeting: Payment Platform Redesign&#10;Maya: Let's lock the processor for November..."
        rows={8}
        spellCheck={false}
      />

      <div className="input-meta">
        <p className={tooShort ? 'char-count warn' : 'char-count'}>
          {count.toLocaleString()}
          {tooShort ? ` / ${MIN_TRANSCRIPT_CHARS}` : null}
          {estimateLabel && !disabled ? (
            <span className="estimate"> · {estimateLabel}</span>
          ) : null}
        </p>
        <button type="button" onClick={onSubmit} disabled={disabled}>
          {disabled ? `Forging ${elapsedLabel ?? ''}`.trim() : 'Forge'}
        </button>
      </div>

      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  )
}
