import type { ImplementationPlan } from '../types/plan'
import { formatElapsed } from '../formatElapsed'
import { resolveTraceLinks } from '../trace'
import { ArtifactMeta, EmptySection } from './artifact'
import { Evidence } from './Evidence'
import { OpenQuestionList } from './OpenQuestionList'
import { RiskList } from './RiskList'
import { Traceability } from './Traceability'
import { useTraceIndex } from './TraceContext'

interface ImplementationPlanViewProps {
  plan: ImplementationPlan
  durationMs: number | null
}

export function ImplementationPlanView({
  plan,
  durationMs,
}: ImplementationPlanViewProps) {
  const traceIndex = useTraceIndex()

  return (
    <section className="plan" aria-labelledby="plan-heading">
      <p className="eyebrow">Implementation plan</p>
      <h2 id="plan-heading">{plan.title}</h2>
      <p className="artifact-id">{plan.id}</p>
      {durationMs != null ? (
        <p className="timing-note">{formatElapsed(durationMs)}</p>
      ) : null}
      <p className="artifact-body plan-summary">{plan.summary}</p>

      <div className="section">
        <div className="section-head">
          <h3>Steps</h3>
          <span>{plan.steps.length}</span>
        </div>
        {plan.steps.length === 0 ? (
          <EmptySection label="steps" />
        ) : (
          <ul className="card-list">
            {plan.steps.map((step) => (
              <li key={step.id}>
                <article className="card" data-trace-id={step.id}>
                  <ArtifactMeta id={step.id} />
                  <h4 className="card-title">{step.title}</h4>
                  <p className="artifact-body">{step.description}</p>
                  <Traceability
                    links={[
                      ...resolveTraceLinks(step.related_requirement_ids, traceIndex),
                      ...resolveTraceLinks(step.related_task_ids, traceIndex),
                    ]}
                  />
                  <Evidence refs={step.evidence ?? []} />
                </article>
              </li>
            ))}
          </ul>
        )}
      </div>

      {plan.acceptance_criteria.length > 0 ? (
        <div className="section">
          <div className="section-head">
            <h3>Done when</h3>
            <span>{plan.acceptance_criteria.length}</span>
          </div>
          <ul className="criteria">
            {plan.acceptance_criteria.map((item, index) => (
              <li key={`${index}-${item}`}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {plan.risks.length > 0 ? <RiskList items={plan.risks} /> : null}
      {plan.open_questions.length > 0 ? (
        <OpenQuestionList items={plan.open_questions} />
      ) : null}
    </section>
  )
}
