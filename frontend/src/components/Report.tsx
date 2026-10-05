import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { createImplementationPlan } from '../api/meetings'
import { getReportMarkdown, reportUrl } from '../api/runs'
import { formatElapsed } from '../formatElapsed'
import { buildTraceIndex } from '../trace'
import type { ImplementationPlan } from '../types/plan'
import type { Run } from '../types/run'
import {
  AlertIcon,
  ArrowLeftIcon,
  CheckIcon,
  CopyIcon,
  DownloadIcon,
  RefreshIcon,
} from './icons'
import { PlanMap } from './PlanMap'
import { PlanView } from './PlanView'
import {
  DecisionSection,
  QuestionSection,
  RequirementSection,
  RiskSection,
  TaskSection,
} from './sections'
import { TraceIndexContext, TraceNavContext } from './TraceContext'

type Tab = 'overview' | 'map' | 'decisions' | 'requirements' | 'tasks' | 'risks' | 'questions' | 'plan'

const TAB_FOR_PREFIX: Record<string, Tab> = {
  DEC: 'decisions',
  REQ: 'requirements',
  TSK: 'tasks',
  RSK: 'risks',
  OQ: 'questions',
  STEP: 'plan',
}

function durationOf(run: Run): number | null {
  if (!run.started_at || !run.finished_at) {
    return null
  }
  return new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()
}

function formatDate(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export function Report({ run, onBack }: { run: Run; onBack: () => void }) {
  const analysis = run.analysis!
  const [tab, setTab] = useState<Tab>('overview')
  const [plan, setPlan] = useState<ImplementationPlan | null>(run.plan)
  const [planning, setPlanning] = useState(false)
  const [planError, setPlanError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [traceNonce, setTraceNonce] = useState(0)
  const pendingTraceIdRef = useRef<string | null>(null)
  const highlightTimerRef = useRef<number | null>(null)

  const traceIndex = useMemo(() => buildTraceIndex(analysis, plan), [analysis, plan])

  const goToTrace = useCallback((id: string) => {
    pendingTraceIdRef.current = id
    const target = TAB_FOR_PREFIX[id.split('-')[0]]
    setTab((current) => (current === 'overview' || !target ? current : target))
    setTraceNonce((value) => value + 1)
  }, [])

  // Scroll to and briefly highlight the item a link pointed at.
  useEffect(() => {
    const targetId = pendingTraceIdRef.current
    if (!targetId || traceNonce === 0) {
      return
    }
    const frame = window.requestAnimationFrame(() => {
      const node = document.querySelector(`[data-trace-id="${CSS.escape(targetId)}"]`)
      if (!(node instanceof HTMLElement)) {
        return
      }
      const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      node.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' })
      document.querySelectorAll('.is-highlighted').forEach((item) => {
        item.classList.remove('is-highlighted')
      })
      node.classList.add('is-highlighted')
      if (highlightTimerRef.current != null) {
        window.clearTimeout(highlightTimerRef.current)
      }
      highlightTimerRef.current = window.setTimeout(() => {
        node.classList.remove('is-highlighted')
        highlightTimerRef.current = null
      }, 1800)
    })
    return () => window.cancelAnimationFrame(frame)
  }, [traceNonce, tab])

  useEffect(
    () => () => {
      if (highlightTimerRef.current != null) {
        window.clearTimeout(highlightTimerRef.current)
      }
    },
    [],
  )

  async function regeneratePlan() {
    setPlanError(null)
    setPlanning(true)
    try {
      setPlan(await createImplementationPlan(analysis, run.title))
      setTab('plan')
    } catch (caught) {
      setPlanError(caught instanceof ApiError ? caught.message : 'Could not regenerate the plan.')
    } finally {
      setPlanning(false)
    }
  }

  async function copyMarkdown() {
    try {
      await navigator.clipboard.writeText(await getReportMarkdown(run.id))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: 'overview', label: 'Overview' },
    ...(plan && plan.steps.length > 0 ? [{ id: 'map' as const, label: 'Plan map' }] : []),
    { id: 'decisions', label: 'Decisions', count: analysis.decisions.length },
    { id: 'requirements', label: 'Requirements', count: analysis.requirements.length },
    { id: 'tasks', label: 'Tasks', count: analysis.tasks.length },
    { id: 'risks', label: 'Risks', count: analysis.risks.length },
    { id: 'questions', label: 'Open questions', count: analysis.open_questions.length },
    { id: 'plan', label: 'Plan', count: plan?.steps.length ?? 0 },
  ]
  const show = (id: Tab) => tab === 'overview' || tab === id
  const took = durationOf(run)
  const owners = new Set(analysis.tasks.map((t) => t.owner).filter(Boolean)).size

  return (
    <TraceIndexContext.Provider value={traceIndex}>
      <TraceNavContext.Provider value={goToTrace}>
        <div className="report">
          <div className="report-top">
            <button type="button" className="button button-ghost" onClick={onBack}>
              <ArrowLeftIcon size={16} />
              New analysis
            </button>
            <div className="report-actions">
              <button type="button" className="button button-ghost" onClick={() => void copyMarkdown()}>
                {copied ? <CheckIcon size={16} /> : <CopyIcon size={16} />}
                {copied ? 'Copied' : 'Copy Markdown'}
              </button>
              <a className="button button-ghost" href={reportUrl(run.id)} download>
                <DownloadIcon size={16} />
                Download .md
              </a>
              <button
                type="button"
                className="button button-ghost"
                onClick={() => void regeneratePlan()}
                disabled={planning}
                title="Ask the model for a new implementation plan"
              >
                <RefreshIcon size={16} className={planning ? 'spin' : undefined} />
                {planning ? 'Regenerating plan…' : 'Regenerate plan'}
              </button>
            </div>
          </div>

          <header className="report-header">
            <p className="eyebrow">Meeting record</p>
            <h1 className="report-title">{run.title}</h1>
            <p className="report-meta">
              {formatDate(run.created_at)}
              {took != null ? ` · analyzed in ${formatElapsed(took)}` : null}
              {owners > 0 ? ` · ${owners} ${owners === 1 ? 'owner' : 'owners'}` : null}
            </p>
          </header>

          {run.warnings.length > 0 || planError ? (
            <div className="callout" role="note">
              <AlertIcon size={18} />
              <ul>
                {planError ? <li>{planError}</li> : null}
                {run.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <nav className="tabs" aria-label="Report sections">
            {tabs.map((item) => (
              <button
                key={item.id}
                type="button"
                className={tab === item.id ? 'tab is-active' : 'tab'}
                aria-current={tab === item.id ? 'page' : undefined}
                onClick={() => setTab(item.id)}
              >
                {item.label}
                {item.count != null ? <span className="tab-count">{item.count}</span> : null}
              </button>
            ))}
          </nav>

          {tab === 'overview' ? (
            <div className="stats">
              {tabs.filter((item) => item.count != null).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`stat kind-${item.id === 'plan' ? 'step' : item.id.replace(/s$/, '')}`}
                  onClick={() => setTab(item.id)}
                >
                  <span className="stat-value">{item.count}</span>
                  <span className="stat-label">{item.id === 'plan' ? 'Plan steps' : item.label}</span>
                </button>
              ))}
            </div>
          ) : null}

          <div className="report-body">
            {show('map') && plan && plan.steps.length > 0 ? (
              <PlanMap analysis={analysis} plan={plan} />
            ) : null}
            {show('decisions') ? <DecisionSection items={analysis.decisions} /> : null}
            {show('requirements') ? <RequirementSection items={analysis.requirements} /> : null}
            {show('tasks') ? <TaskSection items={analysis.tasks} /> : null}
            {show('risks') ? <RiskSection items={analysis.risks} /> : null}
            {show('questions') ? <QuestionSection items={analysis.open_questions} /> : null}
            {show('plan') && plan ? <PlanView plan={plan} /> : null}
          </div>
        </div>
      </TraceNavContext.Provider>
    </TraceIndexContext.Provider>
  )
}
