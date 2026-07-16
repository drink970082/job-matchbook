/**
 * Test-data builders shaped to the Prisma models. Used as create() inputs in the
 * integration suite and as mock return values in unit tests. Override any field.
 */
export function makeApplication(over: Record<string, unknown> = {}) {
    return {
        company_name: 'Acme',
        job_title: 'Engineer',
        application_url: null,
        date_applied: '2026-01-01',
        category: 'SWE',
        status: 'Applied',
        notes: null,
        last_updated: '2026-01-01T00:00:00.000Z',
        ...over,
    }
}

export function makeJobPosting(over: Record<string, unknown> = {}) {
    return {
        source: 'greenhouse',
        external_id: 'e1',
        company_name: 'Acme',
        job_title: 'Engineer',
        location: 'Remote',
        job_url: 'https://example.com/jobs/1',
        // A realistic-length JD so a factory posting is a "normal" (confidently-parsed)
        // row by default — kept above LOW_CONTEXT_MAX_DESCRIPTION_LENGTH so it lands in
        // the score-aware buckets, not the derived Low-context bucket. Override with a
        // short string to build a thin/low-context posting.
        description:
            'We are hiring a software engineer to design, build, and operate backend ' +
            'services. You will own features end to end, collaborate across teams, write ' +
            'tests, review code, and help scale our platform. Requirements: strong ' +
            'programming fundamentals and experience shipping production systems.',
        score: null,
        score_detail: null,
        pipeline_status: 'scored',
        pipeline_error: null,
        attempts: 0,
        application_id: null,
        created_at: '2026-01-01T00:00:00.000Z',
        updated_at: null,
        ...over,
    }
}

export function makeStatusHistory(over: Record<string, unknown> = {}) {
    return {
        application_id: 1,
        status: 'Applied',
        timestamp: '2026-01-01T00:00:00.000Z',
        ...over,
    }
}

export function makeWatchedCompany(over: Record<string, unknown> = {}) {
    return {
        source: 'greenhouse',
        slug: 'acme',
        name: 'Acme',
        created_at: '2026-01-01T00:00:00.000Z',
        ...over,
    }
}
