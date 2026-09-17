import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnalyzeMeetingError, createImplementationPlan } from '../api/meetings'
import { formatElapsed } from '../formatElapsed'
import { buildTraceIndex } from '../trace'
import type { MeetingAnalysis } from '../types/analysis'
import type { ImplementationPlan } from '../types/plan'
import { AnalysisSummary, type RecordSection } from './AnalysisSummary'
import { DecisionList } from './DecisionList'
import { ForgeClock } from './ForgeClock'
import { ImplementationPlanView } from './ImplementationPlanView'
import { OpenQuestionList } from './OpenQuestionList'
import { RequirementList } from './RequirementList'
import { RiskList } from './RiskList'
import { TaskList } from './TaskList'
import { TraceIndexContext, TraceNavContext } from './TraceContext'

interface AnalysisReportProps {
  meetingName: string | null
  analysis: MeetingAnalysis
  durationMs: number | null
  onReset: () => void
}

export function AnalysisReport({
  meetingName,
  analysis,
  durationMs,
  onReset,
}: AnalysisReportProps) {
  const [section, setSection] = useState<RecordSection>('all')
  const [plan, setPlan] = useState<ImplementationPlan | null>(null)
  const [planning, setPlanning] = useState(false)
  const [planError, setPlanError] = useState<string | null>(null)
  const [planElapsedMs, setPlanElapsedMs] = useState(0)
  const [planDurationMs, setPlanDurationMs] = useState<number | null>(null)
  const [traceNonce, setTraceNonce] = useState(0)
  const startedAtRef = useRef<number | null>(null)
  const planRef = useRef<HTMLDivElement | null>(null)
  const highlightTimerRef = useRef<number | null>(null)
  const pendingTraceIdRef = useRef<string | null>(null)

  const traceIndex = useMemo(
    () => buildTraceIndex(analysis, plan),
    [analysis, plan],
  )

  const goToTrace = useCallback((id: string) => {
    pendingTraceIdRef.current = id
    if (!id.startsWith('STEP-')) {
      setSection('all')
    }
    setTraceNonce((value) => value + 1)
  }, [])

  const visible = useMemo(
    () => ({
      decisions: section === 'all' || section === 'decisions',
      requirements: section === 'all' || section === 'requirements',
      tasks: section === 'all' || section === 'tasks',
      risks: section === 'all' || section === 'risks',
      questions: section === 'all' || section === 'questions',
    }),
    [section],
  )

  useEffect(() => {
    if (!planning) {
      return
    }
    const tick = () => {
      const startedAt = startedAtRef.current
      if (startedAt == null) {
        return
      }
      setPlanElapsedMs(Date.now() - startedAt)
    }
    tick()
    const id = window.setInterval(tick, 250)
    return () => window.clearInterval(id)
  }, [planning])

  useEffect(() => {
    if (plan) {
      planRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [plan])

  useEffect(() => {
    const targetId = pendingTraceIdRef.current
    if (!targetId || traceNonce === 0) {
      return
    }
    const frame = window.requestAnimationFrame(() => {
      const escaped =
        typeof CSS !== 'undefined' && typeof CSS.escape === 'function'
          ? CSS.escape(targetId)
          : targetId
      const node = document.querySelector(`[data-trace-id="${escaped}"]`)
      if (!(node instanceof HTMLElement)) {
        return
      }
      const reduceMotion = window.matchMedia(
        '(prefers-reduced-motion: reduce)',
      ).matches
      node.scrollIntoView({
        behavior: reduceMotion ? 'auto' : 'smooth',
        block: 'center',
      })
      document.querySelectorAll('.is-trace-target').forEach((item) => {
        item.classList.remove('is-trace-target')
      })
      node.classList.add('is-trace-target')
      if (highlightTimerRef.current != null) {
        window.clearTimeout(highlightTimerRef.current)
      }
      highlightTimerRef.current = window.setTimeout(() => {
        node.classList.remove('is-trace-target')
        highlightTimerRef.current = null
      }, 1600)
    })
    return () => window.cancelAnimationFrame(frame)
  }, [traceNonce])

  useEffect(() => {
    return () => {
      if (highlightTimerRef.current != null) {
        window.clearTimeout(highlightTimerRef.current)
      }
    }
  }, [])

  async function handleGeneratePlan() {
    const startedAt = Date.now()
    startedAtRef.current = startedAt
    setPlanElapsedMs(0)
    setPlanError(null)
    setPlanning(true)
    try {
      const result = await createImplementationPlan(analysis, meetingName)
      setPlan(result)
      setPlanDurationMs(Date.now() - startedAt)
    } catch (caught) {
      if (caught instanceof AnalyzeMeetingError) {
        setPlanError(caught.message)
      } else {
        setPlanError('Could not derive an implementation plan.')
      }
    } finally {
      setPlanning(false)
    }
  }

  return (
    <TraceIndexContext.Provider value={traceIndex}>
      <TraceNavContext.Provider value={goToTrace}>
        <div className="report">
          <div className="report-toolbar">
            <AnalysisSummary
              meetingName={meetingName}
              analysis={analysis}
              durationMs={durationMs}
              section={section}
              onSectionChange={setSection}
            />
            <div className="report-actions">
              <button
                type="button"
                onClick={() => void handleGeneratePlan()}
                disabled={planning}
              >
                {planning
                  ? `Planning ${formatElapsed(planElapsedMs)}`
                  : plan
                    ? 'Regenerate plan'
                    : 'Generate Implementation Plan'}
              </button>
              <button
                type="button"
                className="button-secondary"
                onClick={onReset}
                disabled={planning}
              >
                New
              </button>
            </div>
          </div>

          {planning ? (
            <ForgeClock
              compact
              elapsedMs={planElapsedMs}
              message="Deriving the implementation plan from this record. Local inference — not a chat."
            />
          ) : null}

          {planError ? (
            <p className="form-error plan-error" role="alert">
              {planError}
            </p>
          ) : null}

          {visible.decisions &&
          (section !== 'all' || analysis.decisions.length > 0) ? (
            <DecisionList items={analysis.decisions} />
          ) : null}
          {visible.requirements &&
          (section !== 'all' || analysis.requirements.length > 0) ? (
            <RequirementList items={analysis.requirements} />
          ) : null}
          {visible.tasks && (section !== 'all' || analysis.tasks.length > 0) ? (
            <TaskList items={analysis.tasks} />
          ) : null}
          {visible.risks && (section !== 'all' || analysis.risks.length > 0) ? (
            <RiskList items={analysis.risks} />
          ) : null}
          {visible.questions &&
          (section !== 'all' || analysis.open_questions.length > 0) ? (
            <OpenQuestionList items={analysis.open_questions} />
          ) : null}

          {plan ? (
            <div ref={planRef}>
              <ImplementationPlanView plan={plan} durationMs={planDurationMs} />
            </div>
          ) : null}
        </div>
      </TraceNavContext.Provider>
    </TraceIndexContext.Provider>
  )
}
