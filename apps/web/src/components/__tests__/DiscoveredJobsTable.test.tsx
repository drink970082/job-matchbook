import { render, screen, fireEvent } from '@testing-library/react'
import { DiscoveredJobsTable } from '@/components/DiscoveredJobsTable'

const mockJobs = [
  {
    id: 1,
    source: 'greenhouse',
    company_name: 'Acme',
    job_title: 'Backend Engineer',
    location: 'Remote',
    job_url: 'https://acme.example/jobs/1',
    description: 'Build things',
    score: 91,
    score_detail: '{"matched":["python","aws"],"missing":["kubernetes"],"reasoning":"Strong match"}',
    resume_path: '/resumes/1.pdf',
    resume_pages: 1,
    pipeline_status: 'scored',
  },
  {
    id: 2,
    source: 'lever',
    company_name: 'Globex',
    job_title: 'ML Engineer',
    location: 'NYC',
    job_url: 'https://globex.example/jobs/2',
    description: 'Train models',
    score: 78,
    score_detail: null,
    resume_path: '/resumes/2.pdf',
    resume_pages: 2,
    pipeline_status: 'tailored',
  },
]

describe('DiscoveredJobsTable', () => {
  it('renders rows with company, job title and source', () => {
    render(
      <DiscoveredJobsTable
        data={mockJobs}
        total={2}
        onFilterChange={jest.fn()}
        onMarkApplied={jest.fn()}
        onDiscard={jest.fn()}
        onReopen={jest.fn()}
        onViewJD={jest.fn()}
      />
    )

    expect(screen.getByText('Acme')).toBeInTheDocument()
    expect(screen.getByText('Globex')).toBeInTheDocument()
    expect(screen.getByText('Backend Engineer')).toBeInTheDocument()
    expect(screen.getByText('ML Engineer')).toBeInTheDocument()
  })

  it('shows the score for each row', () => {
    render(
      <DiscoveredJobsTable
        data={mockJobs}
        total={2}
        onFilterChange={jest.fn()}
        onMarkApplied={jest.fn()}
        onDiscard={jest.fn()}
        onReopen={jest.fn()}
        onViewJD={jest.fn()}
      />
    )

    expect(screen.getByText('91')).toBeInTheDocument()
    expect(screen.getByText('78')).toBeInTheDocument()
  })

  it('shows a multi-page warning flag when resume_pages > 1', () => {
    render(
      <DiscoveredJobsTable
        data={mockJobs}
        total={2}
        onFilterChange={jest.fn()}
        onMarkApplied={jest.fn()}
        onDiscard={jest.fn()}
        onReopen={jest.fn()}
        onViewJD={jest.fn()}
      />
    )

    // The 2-page row (Globex) should show a warning; the 1-page row should not.
    const warnings = screen.getAllByTitle(/page/i)
    expect(warnings.length).toBe(1)
    expect(warnings[0]).toHaveTextContent(/2/)
  })

  it('calls onMarkApplied when the Mark Applied action is clicked', () => {
    const onMarkApplied = jest.fn()
    render(
      <DiscoveredJobsTable
        data={mockJobs}
        total={2}
        onFilterChange={jest.fn()}
        onMarkApplied={onMarkApplied}
        onDiscard={jest.fn()}
        onReopen={jest.fn()}
        onViewJD={jest.fn()}
      />
    )

    const buttons = screen.getAllByTitle(/mark applied/i)
    fireEvent.click(buttons[0])
    expect(onMarkApplied).toHaveBeenCalledWith(1)
  })

  it('renders empty state when there is no data', () => {
    render(
      <DiscoveredJobsTable
        data={[]}
        total={0}
        onFilterChange={jest.fn()}
        onMarkApplied={jest.fn()}
        onDiscard={jest.fn()}
        onReopen={jest.fn()}
        onViewJD={jest.fn()}
      />
    )
    expect(screen.getByText(/no results/i)).toBeInTheDocument()
  })

  it('shows a Reopen control for discarded rows and calls onReopen', () => {
    const onReopen = jest.fn()
    const discarded = [{ ...mockJobs[0], pipeline_status: 'discarded' }]
    render(
      <DiscoveredJobsTable
        data={discarded}
        total={1}
        onFilterChange={jest.fn()}
        onMarkApplied={jest.fn()}
        onDiscard={jest.fn()}
        onReopen={onReopen}
        onViewJD={jest.fn()}
      />
    )

    // Discard is replaced by Reopen for a discarded row.
    expect(screen.queryByTitle(/discard/i)).not.toBeInTheDocument()
    const reopen = screen.getByTitle(/reopen/i)
    fireEvent.click(reopen)
    expect(onReopen).toHaveBeenCalledWith(1)
  })
})
