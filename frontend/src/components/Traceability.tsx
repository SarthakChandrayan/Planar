import type { TraceEntry } from '../trace'
import { useTraceNav } from './TraceContext'

/** Links to related items; clicking one jumps to it. */
export function Traceability({ links }: { links: TraceEntry[] }) {
  const goTo = useTraceNav()
  if (links.length === 0) {
    return null
  }

  return (
    <ul className="links" aria-label="Related items">
      {links.map((item) => (
        <li key={item.id}>
          <button
            type="button"
            className={`link-chip kind-${item.kind}`}
            onClick={() => goTo(item.id)}
            title={`${item.kindLabel} ${item.id}: ${item.label}`}
          >
            <span className="link-dot" aria-hidden="true" />
            <span className="link-id">{item.id}</span>
            <span className="link-label">{item.label}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}
