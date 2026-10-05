import type { MeetingAnalysis } from './analysis'
import type { ImplementationPlan } from './plan'

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface RunProgress {
  stage: string
  step: number
  total_steps: number
  stage_tokens: number
  total_tokens: number
}

export interface RunSummary {
  id: string
  title: string
  status: RunStatus
  created_at: string
  started_at: string | null
  finished_at: string | null
  transcript_chars: number
  progress: RunProgress
  error: string | null
  warnings: string[]
}

export interface Run extends RunSummary {
  transcript: string
  include_plan: boolean
  analysis: MeetingAnalysis | null
  plan: ImplementationPlan | null
}

export interface Readiness {
  status: 'ok' | 'unavailable'
  model: string
  detail?: string | null
}

export function isFinished(status: RunStatus): boolean {
  return status === 'succeeded' || status === 'failed' || status === 'cancelled'
}
