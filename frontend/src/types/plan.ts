import type { OpenQuestion, Risk, SourceReference } from './analysis'

export interface ImplementationPlanStep {
  id: string
  title: string
  description: string
  related_decision_ids?: string[]
  related_requirement_ids?: string[]
  related_task_ids?: string[]
  evidence?: SourceReference[]
  when?: string | null
}

export interface ImplementationPlan {
  id: string
  title: string
  summary: string
  steps: ImplementationPlanStep[]
  acceptance_criteria: string[]
  risks: Risk[]
  open_questions: OpenQuestion[]
}
