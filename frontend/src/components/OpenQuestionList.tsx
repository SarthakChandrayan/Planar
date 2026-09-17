import type { OpenQuestion } from '../types/analysis'
import { resolveTraceLinks } from '../trace'
import { ArtifactMeta, EmptySection } from './artifact'
import { Evidence } from './Evidence'
import { Traceability } from './Traceability'
import { useTraceIndex } from './TraceContext'

export function OpenQuestionList({ items }: { items: OpenQuestion[] }) {
  const traceIndex = useTraceIndex()

  return (
    <section className="section" aria-labelledby="questions-heading">
      <div className="section-head">
        <h3 id="questions-heading">Open</h3>
        <span>{items.length}</span>
      </div>
      {items.length === 0 ? (
        <EmptySection label="open questions" />
      ) : (
        <ul className="card-list">
          {items.map((item) => (
            <li key={item.id}>
              <article className="card" data-trace-id={item.id}>
                <ArtifactMeta id={item.id} />
                <h4 className="card-title">{item.question}</h4>
                <p className="artifact-body">{item.context}</p>
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
