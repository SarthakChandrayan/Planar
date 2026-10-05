import type { Decision } from '../types/analysis'
import { ArtifactMeta, EmptySection } from './artifact'
import { Evidence } from './Evidence'

export function DecisionList({ items }: { items: Decision[] }) {
  return (
    <section className="section" aria-labelledby="decisions-heading">
      <div className="section-head">
        <h3 id="decisions-heading">Decisions</h3>
        <span>{items.length}</span>
      </div>
      {items.length === 0 ? (
        <EmptySection label="decisions" />
      ) : (
        <ul className="card-list">
          {items.map((item) => (
            <li key={item.id}>
              <article className="card" data-trace-id={item.id}>
                <ArtifactMeta id={item.id} confidence={item.confidence} />
                <p className="artifact-body">{item.statement}</p>
                <Evidence refs={[item.source_reference]} />
              </article>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
