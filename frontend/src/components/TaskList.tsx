import type { Task } from '../types/analysis'
import { resolveTraceLinks } from '../trace'
import { ArtifactMeta, EmptySection } from './artifact'
import { Evidence } from './Evidence'
import { Traceability } from './Traceability'
import { useTraceIndex } from './TraceContext'

export function TaskList({ items }: { items: Task[] }) {
  const traceIndex = useTraceIndex()

  return (
    <section className="section" aria-labelledby="tasks-heading">
      <div className="section-head">
        <h3 id="tasks-heading">Tasks</h3>
        <span>{items.length}</span>
      </div>
      {items.length === 0 ? (
        <EmptySection label="tasks" />
      ) : (
        <ul className="card-list">
          {items.map((item) => (
            <li key={item.id}>
              <article className="card" data-trace-id={item.id}>
                <ArtifactMeta
                  id={item.id}
                  badge={item.priority}
                  badgeKind="priority"
                />
                <h4 className="card-title">{item.title}</h4>
                <p className="artifact-body">{item.description}</p>
                {item.acceptance_criteria.length > 0 ? (
                  <div>
                    <p className="field-caption">Done when</p>
                    <ul className="criteria">
                      {item.acceptance_criteria.map((criterion, index) => (
                        <li key={`${index}-${criterion}`}>{criterion}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <Traceability
                  links={resolveTraceLinks(item.related_requirement_ids, traceIndex)}
                />
                <Evidence
                  excerpts={item.source_references.map((ref) => ref.excerpt)}
                />
              </article>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
