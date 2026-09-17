import type { Requirement } from '../types/analysis'
import { resolveTraceLinks } from '../trace'
import { ArtifactMeta, EmptySection } from './artifact'
import { Evidence } from './Evidence'
import { Traceability } from './Traceability'
import { useTraceIndex } from './TraceContext'

export function RequirementList({ items }: { items: Requirement[] }) {
  const traceIndex = useTraceIndex()

  return (
    <section className="section" aria-labelledby="requirements-heading">
      <div className="section-head">
        <h3 id="requirements-heading">Requirements</h3>
        <span>{items.length}</span>
      </div>
      {items.length === 0 ? (
        <EmptySection label="requirements" />
      ) : (
        <ul className="card-list">
          {items.map((item) => (
            <li key={item.id}>
              <article className="card" data-trace-id={item.id}>
                <ArtifactMeta id={item.id} confidence={item.confidence} />
                <p className="artifact-body">{item.statement}</p>
                <Traceability
                  links={[
                    ...resolveTraceLinks(item.related_decision_ids, traceIndex),
                    ...resolveTraceLinks(item.related_risk_ids, traceIndex),
                  ]}
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
