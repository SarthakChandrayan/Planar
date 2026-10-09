import type {
  Estimate,
  Readiness,
  Run,
  RunSummary,
  Sample,
  SampleSummary,
} from '../types/run'
import { DEMO, DEMO_MODEL, demoJson, demoUrl } from '../demo'
import { ApiError, apiUrl, request } from './client'

const DEMO_ONLY =
  'This is a demo with recorded runs. Analysing a new meeting needs the local model: see "Run it yourself" on the Planar page.'

function demoRefusal<T>(): Promise<T> {
  return Promise.reject(new ApiError(DEMO_ONLY))
}

export function startRun(transcript: string, title?: string | null): Promise<Run> {
  if (DEMO) return demoRefusal()
  return request<Run>('/api/runs', {
    method: 'POST',
    body: { transcript, title: title?.trim() || undefined, include_plan: true },
  })
}

export function getRun(id: string, signal?: AbortSignal): Promise<Run> {
  if (DEMO) return demoJson<Run>(`runs/${encodeURIComponent(id)}.json`)
  return request<Run>(`/api/runs/${encodeURIComponent(id)}`, { signal })
}

export function getEstimate(chars: number, signal?: AbortSignal): Promise<Estimate> {
  if (DEMO) return demoRefusal()
  return request<Estimate>(`/api/runs/estimate?chars=${chars}`, { signal })
}

export function listRuns(): Promise<RunSummary[]> {
  if (DEMO) return demoJson<RunSummary[]>('runs.json')
  return request<RunSummary[]>('/api/runs')
}

export function cancelRun(id: string): Promise<Run> {
  if (DEMO) return demoRefusal()
  return request<Run>(`/api/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
}

/** Start writing a new plan in the background; it replaces the saved plan when done. */
export function regeneratePlan(id: string): Promise<Run> {
  if (DEMO) return demoRefusal()
  return request<Run>(`/api/runs/${encodeURIComponent(id)}/plan`, { method: 'POST' })
}

export function cancelPlan(id: string): Promise<Run> {
  if (DEMO) return demoRefusal()
  return request<Run>(`/api/runs/${encodeURIComponent(id)}/plan/cancel`, { method: 'POST' })
}

export function deleteRun(id: string): Promise<void> {
  if (DEMO) return demoRefusal()
  return request<void>(`/api/runs/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function reportUrl(id: string): string {
  if (DEMO) return demoUrl(`reports/${encodeURIComponent(id)}.md`)
  return apiUrl(`/api/runs/${encodeURIComponent(id)}/report.md`)
}

export async function getReadiness(): Promise<Readiness> {
  if (DEMO) return { status: 'demo', model: DEMO_MODEL }
  // 503 still carries a Readiness body explaining what is wrong.
  try {
    const response = await fetch(apiUrl('/health/ready'))
    return (await response.json()) as Readiness
  } catch {
    return {
      status: 'unavailable',
      model: '',
      detail: 'The Planar backend is not running. Start it with: uvicorn app.main:app',
    }
  }
}

/** Ask the backend to load the model now; ignored if it can't. */
export function warmUp(): void {
  if (DEMO) return
  void request('/api/warmup', { method: 'POST' }).catch(() => undefined)
}

export function listSamples(): Promise<SampleSummary[]> {
  if (DEMO) return Promise.resolve([])
  return request<SampleSummary[]>('/api/samples')
}

export function getSample(id: string): Promise<Sample> {
  if (DEMO) return demoRefusal()
  return request<Sample>(`/api/samples/${encodeURIComponent(id)}`)
}

export async function getReportMarkdown(id: string): Promise<string> {
  const response = await fetch(reportUrl(id))
  if (!response.ok) {
    throw new Error(`Report unavailable (${response.status})`)
  }
  return response.text()
}
