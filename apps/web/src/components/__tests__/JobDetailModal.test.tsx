import { render, screen } from '@testing-library/react'
import { JobDetailModal } from '../JobDetailModal'

// Regression guard: the worker writes score_detail with matched_keywords /
// missing_keywords (NOT matched / missing). The modal must render those, or the
// Match Analysis section is silently empty for all real pipeline data.
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
}

describe('JobDetailModal score_detail rendering', () => {
    it('renders matched + missing keywords from the worker shape', () => {
        render(<JobDetailModal {...props} />)
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
        expect(screen.getByText('go')).toBeInTheDocument()
        expect(screen.getByText('rust')).toBeInTheDocument()
    })
})
