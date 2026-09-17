import type { MeetingAnalysis } from '../types/analysis'
import { formatElapsed } from '../formatElapsed'

export type RecordSection =
  | 'all'
  | 'decisions'
  | 'requirements'
  | 'tasks'
  | 'risks'
  | 'questions'

interface AnalysisSummaryProps {
  meetingName: string | null
  analysis: MeetingAnalysis
  durationMs: number | null
  section: RecordSection
  onSectionChange: (section: RecordSection) => void
}

export function AnalysisSummary({
  meetingName,
  analysis,
  durationMs,
  section,
  onSectionChange,
}: AnalysisSummaryProps) {
  const filters: { id: RecordSection; label: string; value: number }[] = [
    {
      id: 'all',
      label: 'All',
      value:
        analysis.decisions.length +
        analysis.requirements.length +
        analysis.tasks.length +
        analysis.risks.length +
        analysis.open_questions.length,
    },
    { id: 'decisions', label: 'Decisions', value: analysis.decisions.length },
    {
      id: 'requirements',
      label: 'Requirements',
      value: analysis.requirements.length,
    },
    { id: 'tasks', label: 'Tasks', value: analysis.tasks.length },
    { id: 'risks', label: 'Risks', value: analysis.risks.length },
    {
      id: 'questions',
      label: 'Open',
      value: analysis.open_questions.length,
    },
  ]

  function toggle(id: RecordSection) {
    onSectionChange(section === id && id !== 'all' ? 'all' : id)
  }

  return (
    <section className="summary-copy" aria-labelledby="report-heading">
      <p className="eyebrow">Record</p>
      <h2 id="report-heading">{meetingName ?? 'Untitled meeting'}</h2>
      {durationMs != null ? (
        <p className="timing-note">{formatElapsed(durationMs)}</p>
      ) : null}
      <ul className="filter-row">
        {filters.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              aria-pressed={section === item.id}
              onClick={() => toggle(item.id)}
            >
              <span className="filter-count">{item.value}</span>
              <span className="filter-label">{item.label}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
