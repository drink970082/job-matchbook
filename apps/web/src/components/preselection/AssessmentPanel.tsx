import { normalizeAssessmentView } from '@/lib/assessment-view'

const STATE_LABELS = {
    not_assessed: 'Not assessed',
    current: 'Current',
    stale: 'Stale',
    unknown: 'Unknown',
} as const

const REASON_LABELS: Record<string, string> = {
    unsupported_schema: 'This assessment format is not supported.',
    malformed_snapshot: 'The supplied snapshot is incomplete.',
    non_synthetic_input: 'This view accepts fabricated assessment snapshots only.',
    invalid_expected_identity: 'The expected assessment identity is incomplete.',
    malformed_success: 'The saved assessment is malformed.',
    invalid_captured_identity: 'The saved assessment identity is incomplete.',
    invalid_assessment_time: 'The saved assessment time is invalid.',
    invalid_assessment_payload: 'No validated assessment values are available.',
    too_many_components: 'The assessment contains more components than this view supports.',
    too_many_jd_evidence: 'The assessment contains more JD evidence than this view supports.',
    identity_mismatch: 'The saved assessment belongs to different input versions.',
    malformed_view: 'No validated assessment values are available.',
}

function attemptLabel(state: string): string {
    switch (state) {
        case 'not_attempted': return 'Not attempted'
        case 'succeeded': return 'Succeeded'
        case 'provider_error': return 'Provider error'
        default: return 'Unknown'
    }
}

function DisplayText({ text, shortened }: { text: string; shortened: boolean }) {
    return (
        <>
            {text}
            {shortened && <span className="ml-1 text-xs text-muted-foreground">(shortened)</span>}
        </>
    )
}

export function AssessmentPanel({ value }: { value: unknown }) {
    const view = normalizeAssessmentView(value)
    const canShowComponents = view.assessment_state === 'current' || view.assessment_state === 'stale'

    return (
        <section aria-labelledby="synthetic-assessment-title" className="rounded-md border p-4">
            <h2 id="synthetic-assessment-title" className="text-lg font-semibold">
                Synthetic assessment preview
            </h2>
            <p aria-live="polite">
                Assessment state: <strong>{STATE_LABELS[view.assessment_state]}</strong>
            </p>
            {view.assessment_reason && (
                <p role="status">{REASON_LABELS[view.assessment_reason] ?? 'Assessment details are unavailable.'}</p>
            )}
            <p>Latest attempt: {attemptLabel(view.latest_attempt.state)}</p>
            {view.latest_attempt.error_category && (
                <p>Error category: {view.latest_attempt.error_category.replace(/_/g, ' ')}</p>
            )}
            {canShowComponents && (
                <>
                    <p>Assessed at: <time dateTime={view.assessment_time ?? undefined}>{view.assessment_time}</time></p>
                    {view.metadata && (
                        <p>Model: <DisplayText
                            text={String(view.metadata.resolved_model)}
                            shortened={view.metadata.resolved_model_truncated === true}
                        /></p>
                    )}
                    <ul aria-label="Assessment components" className="mt-2 space-y-2">
                        {view.components.map((component) => (
                            <li key={component.id}>
                                <h3 className="font-medium"><DisplayText
                                    text={component.label}
                                    shortened={component.label_truncated}
                                /></h3>
                                <p>{component.score} / 100</p>
                                {component.jd_evidence.map((evidence) => (
                                    <blockquote key={evidence.id} className="text-sm text-muted-foreground">
                                        <span><DisplayText
                                            text={evidence.label}
                                            shortened={evidence.label_truncated}
                                        />: </span>
                                        <span><DisplayText
                                            text={evidence.excerpt}
                                            shortened={evidence.excerpt_truncated}
                                        /></span>
                                    </blockquote>
                                ))}
                            </li>
                        ))}
                    </ul>
                </>
            )}
            {!canShowComponents && !view.assessment_reason && (
                <p>No validated assessment values are available.</p>
            )}
            <p className="mt-3 text-sm text-muted-foreground">
                Assessment evidence does not determine qualification.
            </p>
        </section>
    )
}
