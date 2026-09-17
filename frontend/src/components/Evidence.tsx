import { useState } from 'react'

interface EvidenceProps {
  excerpts: string[]
}

export function Evidence({ excerpts }: EvidenceProps) {
  const quotes = excerpts.map((item) => item.trim()).filter(Boolean)
  if (quotes.length === 0) {
    return null
  }

  return (
    <div className="evidence-stack">
      {quotes.map((excerpt, index) => (
        <EvidenceQuote
          key={`${index}-${excerpt.slice(0, 24)}`}
          excerpt={excerpt}
          index={index}
          total={quotes.length}
        />
      ))}
    </div>
  )
}

function EvidenceQuote({
  excerpt,
  index,
  total,
}: {
  excerpt: string
  index: number
  total: number
}) {
  const [copied, setCopied] = useState(false)
  const label = total > 1 ? `Source ${index + 1}` : 'Source'

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
      <summary>{label}</summary>
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
