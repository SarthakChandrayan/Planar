import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react'
import type { SampleSummary } from '../types/run'
import { ClearIcon, CollapseIcon, ExpandIcon } from './icons'

export const MIN_TRANSCRIPT_CHARS = 40
const UNDO_MS = 8000

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
  const [expanded, setExpanded] = useState(false)
  // The text that "Clear" removed, kept briefly so it can be undone.
  const [cleared, setCleared] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const words = countWords(value)
  const tooShort = value.trim().length > 0 && value.trim().length < MIN_TRANSCRIPT_CHARS

  // Full screen: Esc closes it, Ctrl+Shift+F toggles it from anywhere on the page.
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape' && expanded) {
        setExpanded(false)
      } else if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'f') {
        event.preventDefault()
        setExpanded((open) => !open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  // While full screen, the page behind must not scroll; keep the cursor in the text.
  useEffect(() => {
    if (!expanded) {
      return
    }
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    textareaRef.current?.focus()
    return () => {
      document.body.style.overflow = previous
    }
  }, [expanded])

  // The undo offer disappears after a few seconds.
  useEffect(() => {
    if (cleared == null) {
      return
    }
    const timer = window.setTimeout(() => setCleared(null), UNDO_MS)
    return () => window.clearTimeout(timer)
  }, [cleared])

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault()
      onSubmit()
    }
  }

  function clear() {
    if (!value) {
      return
    }
    setCleared(value)
    onChange('')
    textareaRef.current?.focus()
  }

  function undoClear() {
    if (cleared != null) {
      onChange(cleared)
      setCleared(null)
    }
  }

  // Double-click on the frame (not inside the text, where it selects a word).
  function toggleFromFrame(event: MouseEvent<HTMLElement>) {
    if (event.target === event.currentTarget) {
      setExpanded((open) => !open)
    }
  }

  return (
    <section
      className={expanded ? 'composer card is-expanded' : 'composer card'}
      aria-labelledby="composer-title"
      onDoubleClick={toggleFromFrame}
    >
      <div className="composer-head" onDoubleClick={toggleFromFrame}>
        <label id="composer-title" className="composer-label" htmlFor="meeting-transcript">
          Meeting transcript
        </label>
        <div className="composer-tools">
          {value ? (
            <button
              type="button"
              className="tool-button"
              onClick={clear}
              title="Clear the transcript"
            >
              <ClearIcon size={15} />
              Clear
            </button>
          ) : null}
          <button
            type="button"
            className="tool-button"
            onClick={() => setExpanded((open) => !open)}
            aria-pressed={expanded}
            title={expanded ? 'Exit full screen (Esc)' : 'Full screen (Ctrl+Shift+F)'}
          >
            {expanded ? <CollapseIcon size={15} /> : <ExpandIcon size={15} />}
            {expanded ? 'Exit full screen' : 'Full screen'}
          </button>
        </div>
      </div>

      <textarea
        ref={textareaRef}
        id="meeting-transcript"
        name="transcript"
        value={value}
        onChange={(event) => {
          onChange(event.target.value)
          if (cleared != null) {
            setCleared(null)
          }
        }}
        onKeyDown={handleKeyDown}
        placeholder={
          'Paste the transcript or notes from a meeting.\n\n' +
          'Maya: Let’s lock the processor for November.\n' +
          'Arjun: Agreed. I’ll write up the API contract by Friday.'
        }
        rows={12}
        spellCheck={false}
      />

      {samples.length > 0 && !value.trim() && !expanded ? (
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
        {cleared != null ? (
          <p className="composer-meta" role="status">
            Transcript cleared.{' '}
            <button type="button" className="link-button inline" onClick={undoClear}>
              Undo
            </button>
          </p>
        ) : (
          <p className={tooShort ? 'composer-meta warn' : 'composer-meta'}>
            {words > 0 ? `${words.toLocaleString()} words` : 'Runs entirely on this computer'}
            {tooShort ? ` · need at least ${MIN_TRANSCRIPT_CHARS} characters` : null}
            {estimateLabel && !tooShort ? <span> · {estimateLabel}</span> : null}
          </p>
        )}
        <div className="composer-actions">
          <span className="kbd-hint" aria-hidden="true">
            Ctrl + Enter
          </span>
          <button
            type="button"
            className="button button-primary"
            onClick={() => {
              setExpanded(false)
              onSubmit()
            }}
          >
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
