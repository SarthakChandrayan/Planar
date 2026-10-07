/**
 * The plan map's graph, built from the validated record: no model call, so
 * every box and arrow is a real item and a real link.
 *
 *   decisions (why) -> requirements (what) -> plan steps (how) -> owners (who)
 */
import type { MeetingAnalysis, Task } from './types/analysis'
import type { ImplementationPlan } from './types/plan'

export type MapColumn = 'decision' | 'requirement' | 'step' | 'owner'

export interface MapNode {
  key: string
  column: MapColumn
  /** Item ID to jump to when clicked. */
  traceId: string
  label: string
  title: string
  /** Decisions no requirement links to still constrain the whole plan. */
  loose?: boolean
  riskCount?: number
  owners?: string[]
  due?: string[]
  when?: string | null
  stepCount?: number
}

export interface MapEdge {
  from: string
  to: string
}

export interface PlanGraph {
  columns: Record<MapColumn, MapNode[]>
  edges: MapEdge[]
  /** Requirements no plan step covers, so the map can name them. */
  unlinkedRequirements: { id: string; statement: string }[]
}

const UNASSIGNED = 'Unassigned'

function ownerKey(name: string): string {
  return `owner:${name}`
}

export function buildPlanGraph(analysis: MeetingAnalysis, plan: ImplementationPlan): PlanGraph {
  const requirements = new Map(analysis.requirements.map((r) => [r.id, r]))
  const decisions = new Map(analysis.decisions.map((d) => [d.id, d]))
  const tasks = new Map(analysis.tasks.map((t) => [t.id, t]))
  const edges: MapEdge[] = []
  const seenEdges = new Set<string>()
  const addEdge = (from: string, to: string) => {
    const id = `${from}>${to}`
    if (!seenEdges.has(id)) {
      seenEdges.add(id)
      edges.push({ from, to })
    }
  }

  // Steps, in plan order, with the people doing their tasks.
  const ownerSteps = new Map<string, { steps: number; firstTask: string }>()
  const stepNodes: MapNode[] = plan.steps.map((step, index) => {
    const stepTasks = (step.related_task_ids ?? [])
      .map((id) => tasks.get(id))
      .filter((t): t is Task => Boolean(t))
    const owners: string[] = []
    for (const task of stepTasks) {
      const owner = task.owner?.trim() || UNASSIGNED
      if (!owners.includes(owner)) {
        owners.push(owner)
      }
      const entry = ownerSteps.get(owner)
      if (entry) {
        entry.steps += 1
      } else {
        ownerSteps.set(owner, { steps: 1, firstTask: task.id })
      }
      addEdge(step.id, ownerKey(owner))
    }
    return {
      key: step.id,
      column: 'step',
      traceId: step.id,
      label: `${index + 1}`,
      title: step.title,
      owners: owners.filter((o) => o !== UNASSIGNED),
      due: stepTasks.map((t) => t.due?.trim()).filter((d): d is string => Boolean(d)),
      when: step.when ?? null,
    }
  })

  // Requirements the plan delivers, in the order the steps reach them.
  const requirementOrder: string[] = []
  for (const step of plan.steps) {
    for (const id of step.related_requirement_ids ?? []) {
      if (requirements.has(id)) {
        if (!requirementOrder.includes(id)) {
          requirementOrder.push(id)
        }
        addEdge(id, step.id)
      }
    }
  }
  const requirementNodes: MapNode[] = requirementOrder.map((id) => {
    const req = requirements.get(id)!
    return {
      key: id,
      column: 'requirement',
      traceId: id,
      label: id,
      title: req.statement,
      riskCount: req.related_risk_ids?.length ?? 0,
    }
  })

  // Decisions the steps apply directly, then those behind their requirements,
  // then the rest as constraints on the plan as a whole.
  const decisionOrder: string[] = []
  for (const step of plan.steps) {
    for (const decisionId of step.related_decision_ids ?? []) {
      if (decisions.has(decisionId)) {
        if (!decisionOrder.includes(decisionId)) {
          decisionOrder.push(decisionId)
        }
        addEdge(decisionId, step.id)
      }
    }
  }
  for (const id of requirementOrder) {
    for (const decisionId of requirements.get(id)?.related_decision_ids ?? []) {
      if (decisions.has(decisionId)) {
        if (!decisionOrder.includes(decisionId)) {
          decisionOrder.push(decisionId)
        }
        addEdge(decisionId, id)
      }
    }
  }
  const linked = new Set(decisionOrder)
  for (const decision of analysis.decisions) {
    if (!linked.has(decision.id)) {
      decisionOrder.push(decision.id)
    }
  }
  const decisionNodes: MapNode[] = decisionOrder.map((id) => ({
    key: id,
    column: 'decision',
    traceId: id,
    label: id,
    title: decisions.get(id)!.statement,
    loose: !linked.has(id),
  }))

  const ownerNodes: MapNode[] = [...ownerSteps.entries()]
    .sort(([a, x], [b, y]) => (a === UNASSIGNED ? 1 : b === UNASSIGNED ? -1 : y.steps - x.steps))
    .map(([name, info]) => ({
      key: ownerKey(name),
      column: 'owner',
      traceId: info.firstTask,
      label: name,
      title: name,
      stepCount: info.steps,
    }))

  return {
    columns: {
      decision: decisionNodes,
      requirement: requirementNodes,
      step: stepNodes,
      owner: ownerNodes,
    },
    edges,
    unlinkedRequirements: analysis.requirements
      .filter((r) => !requirementOrder.includes(r.id))
      .map((r) => ({ id: r.id, statement: r.statement })),
  }
}

/** Everything upstream and downstream of a node: its line of reasoning. */
export function lineage(key: string, edges: MapEdge[]): Set<string> {
  const forward = new Map<string, string[]>()
  const backward = new Map<string, string[]>()
  for (const { from, to } of edges) {
    forward.set(from, [...(forward.get(from) ?? []), to])
    backward.set(to, [...(backward.get(to) ?? []), from])
  }
  const result = new Set<string>([key])
  for (const graph of [forward, backward]) {
    const queue = [key]
    while (queue.length) {
      const next = queue.shift()!
      for (const neighbour of graph.get(next) ?? []) {
        if (!result.has(neighbour)) {
          result.add(neighbour)
          queue.push(neighbour)
        }
      }
    }
  }
  return result
}
