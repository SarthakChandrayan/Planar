import type { ReactNode } from 'react'
import type { SourceReference } from '../types/analysis'
import type { TraceEntry } from '../trace'
import { Evidence } from './Evidence'
import { Traceability } from './Traceability'

export type ItemKind = 'decision' | 'requirement' | 'task' | 'risk' | 'question' | 'step'

export function ItemCard({
  id,
  kind,
  meta,
  links = [],
  evidence = [],
  children,
}: {
  id: string
  kind: ItemKind
  meta?: ReactNode
  links?: TraceEntry[]
  evidence?: SourceReference[]
  children: ReactNode
}) {
  return (
    <article className={`item kind-${kind}`} data-trace-id={id}>
      <div className="item-head">
        <span className="item-id">{id}</span>
        {meta ? <span className="item-meta">{meta}</span> : null}
      </div>
      <div className="item-body">{children}</div>
      {links.length > 0 || evidence.length > 0 ? (
        <div className="item-foot">
          <Evidence refs={evidence} />
          <Traceability links={links} />
        </div>
      ) : null}
    </article>
  )
}

/** Small labelled pill: priority, severity, due date, evidence strength. */
export function Chip({
  tone = 'neutral',
  icon,
  children,
  title,
}: {
  tone?: 'neutral' | 'low' | 'medium' | 'high' | 'critical' | 'good' | 'weak'
  icon?: ReactNode
  children: ReactNode
  title?: string
}) {
  return (
    <span className={`chip tone-${tone}`} title={title}>
      {icon}
      {children}
    </span>
  )
}

/** Confidence is evidence strength, so say it in words. */
export function EvidenceStrength({ value }: { value: number }) {
  const label = value >= 0.85 ? 'Strong evidence' : value >= 0.7 ? 'Good evidence' : 'Weak evidence'
  const tone = value >= 0.7 ? 'good' : 'weak'
  return (
    <Chip tone={tone} title={`How well the cited lines back this up: ${Math.round(value * 100)}%`}>
      {label}
    </Chip>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="empty-state">{children}</p>
}
