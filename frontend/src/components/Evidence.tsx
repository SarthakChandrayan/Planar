import { useState } from 'react'
import type { SourceReference } from '../types/analysis'

interface EvidenceProps {
  refs: SourceReference[]
}

export function Evidence({ refs }: EvidenceProps) {
  const sources = refs.filter((ref) => ref.excerpt.trim())
  if (sources.length === 0) {
    return null
  }

  return (
    <div className="evidence-stack">
      {sources.map((ref, index) => (
        <EvidenceQuote
          key={`${index}-${ref.line_start ?? ''}-${ref.excerpt.slice(0, 24)}`}
          source={ref}
          index={index}
          total={sources.length}
        />
      ))}
    </div>
  )
}

function locationLabel(ref: SourceReference): string | null {
  const parts: string[] = []
  if (ref.line_start != null) {
    parts.push(
      ref.line_end != null && ref.line_end !== ref.line_start
        ? `L${ref.line_start}–${ref.line_end}`
        : `L${ref.line_start}`,
    )
  }
  if (ref.speaker) {
    parts.push(ref.speaker)
  }
  return parts.length > 0 ? parts.join(' · ') : null
}

function EvidenceQuote({
  source,
  index,
  total,
}: {
  source: SourceReference
  index: number
  total: number
}) {
  const [copied, setCopied] = useState(false)
  const base = total > 1 ? `Source ${index + 1}` : 'Source'
  const location = locationLabel(source)
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
    <details className="evidence">
      <summary>
        {base}
        {location ? <span className="evidence-location"> · {location}</span> : null}
      </summary>
      <div className="evidence-panel">
        <blockquote className="evidence-quote">{excerpt}</blockquote>
        <div className="evidence-actions">
          <button type="button" className="button-ghost" onClick={() => void copy()}>
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      </div>
    </details>
  )
}
