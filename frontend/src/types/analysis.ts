export type Priority = 'low' | 'medium' | 'high' | 'critical'
export type Severity = 'low' | 'medium' | 'high' | 'critical'

export interface SourceReference {
  excerpt: string
  line_start?: number | null
  line_end?: number | null
  speaker?: string | null
}

export interface Decision {
  id: string
  statement: string
  confidence: number
  source_reference: SourceReference
}

export interface Requirement {
  id: string
  statement: string
  confidence: number
  source_reference: SourceReference
  related_decision_ids?: string[]
  related_risk_ids?: string[]
}

export interface Task {
  id: string
  title: string
  description: string
  priority: Priority
  owner?: string | null
  due?: string | null
  acceptance_criteria: string[]
  source_references: SourceReference[]
  related_requirement_ids?: string[]
}

export interface Risk {
  id: string
  description: string
  severity: Severity
  source_reference: SourceReference
  related_requirement_ids?: string[]
}

export interface OpenQuestion {
  id: string
  question: string
  context: string
  source_reference: SourceReference
  related_requirement_ids?: string[]
}

export interface MeetingAnalysis {
  decisions: Decision[]
  requirements: Requirement[]
  tasks: Task[]
  risks: Risk[]
  open_questions: OpenQuestion[]
}
