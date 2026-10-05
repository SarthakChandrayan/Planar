import type { ReactNode } from 'react'
import { hue, initials } from '../people'
import { resolveTraceLinks } from '../trace'
import type { Decision, OpenQuestion, Requirement, Risk, Task } from '../types/analysis'
import { CalendarIcon, CheckIcon } from './icons'
import { Chip, EmptyState, EvidenceStrength, ItemCard, type ItemKind } from './ItemCard'
import { useTraceIndex } from './TraceContext'

export function Section({
  id,
  kind,
  title,
  count,
  description,
  children,
}: {
  id: string
  kind: ItemKind
  title: string
  count: number
  description?: string
  children: ReactNode
}) {
  return (
    <section className={`report-section kind-${kind}`} aria-labelledby={`${id}-heading`} id={id}>
      <div className="report-section-head">
        <h2 id={`${id}-heading`}>
          <span className="kind-dot" aria-hidden="true" />
          {title}
          <span className="count">{count}</span>
        </h2>
        {description ? <p className="report-section-desc">{description}</p> : null}
      </div>
      {children}
    </section>
  )
}

export function DecisionSection({ items }: { items: Decision[] }) {
  return (
    <Section id="decisions" kind="decision" title="Decisions" count={items.length}
      description="What the meeting agreed, chose, rejected, or ruled out.">
      {items.length === 0 ? (
        <EmptyState>No decisions were found in this meeting.</EmptyState>
      ) : (
        <div className="item-list">
          {items.map((item) => (
            <ItemCard key={item.id} id={item.id} kind="decision"
              meta={<EvidenceStrength value={item.confidence} />}
              evidence={[item.source_reference]}>
              <p className="item-text">{item.statement}</p>
            </ItemCard>
          ))}
        </div>
      )}
    </Section>
  )
}

export function RequirementSection({ items }: { items: Requirement[] }) {
  const index = useTraceIndex()
  return (
    <Section id="requirements" kind="requirement" title="Requirements" count={items.length}
      description="What the built system must do or satisfy.">
      {items.length === 0 ? (
        <EmptyState>No requirements were found in this meeting.</EmptyState>
      ) : (
        <div className="item-list">
          {items.map((item) => (
            <ItemCard key={item.id} id={item.id} kind="requirement"
              meta={<EvidenceStrength value={item.confidence} />}
              evidence={[item.source_reference]}
              links={[
                ...resolveTraceLinks(item.related_decision_ids, index),
                ...resolveTraceLinks(item.related_risk_ids, index),
              ]}>
              <p className="item-text">{item.statement}</p>
            </ItemCard>
          ))}
        </div>
      )}
    </Section>
  )
}

const PRIORITY_ORDER = { critical: 0, high: 1, medium: 2, low: 3 } as const

export function TaskCard({ item }: { item: Task }) {
  const index = useTraceIndex()
  const showDescription = item.description && item.description !== item.title
  return (
    <ItemCard id={item.id} kind="task"
      meta={
        <>
          <Chip tone={item.priority}>{item.priority}</Chip>
          {item.due ? <Chip icon={<CalendarIcon size={12} />}>Due {item.due}</Chip> : null}
        </>
      }
      evidence={item.source_references}
      links={resolveTraceLinks(item.related_requirement_ids, index)}>
      <h3 className="item-title">{item.title}</h3>
      {showDescription ? <p className="item-text muted">{item.description}</p> : null}
      {item.acceptance_criteria.length > 0 ? (
        <ul className="checklist" aria-label="Done when">
          {item.acceptance_criteria.map((criterion, i) => (
            <li key={`${i}-${criterion}`}>
              <span className="check-box" aria-hidden="true">
                <CheckIcon size={11} />
              </span>
              {criterion}
            </li>
          ))}
        </ul>
      ) : null}
    </ItemCard>
  )
}

export function TaskSection({ items }: { items: Task[] }) {
  const groups = new Map<string, Task[]>()
  for (const task of items) {
    const owner = task.owner?.trim() || ''
    groups.set(owner, [...(groups.get(owner) ?? []), task])
  }
  const owners = [...groups.keys()].sort((a, b) => {
    if (!a) return 1
    if (!b) return -1
    return (groups.get(b)?.length ?? 0) - (groups.get(a)?.length ?? 0) || a.localeCompare(b)
  })

  return (
    <Section id="tasks" kind="task" title="Tasks" count={items.length}
      description="Who does what, grouped by owner.">
      {items.length === 0 ? (
        <EmptyState>No action items were assigned in this meeting.</EmptyState>
      ) : (
        <div className="owner-groups">
          {owners.map((owner) => {
            const tasks = [...(groups.get(owner) ?? [])].sort(
              (a, b) => PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority],
            )
            return (
              <div key={owner || 'unassigned'} className="owner-group">
                <div className="owner-head">
                  {owner ? (
                    <span className="avatar" style={{ '--hue': hue(owner) } as React.CSSProperties}>
                      {initials(owner)}
                    </span>
                  ) : (
                    <span className="avatar avatar-empty">?</span>
                  )}
                  <span className="owner-name">{owner || 'Unassigned'}</span>
                  <span className="count">{tasks.length}</span>
                </div>
                <div className="item-list">
                  {tasks.map((task) => (
                    <TaskCard key={task.id} item={task} />
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Section>
  )
}

export function RiskSection({ items }: { items: Risk[] }) {
  const index = useTraceIndex()
  const sorted = [...items].sort((a, b) => PRIORITY_ORDER[a.severity] - PRIORITY_ORDER[b.severity])
  return (
    <Section id="risks" kind="risk" title="Risks" count={items.length}
      description="What could go wrong, most serious first.">
      {items.length === 0 ? (
        <EmptyState>No risks were raised in this meeting.</EmptyState>
      ) : (
        <div className="item-list">
          {sorted.map((item) => (
            <ItemCard key={item.id} id={item.id} kind="risk"
              meta={<Chip tone={item.severity}>{item.severity}</Chip>}
              evidence={[item.source_reference]}
              links={resolveTraceLinks(item.related_requirement_ids, index)}>
              <p className="item-text">{item.description}</p>
            </ItemCard>
          ))}
        </div>
      )}
    </Section>
  )
}

export function QuestionSection({ items }: { items: OpenQuestion[] }) {
  const index = useTraceIndex()
  return (
    <Section id="questions" kind="question" title="Open questions" count={items.length}
      description="Left unresolved; someone needs to answer these.">
      {items.length === 0 ? (
        <EmptyState>Nothing was left open.</EmptyState>
      ) : (
        <div className="item-list">
          {items.map((item) => (
            <ItemCard key={item.id} id={item.id} kind="question"
              evidence={[item.source_reference]}
              links={resolveTraceLinks(item.related_requirement_ids, index)}>
              <h3 className="item-title">{item.question}</h3>
              {item.context ? <p className="item-text muted">{item.context}</p> : null}
            </ItemCard>
          ))}
        </div>
      )}
    </Section>
  )
}
