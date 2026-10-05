import { useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { hue, initials } from '../people'
import { buildPlanGraph, lineage, type MapColumn, type MapNode } from '../planGraph'
import type { MeetingAnalysis } from '../types/analysis'
import type { ImplementationPlan } from '../types/plan'
import { AlertIcon, CalendarIcon } from './icons'
import { useTraceNav } from './TraceContext'

const COLUMNS: { id: MapColumn; title: string; hint: string; kind: string }[] = [
  { id: 'decision', title: 'Decisions', hint: 'why', kind: 'decision' },
  { id: 'requirement', title: 'Requirements', hint: 'what', kind: 'requirement' },
  { id: 'step', title: 'Plan steps', hint: 'how', kind: 'step' },
  { id: 'owner', title: 'Owners', hint: 'who', kind: 'task' },
]

interface Path {
  key: string
  d: string
  from: string
  to: string
}

export function PlanMap({
  analysis,
  plan,
}: {
  analysis: MeetingAnalysis
  plan: ImplementationPlan
}) {
  const goTo = useTraceNav()
  const graph = useMemo(() => buildPlanGraph(analysis, plan), [analysis, plan])
  const [focus, setFocus] = useState<string | null>(null)
  const [paths, setPaths] = useState<Path[]>([])
  const canvasRef = useRef<HTMLDivElement | null>(null)
  const nodeRefs = useRef(new Map<string, HTMLElement>())

  const lit = useMemo(() => (focus ? lineage(focus, graph.edges) : null), [focus, graph.edges])

  // Draw a curve from the right edge of each source box to the left edge of its target.
  useLayoutEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) {
      return
    }
    const measure = () => {
      const origin = canvas.getBoundingClientRect()
      const next: Path[] = []
      for (const edge of graph.edges) {
        const a = nodeRefs.current.get(edge.from)?.getBoundingClientRect()
        const b = nodeRefs.current.get(edge.to)?.getBoundingClientRect()
        if (!a || !b) {
          continue
        }
        const x1 = a.right - origin.left
        const y1 = a.top + a.height / 2 - origin.top
        const x2 = b.left - origin.left
        const y2 = b.top + b.height / 2 - origin.top
        const bend = Math.max((x2 - x1) / 2, 24)
        next.push({
          key: `${edge.from}>${edge.to}`,
          from: edge.from,
          to: edge.to,
          d: `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`,
        })
      }
      setPaths(next)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(canvas)
    return () => observer.disconnect()
  }, [graph])

  const register = (key: string) => (el: HTMLElement | null) => {
    if (el) {
      nodeRefs.current.set(key, el)
    } else {
      nodeRefs.current.delete(key)
    }
  }

  const state = (key: string) => (lit ? (lit.has(key) ? ' is-lit' : ' is-dim') : '')

  return (
    <section className="plan-map" aria-labelledby="plan-map-heading">
      <div className="report-section-head">
        <h2 id="plan-map-heading">
          <span className="kind-dot map-dot" aria-hidden="true" />
          Plan map
        </h2>
        <p className="report-section-desc">
          Why each step exists and who owns it. Hover a box to trace its chain; click to open it.
        </p>
      </div>

      <div className="map-scroll">
        <div className="map-canvas" ref={canvasRef} onMouseLeave={() => setFocus(null)}>
          <svg className="map-edges" aria-hidden="true">
            {paths.map((path) => (
              <path
                key={path.key}
                d={path.d}
                className={
                  lit
                    ? lit.has(path.from) && lit.has(path.to)
                      ? 'edge is-lit'
                      : 'edge is-dim'
                    : 'edge'
                }
              />
            ))}
          </svg>

          {COLUMNS.map((column) => {
            const nodes = graph.columns[column.id]
            return (
              <div key={column.id} className={`map-column kind-${column.kind}`}>
                <div className="map-column-head">
                  <span className="kind-dot" aria-hidden="true" />
                  {column.title}
                  <span className="map-hint">{column.hint}</span>
                </div>
                {nodes.length === 0 ? (
                  <p className="map-empty">None linked</p>
                ) : (
                  nodes.map((node) => (
                    <button
                      key={node.key}
                      ref={register(node.key)}
                      type="button"
                      className={`map-node node-${node.column}${node.loose ? ' is-loose' : ''}${state(node.key)}`}
                      onMouseEnter={() => setFocus(node.key)}
                      onFocus={() => setFocus(node.key)}
                      onBlur={() => setFocus(null)}
                      onClick={() => goTo(node.traceId)}
                      title={node.loose ? `${node.title} (applies to the whole plan)` : node.title}
                    >
                      <NodeContent node={node} />
                    </button>
                  ))
                )}
              </div>
            )
          })}
        </div>
      </div>

      {graph.hiddenRequirements > 0 ? (
        <p className="map-footnote">
          {graph.hiddenRequirements} more{' '}
          {graph.hiddenRequirements === 1 ? 'requirement is' : 'requirements are'} not covered by
          any plan step. Faded decisions apply to the plan as a whole.
        </p>
      ) : (
        <p className="map-footnote">Faded decisions apply to the plan as a whole.</p>
      )}
    </section>
  )
}

function NodeContent({ node }: { node: MapNode }) {
  if (node.column === 'owner') {
    const unassigned = node.title === 'Unassigned'
    return (
      <span className="node-owner">
        <span
          className={unassigned ? 'avatar avatar-empty' : 'avatar'}
          style={unassigned ? undefined : ({ '--hue': hue(node.title) } as CSSProperties)}
        >
          {unassigned ? '?' : initials(node.title)}
        </span>
        <span>
          <span className="node-title">{node.title}</span>
          <span className="node-sub">
            {node.stepCount} {node.stepCount === 1 ? 'step' : 'steps'}
          </span>
        </span>
      </span>
    )
  }

  if (node.column === 'step') {
    return (
      <span className="node-step">
        <span className="node-num">{node.label}</span>
        <span className="node-main">
          <span className="node-title">{node.title}</span>
          {node.owners?.length || node.due?.length ? (
            <span className="node-tags">
              {node.owners?.map((owner) => (
                <span
                  key={owner}
                  className="avatar avatar-xs"
                  style={{ '--hue': hue(owner) } as CSSProperties}
                  title={owner}
                >
                  {initials(owner)}
                </span>
              ))}
              {node.due?.length ? (
                <span className="node-due">
                  <CalendarIcon size={11} />
                  {node.due[0]}
                </span>
              ) : null}
            </span>
          ) : null}
        </span>
      </span>
    )
  }

  return (
    <span className="node-main">
      <span className="node-id">
        {node.label}
        {node.riskCount ? (
          <span className="node-risk" title={`${node.riskCount} related risk(s)`}>
            <AlertIcon size={11} />
            {node.riskCount}
          </span>
        ) : null}
      </span>
      <span className="node-text">{node.title}</span>
    </span>
  )
}
