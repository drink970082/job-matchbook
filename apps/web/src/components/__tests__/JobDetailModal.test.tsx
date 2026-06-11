import { render, screen, fireEvent } from '@testing-library/react'
import { JobDetailModal } from '../JobDetailModal'

// Regression guard: the worker writes score_detail with matched_keywords /
// missing_keywords (NOT matched / missing). The modal must render those, or the
// Match Analysis section is silently empty for all real pipeline data. Match
// detail is collapsed behind a toggle, so the tests expand it first.
const workerShapedJob: any = {
    id: 1,
    source: 'greenhouse',
    company_name: 'Acme',
    job_title: 'Backend Engineer',
    location: 'Remote',
    job_url: 'https://example.com/jobs/1',
    description: 'Build scalable services.',
    score: 91,
    score_detail: JSON.stringify({
        matched_keywords: ['python', 'aws'],
        missing_keywords: ['kubernetes'],
        reasoning: 'Strong backend match.',
    }),
    resume_path: null,
    resume_pages: null,
    pipeline_status: 'scored',
}

const props = {
    isOpen: true,
    onClose: jest.fn(),
    job: workerShapedJob,
    onMarkApplied: jest.fn(),
    onDiscard: jest.fn(),
    onReopen: jest.fn(),
}

describe('JobDetailModal score_detail rendering', () => {
    it('renders matched + missing keywords from the worker shape (behind the details toggle)', () => {
        render(<JobDetailModal {...props} />)
        fireEvent.click(screen.getByText(/match details/i))
        expect(screen.getByText('Matched')).toBeInTheDocument()
        expect(screen.getByText('python')).toBeInTheDocument()
        expect(screen.getByText('aws')).toBeInTheDocument()
        expect(screen.getByText('Missing')).toBeInTheDocument()
        expect(screen.getByText('kubernetes')).toBeInTheDocument()
        expect(screen.getByText('Strong backend match.')).toBeInTheDocument()
    })

    it('still tolerates the legacy matched/missing keys', () => {
        const legacy = {
            ...props,
            job: {
                ...workerShapedJob,
                score_detail: JSON.stringify({ matched: ['go'], missing: ['rust'] }),
            },
        }
        render(<JobDetailModal {...legacy} />)
        fireEvent.click(screen.getByText(/match details/i))
        expect(screen.getByText('go')).toBeInTheDocument()
        expect(screen.getByText('rust')).toBeInTheDocument()
    })

    it('shows the disqualification reason up-front (no toggle) and offers Reopen when discarded', () => {
        const disqualified = {
            ...props,
            job: {
                ...workerShapedJob,
                pipeline_status: 'discarded',
                score_detail: JSON.stringify({
                    matched_keywords: [],
                    missing_keywords: [],
                    reasoning: 'Senior role.',
                    disqualified: true,
                    disqualification_reason: 'requires 8+ years (candidate is entry-level)',
                }),
            },
        }
        render(<JobDetailModal {...disqualified} />)
        // Decision is reachable without expanding anything.
        expect(screen.getByText('Disqualified')).toBeInTheDocument()
        expect(screen.getByText(/requires 8\+ years/)).toBeInTheDocument()
        // Discarded rows get a Reopen action instead of Discard.
        expect(screen.getByRole('button', { name: /reopen/i })).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: /discard/i })).not.toBeInTheDocument()
    })

    it('renders the per-requirement gate breakdown from screen', () => {
        const withScreen = {
            ...props,
            job: {
                ...workerShapedJob,
                pipeline_status: 'discarded',
                score_detail: JSON.stringify({
                    matched_keywords: [],
                    missing_keywords: [],
                    disqualified: true,
                    disqualification_reason: 'location: on-site in Singapore',
                    screen: {
                        experience: { pass: true, note: '' },
                        location: { pass: false, note: 'on-site in Singapore' },
                    },
                }),
            },
        }
        render(<JobDetailModal {...withScreen} />)
        expect(screen.getByText('Screening')).toBeInTheDocument()
        // Each gate is listed; the failing one shows its note (also in the banner,
        // so it appears more than once).
        expect(screen.getByText('experience')).toBeInTheDocument()
        expect(screen.getByText('location')).toBeInTheDocument()
        expect(screen.getAllByText(/on-site in Singapore/).length).toBeGreaterThanOrEqual(1)
    })
})
