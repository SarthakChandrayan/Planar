import type { Risk } from '../types/analysis'
import { resolveTraceLinks } from '../trace'
import { ArtifactMeta, EmptySection } from './artifact'
import { Evidence } from './Evidence'
import { Traceability } from './Traceability'
import { useTraceIndex } from './TraceContext'

export function RiskList({ items }: { items: Risk[] }) {
  const traceIndex = useTraceIndex()

  return (
    <section className="section" aria-labelledby="risks-heading">
      <div className="section-head">
        <h3 id="risks-heading">Risks</h3>
        <span>{items.length}</span>
      </div>
      {items.length === 0 ? (
        <EmptySection label="risks" />
      ) : (
        <ul className="card-list">
          {items.map((item) => (
            <li key={item.id}>
              <article
                className={`card card-risk is-${item.severity}`}
                data-trace-id={item.id}
              >
                <ArtifactMeta
                  id={item.id}
                  badge={item.severity}
                  badgeKind="severity"
                />
                <p className="artifact-body">{item.description}</p>
                <Traceability
                  links={resolveTraceLinks(item.related_requirement_ids, traceIndex)}
                />
                <Evidence excerpts={[item.source_reference.excerpt]} />
              </article>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
