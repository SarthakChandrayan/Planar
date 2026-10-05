import type { RunSummary } from '../types/run'

const STATUS_LABEL: Record<RunSummary['status'], string> = {
  queued: 'Queued',
  running: 'Running',
  succeeded: 'Done',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

function formatWhen(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) {
    return ''
  }
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function RecentRuns({
  runs,
  onOpen,
  onDelete,
}: {
  runs: RunSummary[]
  onOpen: (id: string) => void
  onDelete: (id: string) => void
}) {
  if (runs.length === 0) {
    return null
  }
  return (
    <section className="section recent-runs" aria-labelledby="recent-heading">
      <div className="section-head">
        <h3 id="recent-heading">Recent runs</h3>
        <span>{runs.length}</span>
      </div>
      <ul className="run-list">
        {runs.map((run) => (
          <li key={run.id}>
            <button
              type="button"
              className="run-open"
              onClick={() => onOpen(run.id)}
              disabled={run.status !== 'succeeded'}
              title={run.error ?? undefined}
            >
              <span className="run-title">{run.title}</span>
              <span className="run-meta">
                {formatWhen(run.created_at)} · {run.transcript_chars.toLocaleString()} chars
              </span>
              <span className={`badge badge-plain run-status run-status-${run.status}`}>
                {STATUS_LABEL[run.status]}
              </span>
            </button>
            <button
              type="button"
              className="button-ghost run-delete"
              aria-label={`Delete ${run.title}`}
              onClick={() => onDelete(run.id)}
              disabled={run.status === 'running' || run.status === 'queued'}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
