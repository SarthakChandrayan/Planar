import { formatApprox, formatClock, formatElapsed } from '../formatElapsed'
import type { Run } from '../types/run'
import { CheckIcon } from './icons'

const PASSES = ['Decisions', 'Requirements', 'Tasks', 'Risks & open questions']
const PLAN = 'Implementation plan'

/** The same stage order the backend runs: four passes per chunk, then the plan. */
function stageLabels(run: Run): string[] {
  const planSteps = run.include_plan ? 1 : 0
  const total = run.progress.total_steps
  const chunks = total > planSteps ? Math.max(1, Math.round((total - planSteps) / 4)) : 1
  const labels: string[] = []
  for (let chunk = 1; chunk <= chunks; chunk += 1) {
    for (const pass of PASSES) {
      labels.push(chunks > 1 ? `${pass} · part ${chunk}/${chunks}` : pass)
    }
  }
  if (run.include_plan) {
    labels.push(PLAN)
  }
  return labels
}

export function RunProgress({
  run,
  elapsedMs,
  onCancel,
}: {
  run: Run
  elapsedMs: number
  onCancel: () => void
}) {
  const labels = stageLabels(run)
  const queued = run.status === 'queued'
  const current = queued ? -1 : Math.max(run.progress.step, 1) - 1
  const timings = run.stage_timings ?? []
  const eta = run.progress.eta_seconds
  const done = Math.max(current, 0)
  const percent = labels.length ? Math.round((done / labels.length) * 100) : 0

  return (
    <section className="progress card" aria-labelledby="progress-title">
      <div className="progress-head">
        <div>
          <p className="eyebrow">{queued ? 'Queued' : 'Analyzing'}</p>
          <h2 id="progress-title" className="progress-title">
            {run.title}
          </h2>
        </div>
        <button type="button" className="button button-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>

      <div className="progress-figures">
        <div>
          <p className="figure" aria-live="polite">
            {eta != null ? formatApprox(eta) : 'Estimating…'}
          </p>
          <p className="figure-label">{eta != null ? 'left' : 'time left'}</p>
        </div>
        <div>
          <p className="figure figure-muted">
            <time dateTime={`PT${Math.floor(elapsedMs / 1000)}S`}>{formatClock(elapsedMs)}</time>
          </p>
          <p className="figure-label">elapsed</p>
        </div>
      </div>

      <div
        className="progress-bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-label="Stages completed"
      >
        <span style={{ width: `${Math.max(percent, 3)}%` }} />
      </div>

      <ol className="stages">
        {labels.map((label, index) => {
          const state = index < current ? 'done' : index === current ? 'active' : 'pending'
          const seconds = timings[index]?.seconds
          return (
            <li key={label} className={`stage is-${state}`}>
              <span className="stage-marker" aria-hidden="true">
                {state === 'done' ? <CheckIcon size={13} /> : index + 1}
              </span>
              <span className="stage-label">{label}</span>
              <span className="stage-meta">
                {state === 'done' && seconds != null ? formatElapsed(seconds * 1000) : null}
                {state === 'active'
                  ? run.progress.stage_tokens > 0
                    ? `writing · ${run.progress.stage_tokens} tokens`
                    : 'reading the transcript…'
                  : null}
              </span>
            </li>
          )
        })}
      </ol>

      <p className="progress-note">
        Everything runs on this computer. You can close this tab; the analysis keeps going and
        picks up here when you come back.
      </p>
    </section>
  )
}
