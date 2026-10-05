import type { MeetingAnalysis } from '../types/analysis'
import type { ImplementationPlan } from '../types/plan'
import { request } from './client'

export function createImplementationPlan(
  analysis: MeetingAnalysis,
  title?: string | null,
): Promise<ImplementationPlan> {
  return request<ImplementationPlan>('/api/meetings/implementation-plan', {
    method: 'POST',
    body: { analysis, title: title?.trim() || undefined },
  })
}
