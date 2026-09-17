import type { MeetingAnalysis } from '../types/analysis'
import type { ImplementationPlan } from '../types/plan'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export class AnalyzeMeetingError extends Error {
  readonly status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'AnalyzeMeetingError'
    this.status = status
  }
}

interface FastApiErrorBody {
  detail?: unknown
}

function userMessageFromDetail(detail: unknown): string | null {
  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          const msg = (item as { msg?: unknown }).msg
          return typeof msg === 'string' ? msg : null
        }
        return null
      })
      .filter((msg): msg is string => Boolean(msg))
    if (messages.length > 0) {
      return messages.join(' ')
    }
  }
  return null
}

function messageForStatus(status: number, fallback: string): string {
  if (status === 422) {
    return fallback || 'The transcript could not be validated. Check that it is not empty.'
  }
  if (status === 502) {
    return fallback || 'The language model returned output that could not be used. Try again.'
  }
  if (status === 503) {
    return 'The analysis service is unavailable. Confirm the backend and Ollama are running.'
  }
  if (status === 504) {
    return 'The analysis timed out. Large meetings can take several minutes; try again.'
  }
  if (status >= 500) {
    return fallback || 'The server could not complete the analysis. Try again.'
  }
  return fallback || 'The analysis request was rejected.'
}

export async function analyzeMeeting(transcript: string): Promise<MeetingAnalysis> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/api/meetings/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript }),
    })
  } catch {
    throw new AnalyzeMeetingError(
      'Could not reach the SpecForge API. Start the backend, or check VITE_API_BASE_URL.',
    )
  }

  let payload: unknown = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    const detail =
      payload && typeof payload === 'object'
        ? userMessageFromDetail((payload as FastApiErrorBody).detail)
        : null
    throw new AnalyzeMeetingError(
      messageForStatus(response.status, detail ?? ''),
      response.status,
    )
  }

  return payload as MeetingAnalysis
}

export async function createImplementationPlan(
  analysis: MeetingAnalysis,
  title?: string | null,
): Promise<ImplementationPlan> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/api/meetings/implementation-plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        analysis,
        title: title?.trim() || undefined,
      }),
    })
  } catch {
    throw new AnalyzeMeetingError(
      'Could not reach the SpecForge API. Start the backend, or check VITE_API_BASE_URL.',
    )
  }

  let payload: unknown = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    const detail =
      payload && typeof payload === 'object'
        ? userMessageFromDetail((payload as FastApiErrorBody).detail)
        : null
    throw new AnalyzeMeetingError(
      messageForStatus(response.status, detail ?? ''),
      response.status,
    )
  }

  return payload as ImplementationPlan
}
