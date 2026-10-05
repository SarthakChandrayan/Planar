import { useCallback, useEffect, useState } from 'react'
import { ApiError } from './api/client'
import {
  cancelRun,
  deleteRun,
  getEstimate,
  getReadiness,
  getRun,
  getSample,
  listRuns,
  listSamples,
  startRun,
} from './api/runs'
import { Composer, MIN_TRANSCRIPT_CHARS } from './components/Composer'
import { Header } from './components/Header'
import { AlertIcon } from './components/icons'
import { RecentRuns } from './components/RecentRuns'
import { Report } from './components/Report'
import { RunProgress } from './components/RunProgress'
import { formatApprox } from './formatElapsed'
import {
  isFinished,
  type Estimate,
  type Readiness,
  type Run,
  type RunSummary,
  type SampleSummary,
} from './types/run'
import './App.css'

const ACTIVE_RUN_KEY = 'planar.activeRun'
const POLL_MS = 2000
const ESTIMATE_DEBOUNCE_MS = 400

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
  const [samples, setSamples] = useState<SampleSummary[]>([])
  const [loadingSample, setLoadingSample] = useState<string | null>(null)
  const [estimate, setEstimate] = useState<Estimate | null>(null)

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
        window.scrollTo({ top: 0 })
      } else if (run.status === 'failed') {
        setError(run.error ?? 'The analysis failed.')
        checkReadiness()
      } else if (run.status === 'cancelled') {
        setError('Analysis cancelled.')
      }
    },
    [checkReadiness, refreshRecent],
  )

  const watchRun = useCallback(
    (run: Run) => {
      if (isFinished(run.status)) {
        finishRun(run)
        return
      }
      writeActiveRun(run.id)
      setResult(null)
      setError(null)
      setTranscript(run.transcript)
      setActiveRun(run)
    },
    [finishRun],
  )

  // First load: model status, history, samples, and resume a run left in progress.
  useEffect(() => {
    checkReadiness()
    refreshRecent()
    listSamples()
      .then(setSamples)
      .catch(() => setSamples([]))
    const resumeId = readActiveRun()
    if (resumeId) {
      getRun(resumeId)
        .then(watchRun)
        .catch(() => writeActiveRun(null))
    }
  }, [checkReadiness, refreshRecent, watchRun])

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
          setError('The analysis was lost. The server may have been restarted; start it again.')
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
  const anchor = activeRun ? activeRun.started_at ?? activeRun.created_at : null
  useEffect(() => {
    if (!anchor) {
      return
    }
    const startedAt = new Date(anchor).getTime()
    const tick = () => setElapsedMs(Date.now() - startedAt)
    tick()
    const id = window.setInterval(tick, 500)
    return () => window.clearInterval(id)
  }, [anchor])

  // Expected duration for the pasted transcript, from this machine's past runs.
  const transcriptChars = transcript.trim().length
  const longEnough = transcriptChars >= MIN_TRANSCRIPT_CHARS
  useEffect(() => {
    if (!longEnough) {
      return
    }
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      getEstimate(transcriptChars, controller.signal)
        .then(setEstimate)
        .catch(() => setEstimate(null))
    }, ESTIMATE_DEBOUNCE_MS)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [transcriptChars, longEnough])

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
    try {
      const run = await startRun(cleaned)
      setElapsedMs(0)
      watchRun(run)
      refreshRecent()
      window.scrollTo({ top: 0 })
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
      setError(messageFrom(caught, 'Could not cancel the analysis.'))
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
      } else if (!isFinished(run.status)) {
        watchRun(run)
      }
    } catch (caught) {
      setError(messageFrom(caught, 'Could not open that analysis.'))
    }
  }

  async function handleDelete(id: string) {
    if (!window.confirm('Delete this analysis? This cannot be undone.')) {
      return
    }
    try {
      await deleteRun(id)
      if (result?.id === id) {
        setResult(null)
      }
    } catch (caught) {
      setError(messageFrom(caught, 'Could not delete that analysis.'))
    }
    refreshRecent()
  }

  async function handleLoadSample(id: string) {
    setLoadingSample(id)
    try {
      const sample = await getSample(id)
      setTranscript(sample.transcript)
      setError(null)
    } catch (caught) {
      setError(messageFrom(caught, 'Could not load that sample.'))
    } finally {
      setLoadingSample(null)
    }
  }

  function goHome() {
    if (activeRun) {
      return
    }
    setResult(null)
    setError(null)
    setTranscript('')
    refreshRecent()
    window.scrollTo({ top: 0 })
  }

  const estimateLabel =
    estimate && longEnough
      ? `${formatApprox(estimate.seconds)}${
          estimate.basis === 'default' ? ' (rough estimate)' : ' on this machine'
        }`
      : null

  let view
  if (activeRun) {
    view = (
      <RunProgress run={activeRun} elapsedMs={elapsedMs} onCancel={() => void handleCancel()} />
    )
  } else if (result?.analysis) {
    view = <Report key={result.id} run={result} onBack={goHome} />
  } else {
    view = (
      <>
        <div className="hero">
          <h1>Turn a meeting into a plan.</h1>
          <p>
            Paste a transcript. Planar pulls out the decisions, requirements, tasks, risks and
            open questions, links each one to the lines it came from, and drafts an
            implementation plan. Nothing leaves this computer.
          </p>
        </div>
        <Composer
          value={transcript}
          error={error}
          estimateLabel={estimateLabel}
          samples={samples}
          loadingSample={loadingSample}
          onChange={(value) => {
            setTranscript(value)
            if (error) {
              setError(null)
            }
          }}
          onSubmit={() => void handleAnalyze()}
          onLoadSample={(id) => void handleLoadSample(id)}
        />
        <RecentRuns
          runs={recent}
          onOpen={(id) => void handleOpen(id)}
          onDelete={(id) => void handleDelete(id)}
        />
      </>
    )
  }

  return (
    <div className="app">
      <Header readiness={readiness} onHome={goHome} />
      <main className="main">
        {readiness?.status === 'unavailable' ? (
          <div className="callout callout-danger" role="alert">
            <AlertIcon size={18} />
            <div>
              <p>
                <strong>The local model isn’t ready.</strong> {readiness.detail}
              </p>
              <button type="button" className="link-button" onClick={checkReadiness}>
                Check again
              </button>
            </div>
          </div>
        ) : null}
        {view}
      </main>
    </div>
  )
}

export default App
