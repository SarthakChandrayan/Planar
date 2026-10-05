import type { KeyboardEvent } from 'react'
import type { SampleSummary } from '../types/run'

export const MIN_TRANSCRIPT_CHARS = 40

function countWords(text: string): number {
  const trimmed = text.trim()
  return trimmed ? trimmed.split(/\s+/).length : 0
}

interface ComposerProps {
  value: string
  error: string | null
  estimateLabel: string | null
  samples: SampleSummary[]
  loadingSample: string | null
  onChange: (value: string) => void
  onSubmit: () => void
  onLoadSample: (id: string) => void
}

export function Composer({
  value,
  error,
  estimateLabel,
  samples,
  loadingSample,
  onChange,
  onSubmit,
  onLoadSample,
}: ComposerProps) {
  const words = countWords(value)
  const tooShort = value.trim().length > 0 && value.trim().length < MIN_TRANSCRIPT_CHARS

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault()
      onSubmit()
    }
  }

  return (
    <section className="composer card" aria-labelledby="composer-title">
      <label id="composer-title" className="composer-label" htmlFor="meeting-transcript">
        Meeting transcript
      </label>
      <textarea
        id="meeting-transcript"
        name="transcript"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={
          'Paste the transcript or notes from an engineering meeting.\n\n' +
          'Maya: Let’s lock the processor for November.\n' +
          'Arjun: Agreed. I’ll write up the API contract by Friday.'
        }
        rows={12}
        spellCheck={false}
      />

      {samples.length > 0 && !value.trim() ? (
        <div className="samples">
          <span className="samples-label">No transcript handy? Try a sample:</span>
          {samples.map((sample) => (
            <button
              key={sample.id}
              type="button"
              className="chip-button"
              onClick={() => onLoadSample(sample.id)}
              disabled={loadingSample != null}
            >
              {sample.title}
              <span className="chip-meta">{sample.words.toLocaleString()} words</span>
            </button>
          ))}
        </div>
      ) : null}

      <div className="composer-foot">
        <p className={tooShort ? 'composer-meta warn' : 'composer-meta'}>
          {words > 0 ? `${words.toLocaleString()} words` : 'Runs entirely on this computer'}
          {tooShort ? ` · need at least ${MIN_TRANSCRIPT_CHARS} characters` : null}
          {estimateLabel && !tooShort ? <span> · {estimateLabel}</span> : null}
        </p>
        <div className="composer-actions">
          <span className="kbd-hint" aria-hidden="true">
            Ctrl + Enter
          </span>
          <button type="button" className="button button-primary" onClick={onSubmit}>
            Analyze meeting
          </button>
        </div>
      </div>

      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  )
}
