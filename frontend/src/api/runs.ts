import type {
  Estimate,
  Readiness,
  Run,
  RunSummary,
  Sample,
  SampleSummary,
} from '../types/run'
import { apiUrl, request } from './client'

export function startRun(transcript: string, title?: string | null): Promise<Run> {
  return request<Run>('/api/runs', {
    method: 'POST',
    body: { transcript, title: title?.trim() || undefined, include_plan: true },
  })
}

export function getRun(id: string, signal?: AbortSignal): Promise<Run> {
  return request<Run>(`/api/runs/${encodeURIComponent(id)}`, { signal })
}

export function getEstimate(chars: number, signal?: AbortSignal): Promise<Estimate> {
  return request<Estimate>(`/api/runs/estimate?chars=${chars}`, { signal })
}

export function listRuns(): Promise<RunSummary[]> {
  return request<RunSummary[]>('/api/runs')
}

export function cancelRun(id: string): Promise<Run> {
  return request<Run>(`/api/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
}

/** Start writing a new plan in the background; it replaces the saved plan when done. */
export function regeneratePlan(id: string): Promise<Run> {
  return request<Run>(`/api/runs/${encodeURIComponent(id)}/plan`, { method: 'POST' })
}

export function cancelPlan(id: string): Promise<Run> {
  return request<Run>(`/api/runs/${encodeURIComponent(id)}/plan/cancel`, { method: 'POST' })
}

export function deleteRun(id: string): Promise<void> {
  return request<void>(`/api/runs/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function reportUrl(id: string): string {
  return apiUrl(`/api/runs/${encodeURIComponent(id)}/report.md`)
}

export async function getReadiness(): Promise<Readiness> {
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

export function listSamples(): Promise<SampleSummary[]> {
  return request<SampleSummary[]>('/api/samples')
}

export function getSample(id: string): Promise<Sample> {
  return request<Sample>(`/api/samples/${encodeURIComponent(id)}`)
}

export async function getReportMarkdown(id: string): Promise<string> {
  const response = await fetch(reportUrl(id))
  if (!response.ok) {
    throw new Error(`Report unavailable (${response.status})`)
  }
  return response.text()
}
