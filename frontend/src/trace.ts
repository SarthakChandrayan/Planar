import type { MeetingAnalysis } from './types/analysis'
import type { ImplementationPlan } from './types/plan'

export type TraceKind =
  | 'decision'
  | 'requirement'
  | 'task'
  | 'risk'
  | 'question'
  | 'step'

export interface TraceEntry {
  id: string
  kind: TraceKind
  kindLabel: string
  label: string
}

const KIND_LABEL: Record<TraceKind, string> = {
  decision: 'Decision',
  requirement: 'Requirement',
  task: 'Task',
  risk: 'Risk',
  question: 'Open question',
  step: 'Step',
}

export function presentIds(ids: string[] | null | undefined): string[] {
  if (!Array.isArray(ids)) {
    return []
  }
  const seen = new Set<string>()
  const out: string[] = []
  for (const raw of ids) {
    if (typeof raw !== 'string') {
      continue
    }
    const id = raw.trim()
    if (!id || seen.has(id)) {
      continue
    }
    seen.add(id)
    out.push(id)
  }
  return out
}

export function buildTraceIndex(
  analysis: MeetingAnalysis,
  plan?: ImplementationPlan | null,
): Map<string, TraceEntry> {
  const index = new Map<string, TraceEntry>()

  function add(id: string, kind: TraceKind, label: string) {
    const key = id.trim()
    if (!key || index.has(key)) {
      return
    }
    index.set(key, {
      id: key,
      kind,
      kindLabel: KIND_LABEL[kind],
      label: label.trim(),
    })
  }

  for (const item of analysis.decisions) {
    add(item.id, 'decision', item.statement)
  }
  for (const item of analysis.requirements) {
    add(item.id, 'requirement', item.statement)
  }
  for (const item of analysis.tasks) {
    add(item.id, 'task', item.title)
  }
  for (const item of analysis.risks) {
    add(item.id, 'risk', item.description)
  }
  for (const item of analysis.open_questions) {
    add(item.id, 'question', item.question)
  }
  for (const item of plan?.steps ?? []) {
    add(item.id, 'step', item.title)
  }

  return index
}

export function resolveTraceLinks(
  ids: string[] | null | undefined,
  index: Map<string, TraceEntry>,
): TraceEntry[] {
  const links: TraceEntry[] = []
  for (const id of presentIds(ids)) {
    const entry = index.get(id)
    if (entry) {
      links.push(entry)
    }
  }
  return links
}
