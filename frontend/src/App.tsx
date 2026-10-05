import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from './api/client'
import {
  cancelRun,
  deleteRun,
  getReadiness,
  getRun,
  listRuns,
  reportUrl,
  startRun,
} from './api/runs'
import { AnalysisReport } from './components/AnalysisReport'
import { ForgeClock, type ForgeStage } from './components/ForgeClock'
import { MeetingInput, MIN_TRANSCRIPT_CHARS } from './components/MeetingInput'
import { RecentRuns } from './components/RecentRuns'
import { formatElapsed } from './formatElapsed'
import { isFinished, type Readiness, type Run, type RunSummary } from './types/run'
import './App.css'

const ACTIVE_RUN_KEY = 'planar.activeRun'
const POLL_MS = 2000

function readActiveRun(): string | null {
  try {
    return window.localStorage.getItem(ACTIVE_RUN_KEY)
  } catch {
    return null
  }
}

function writeActiveRun(id: string | null) {
  try {
    if (id) {
      window.localStorage.setItem(ACTIVE_RUN_KEY, id)
    } else {
      window.localStorage.removeItem(ACTIVE_RUN_KEY)
    }
  } catch {
    // Storage unavailable (private mode): resuming after refresh just won't work.
  }
}

function durationOf(run: Run): number | null {
  if (!run.started_at || !run.finished_at) {
    return null
  }
  return new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()
}

function messageFrom(caught: unknown, fallback: string): string {
  return caught instanceof ApiError ? caught.message : fallback
}

function App() {
  const [transcript, setTranscript] = useState('')
  const [activeRun, setActiveRun] = useState<Run | null>(null)
  const [result, setResult] = useState<Run | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [elapsedMs, setElapsedMs] = useState(0)
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [recent, setRecent] = useState<RunSummary[]>([])
  const startedAtRef = useRef<number | null>(null)

  const loading = activeRun != null

  const refreshRecent = useCallback(() => {
    listRuns()
      .then(setRecent)
      .catch(() => setRecent([]))
  }, [])

  const checkReadiness = useCallback(() => {
    void getReadiness().then(setReadiness)
  }, [])

  const finishRun = useCallback(
    (run: Run) => {
      setActiveRun(null)
      writeActiveRun(null)
      refreshRecent()
      if (run.status === 'succeeded' && run.analysis) {
        setResult(run)
        setTranscript(run.transcript)
        setError(null)
      } else if (run.status === 'failed') {
        setError(run.error ?? 'The run failed.')
        checkReadiness()
      } else if (run.status === 'cancelled') {
        setError('Run cancelled.')
      }
    },
    [checkReadiness, refreshRecent],
  )

  // Initial load: readiness, history, and resume a run left in progress.
  useEffect(() => {
    checkReadiness()
    refreshRecent()
    const resumeId = readActiveRun()
    if (resumeId) {
      getRun(resumeId)
        .then((run) => {
          if (isFinished(run.status)) {
            finishRun(run)
          } else {
            setTranscript(run.transcript)
            setActiveRun(run)
          }
        })
        .catch(() => writeActiveRun(null))
    }
  }, [checkReadiness, finishRun, refreshRecent])

  // Poll the active run until it finishes.
  const activeId = activeRun?.id ?? null
  useEffect(() => {
    if (!activeId) {
      return
    }
    const controller = new AbortController()
    let timer: number | undefined
    const poll = async () => {
      try {
        const run = await getRun(activeId, controller.signal)
        if (isFinished(run.status)) {
          finishRun(run)
          return
        }
        setActiveRun(run)
      } catch (caught) {
        if (controller.signal.aborted) {
          return
        }
        if (caught instanceof ApiError && caught.status === 404) {
          setActiveRun(null)
          writeActiveRun(null)
          setError('The run was lost. The server may have been reset; start it again.')
          return
        }
        // Transient (backend restarting): keep polling.
      }
      timer = window.setTimeout(poll, POLL_MS)
    }
    timer = window.setTimeout(poll, POLL_MS)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [activeId, finishRun])

  // Wall clock while a run is active, measured from the server's start time.
  useEffect(() => {
    if (!activeRun) {
      return
    }
    const anchor = activeRun.started_at ?? activeRun.created_at
    startedAtRef.current = new Date(anchor).getTime()
    const tick = () => {
      if (startedAtRef.current != null) {
        setElapsedMs(Date.now() - startedAtRef.current)
      }
    }
    tick()
    const id = window.setInterval(tick, 250)
    return () => window.clearInterval(id)
  }, [activeRun])

  async function handleAnalyze() {
    const cleaned = transcript.trim()
    if (!cleaned) {
      setError('Paste a transcript first.')
      return
    }
    if (cleaned.length < MIN_TRANSCRIPT_CHARS) {
      setError(`Need at least ${MIN_TRANSCRIPT_CHARS} characters.`)
      return
    }
    setError(null)
    setResult(null)
    try {
      const run = await startRun(cleaned)
      writeActiveRun(run.id)
      setElapsedMs(0)
      setActiveRun(run)
      refreshRecent()
    } catch (caught) {
      setError(messageFrom(caught, 'Could not start the analysis.'))
      checkReadiness()
    }
  }

  async function handleCancel() {
    if (!activeRun) {
      return
    }
    try {
      finishRun(await cancelRun(activeRun.id))
    } catch (caught) {
      setError(messageFrom(caught, 'Could not cancel the run.'))
    }
  }

  async function handleOpen(id: string) {
    try {
      const run = await getRun(id)
      if (run.status === 'succeeded' && run.analysis) {
        setResult(run)
        setTranscript(run.transcript)
        setError(null)
        window.scrollTo({ top: 0 })
      }
    } catch (caught) {
      setError(messageFrom(caught, 'Could not open that run.'))
    }
  }

  async function handleDelete(id: string) {
    if (!window.confirm('Delete this run?')) {
      return
    }
    try {
      await deleteRun(id)
      if (result?.id === id) {
        setResult(null)
      }
    } catch (caught) {
      setError(messageFrom(caught, 'Could not delete that run.'))
    }
    refreshRecent()
  }

  function handleReset() {
    if (result && !window.confirm('Clear the current engineering record?')) {
      return
    }
    setResult(null)
    setError(null)
    setTranscript('')
  }

  const stage: ForgeStage | null = activeRun
    ? {
        label:
          activeRun.status === 'queued'
            ? 'Queued: waiting for the model'
            : activeRun.progress.stage,
        step: activeRun.progress.step,
        total: activeRun.progress.total_steps,
        tokens: activeRun.progress.stage_tokens,
      }
    : null

  const showRecord = result?.analysis != null && !loading
  const input = (
    <MeetingInput
      value={transcript}
      disabled={loading}
      elapsedLabel={loading ? formatElapsed(elapsedMs) : null}
      error={loading ? null : error}
      onChange={(value) => {
        setTranscript(value)
        if (error) {
          setError(null)
        }
      }}
      onSubmit={() => {
        void handleAnalyze()
      }}
    />
  )

  return (
    <div className="app">
      <header className="site-header">
        <h1 className="brand">Planar</h1>
        <span className="brand-meta">
          Local{readiness?.model ? ` · ${readiness.model}` : ''}
        </span>
      </header>

      <main>
        {readiness?.status === 'unavailable' ? (
          <div className="readiness-banner" role="alert">
            <p>
              <strong>Model not ready.</strong> {readiness.detail}
            </p>
            <button type="button" className="button-ghost" onClick={checkReadiness}>
              Check again
            </button>
          </div>
        ) : null}

        {loading ? (
          <ForgeClock
            elapsedMs={elapsedMs}
            stage={stage}
            onCancel={() => void handleCancel()}
          />
        ) : null}

        {showRecord ? (
          <details className="source-drawer">
            <summary>
              Transcript · {transcript.length.toLocaleString()} chars
            </summary>
            {input}
          </details>
        ) : (
          input
        )}

        {showRecord && result?.analysis ? (
          <AnalysisReport
            key={result.id}
            meetingName={result.title}
            analysis={result.analysis}
            durationMs={durationOf(result)}
            initialPlan={result.plan}
            warnings={result.warnings}
            reportHref={reportUrl(result.id)}
            onReset={handleReset}
          />
        ) : null}

        {!loading && !showRecord ? (
          <RecentRuns
            runs={recent}
            onOpen={(id) => void handleOpen(id)}
            onDelete={(id) => void handleDelete(id)}
          />
        ) : null}
      </main>
    </div>
  )
}

export default App
