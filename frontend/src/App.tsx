import { useEffect, useRef, useState } from 'react'
import { AnalyzeMeetingError, analyzeMeeting } from './api/meetings'
import { AnalysisReport } from './components/AnalysisReport'
import { ForgeClock } from './components/ForgeClock'
import { MeetingInput, MIN_TRANSCRIPT_CHARS } from './components/MeetingInput'
import { formatElapsed } from './formatElapsed'
import type { MeetingAnalysis } from './types/analysis'
import './App.css'

function meetingNameFromTranscript(transcript: string): string | null {
  const match = transcript.match(/^\s*Meeting:\s*(.+)$/im)
  const name = match?.[1]?.trim()
  return name || null
}

function App() {
  const [transcript, setTranscript] = useState('')
  const [analysis, setAnalysis] = useState<MeetingAnalysis | null>(null)
  const [meetingName, setMeetingName] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [elapsedMs, setElapsedMs] = useState(0)
  const [analysisDurationMs, setAnalysisDurationMs] = useState<number | null>(
    null,
  )
  const [failedDurationMs, setFailedDurationMs] = useState<number | null>(null)
  const startedAtRef = useRef<number | null>(null)

  useEffect(() => {
    if (!loading) {
      return
    }
    const tick = () => {
      const startedAt = startedAtRef.current
      if (startedAt == null) {
        return
      }
      setElapsedMs(Date.now() - startedAt)
    }
    tick()
    const id = window.setInterval(tick, 250)
    return () => window.clearInterval(id)
  }, [loading])

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

    const startedAt = Date.now()
    startedAtRef.current = startedAt
    setElapsedMs(0)
    setFailedDurationMs(null)
    setError(null)
    setLoading(true)
    try {
      const result = await analyzeMeeting(cleaned)
      setAnalysis(result)
      setMeetingName(meetingNameFromTranscript(cleaned))
      setAnalysisDurationMs(Date.now() - startedAt)
    } catch (caught) {
      setFailedDurationMs(Date.now() - startedAt)
      if (caught instanceof AnalyzeMeetingError) {
        setError(caught.message)
      } else {
        setError('Could not complete the extraction.')
      }
    } finally {
      setLoading(false)
    }
  }

  function handleReset() {
    if (analysis && !window.confirm('Clear the current engineering record?')) {
      return
    }
    setAnalysis(null)
    setMeetingName(null)
    setAnalysisDurationMs(null)
    setFailedDurationMs(null)
    setElapsedMs(0)
    startedAtRef.current = null
    setError(null)
    setTranscript('')
  }

  const showRecord = Boolean(analysis) && !loading
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
        <h1 className="brand">SpecForge</h1>
        <span className="brand-meta">Local</span>
      </header>

      <main>
        {loading ? <ForgeClock elapsedMs={elapsedMs} /> : null}

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

        {!loading && error && failedDurationMs != null && !analysis ? (
          <p className="timing-note" role="status">
            Halted at {formatElapsed(failedDurationMs)}
          </p>
        ) : null}

        {showRecord && analysis ? (
          <AnalysisReport
            meetingName={meetingName}
            analysis={analysis}
            durationMs={analysisDurationMs}
            onReset={handleReset}
          />
        ) : null}
      </main>
    </div>
  )
}

export default App
