import { useState } from 'react'
import type { SourceReference } from '../types/analysis'
import { CheckIcon, CopyIcon, QuoteIcon } from './icons'

function locationLabel(ref: SourceReference): string {
  const parts: string[] = []
  if (ref.line_start != null) {
    parts.push(
      ref.line_end != null && ref.line_end !== ref.line_start
        ? `Lines ${ref.line_start}–${ref.line_end}`
        : `Line ${ref.line_start}`,
    )
  }
  if (ref.speaker) {
    parts.push(ref.speaker)
  }
  return parts.length > 0 ? parts.join(' · ') : 'Source'
}

/** Where in the transcript an item came from; the quote opens on demand. */
export function Evidence({ refs }: { refs: SourceReference[] }) {
  const sources = refs.filter((ref) => ref.excerpt.trim())
  const [open, setOpen] = useState<number | null>(null)
  if (sources.length === 0) {
    return null
  }

  return (
    <div className="evidence">
      <div className="evidence-toggles">
        {sources.map((ref, index) => (
          <button
            key={`${index}-${ref.line_start ?? ref.excerpt.slice(0, 12)}`}
            type="button"
            className={open === index ? 'evidence-toggle is-open' : 'evidence-toggle'}
            aria-expanded={open === index}
            onClick={() => setOpen(open === index ? null : index)}
          >
            <QuoteIcon size={13} />
            {locationLabel(ref)}
          </button>
        ))}
      </div>
      {open != null && sources[open] ? <Quote source={sources[open]} /> : null}
    </div>
  )
}

function Quote({ source }: { source: SourceReference }) {
  const [copied, setCopied] = useState(false)
  const excerpt = source.excerpt.trim()

  async function copy() {
    try {
      await navigator.clipboard.writeText(excerpt)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1200)
    } catch {
      setCopied(false)
    }
  }

  return (
    <figure className="quote">
      <blockquote>{excerpt}</blockquote>
      <button
        type="button"
        className="icon-button quote-copy"
        onClick={() => void copy()}
        aria-label="Copy quote"
        title={copied ? 'Copied' : 'Copy quote'}
      >
        {copied ? <CheckIcon size={14} /> : <CopyIcon size={14} />}
      </button>
    </figure>
  )
}
