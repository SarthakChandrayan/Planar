import type { Readiness, Run, RunSummary } from '../types/run'
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

export function listRuns(): Promise<RunSummary[]> {
  return request<RunSummary[]>('/api/runs')
}

export function cancelRun(id: string): Promise<Run> {
  return request<Run>(`/api/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
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
