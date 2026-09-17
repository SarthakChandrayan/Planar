function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`
}

export function EmptySection({ label }: { label: string }) {
  return <p className="empty-section">No {label}.</p>
}

export function ArtifactMeta({
  id,
  badge,
  badgeKind,
  confidence,
}: {
  id: string
  badge?: string
  badgeKind?: 'priority' | 'severity' | 'confidence'
  confidence?: number
}) {
  return (
    <div className="artifact-meta">
      <p className="artifact-id">{id}</p>
      {typeof confidence === 'number' ? (
        <span className="badge badge-confidence" title={`Confidence ${formatConfidence(confidence)}`}>
          <span className="meter" aria-hidden="true">
            <span style={{ width: `${Math.round(confidence * 100)}%` }} />
          </span>
          {formatConfidence(confidence)}
        </span>
      ) : badge ? (
        <span className={`badge badge-${badgeKind ?? 'plain'} badge-${badge}`}>
          {badge}
        </span>
      ) : null}
    </div>
  )
}
