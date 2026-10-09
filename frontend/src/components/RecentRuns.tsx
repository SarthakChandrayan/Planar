import { formatElapsed } from '../formatElapsed'
import type { RunSummary } from '../types/run'
import { TrashIcon } from './icons'

const STATUS_LABEL: Record<RunSummary['status'], string> = {
  queued: 'Queued',
  running: 'Running',
  succeeded: 'Ready',
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

function duration(run: RunSummary): string | null {
  if (!run.started_at || !run.finished_at) {
    return null
  }
  return formatElapsed(new Date(run.finished_at).getTime() - new Date(run.started_at).getTime())
}

export function RecentRuns({
  runs,
  onOpen,
  onDelete,
  title = 'Recent analyses',
}: {
  runs: RunSummary[]
  onOpen: (id: string) => void
  onDelete?: (id: string) => void
  title?: string
}) {
  if (runs.length === 0) {
    return null
  }
  return (
    <section className="recent" aria-labelledby="recent-heading">
      <h2 id="recent-heading" className="section-title">
        {title}
      </h2>
      <ul className="run-grid">
        {runs.map((run) => {
          const active = run.status === 'running' || run.status === 'queued'
          const openable = active || run.status === 'succeeded'
          const took = duration(run)
          return (
            <li key={run.id} className="run-card card">
              <button
                type="button"
                className="run-open"
                onClick={() => onOpen(run.id)}
                disabled={!openable}
                title={run.error ?? undefined}
              >
                <span className={`run-status is-${run.status}`}>
                  <span className="status-dot" aria-hidden="true" />
                  {STATUS_LABEL[run.status]}
                </span>
                <span className="run-title">{run.title}</span>
                <span className="run-meta">
                  {onDelete ? formatWhen(run.created_at) : `${Math.round(run.transcript_chars / 1000)}k characters`}
                  {took ? ` · took ${took}` : null}
                  {active ? ' · click to watch' : null}
                </span>
                {run.status === 'failed' && run.error ? (
                  <span className="run-error">{run.error}</span>
                ) : null}
              </button>
              {onDelete ? (
              <button
                type="button"
                className="icon-button run-delete"
                aria-label={`Delete ${run.title}`}
                title="Delete"
                onClick={() => onDelete(run.id)}
                disabled={active}
              >
                <TrashIcon size={15} />
              </button>
              ) : null}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
