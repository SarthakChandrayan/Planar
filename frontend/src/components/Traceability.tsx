import type { TraceEntry } from '../trace'
import { useTraceNav } from './TraceContext'

export function Traceability({ links }: { links: TraceEntry[] }) {
  const goTo = useTraceNav()
  if (links.length === 0) {
    return null
  }

  return (
    <div className="traceability">
      <p className="field-caption">Traceability</p>
      <ul className="trace-links">
        {links.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              className="trace-link"
              onClick={() => goTo(item.id)}
              aria-label={`Go to ${item.kindLabel} ${item.id}`}
            >
              <span className="trace-kind">{item.kindLabel}</span>
              <span className="artifact-id">{item.id}</span>
              <span className="trace-label">{item.label}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
