import type { ReactNode } from 'react'
import { resolveTraceLinks } from '../trace'
import type { ImplementationPlan } from '../types/plan'
import { CalendarIcon, CheckIcon } from './icons'
import { Chip, EmptyState } from './ItemCard'
import { Evidence } from './Evidence'
import { Section } from './sections'
import { Traceability } from './Traceability'
import { useTraceIndex } from './TraceContext'

/** A phase heading ("Before October 28") where the plan's timeframe changes. */
function PhaseAndStep({ phase, children }: { phase: string | null; children: ReactNode }) {
  return (
    <>
      {phase ? (
        <li className="timeline-phase" aria-hidden="true">
          {phase}
        </li>
      ) : null}
      {children}
    </>
  )
}

export function PlanView({ plan }: { plan: ImplementationPlan }) {
  const index = useTraceIndex()
  return (
    <Section id="plan" kind="step" title="Implementation plan" count={plan.steps.length}>
      <p className="plan-summary">{plan.summary}</p>
      {plan.steps.length === 0 ? (
        <EmptyState>No implementation steps.</EmptyState>
      ) : (
        <ol className="timeline">
          {plan.steps.map((step, i) => (
            <PhaseAndStep
              key={step.id}
              phase={step.when && step.when !== plan.steps[i - 1]?.when ? step.when : null}
            >
              <li className="timeline-step item kind-step" data-trace-id={step.id}>
                <span className="timeline-num" aria-hidden="true">
                  {i + 1}
                </span>
                <div className="timeline-body">
                  <div className="item-head">
                    <span className="item-id">{step.id}</span>
                    {step.when ? (
                      <span className="item-meta">
                        <Chip icon={<CalendarIcon size={12} />}>{step.when}</Chip>
                      </span>
                    ) : null}
                  </div>
                  <h3 className="item-title">{step.title}</h3>
                  <p className="item-text muted">{step.description}</p>
                  <div className="item-foot">
                    <Evidence refs={step.evidence ?? []} />
                    <Traceability
                      links={[
                        ...resolveTraceLinks(step.related_decision_ids, index),
                        ...resolveTraceLinks(step.related_requirement_ids, index),
                        ...resolveTraceLinks(step.related_task_ids, index),
                      ]}
                    />
                  </div>
                </div>
              </li>
            </PhaseAndStep>
          ))}
        </ol>
      )}
      {plan.acceptance_criteria.length > 0 ? (
        <div className="done-when card">
          <h3 className="done-when-title">The plan is done when (suggested)</h3>
          <ul className="checklist">
            {plan.acceptance_criteria.map((criterion, i) => (
              <li key={`${i}-${criterion}`}>
                <span className="check-box" aria-hidden="true">
                  <CheckIcon size={11} />
                </span>
                {criterion}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Section>
  )
}
