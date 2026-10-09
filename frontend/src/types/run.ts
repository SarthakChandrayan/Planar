import type { MeetingAnalysis } from './analysis'
import type { ImplementationPlan } from './plan'

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface RunProgress {
  stage: string
  step: number
  total_steps: number
  stage_tokens: number
  total_tokens: number
  eta_seconds: number | null
}

export interface Estimate {
  seconds: number
  chunks: number
  basis: 'default' | 'this machine'
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

export interface StageTiming {
  stage: string
  seconds: number
  kilotokens: number
}

export interface PlanJob {
  status: 'queued' | 'running' | 'failed'
  version: number
  requested_at: string
  started_at: string | null
  tokens: number
  eta_seconds: number | null
  error: string | null
}

export interface Run extends RunSummary {
  transcript: string
  include_plan: boolean
  analysis: MeetingAnalysis | null
  plan: ImplementationPlan | null
  stage_timings?: StageTiming[]
  plan_version?: number
  plan_job?: PlanJob | null
}

export interface SampleSummary {
  id: string
  title: string
  words: number
}

export interface Sample extends SampleSummary {
  transcript: string
}

export interface Readiness {
  status: 'ok' | 'unavailable' | 'demo'
  model: string
  detail?: string | null
}

export function isFinished(status: RunStatus): boolean {
  return status === 'succeeded' || status === 'failed' || status === 'cancelled'
}
