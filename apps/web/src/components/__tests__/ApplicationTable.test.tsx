import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ApplicationTable } from '@/components/ApplicationTable'
import userEvent from '@testing-library/user-event'

const mockApps = [
  { id: 1, company_name: 'Google', job_title: 'SWE', status: 'Applied', category: 'SWE', date_applied: '2023-01-01', notes: '' },
  { id: 2, company_name: 'Meta', job_title: 'MLE', status: 'Applied', category: 'MLE', date_applied: '2023-01-02', notes: '' },
]

describe('ApplicationTable', () => {
  it('should render applications', () => {
    render(
      <ApplicationTable
        data={mockApps}
        total={2}
        page={0}
        size={10}
        onPageChange={jest.fn()}
        onFilterChange={jest.fn()}
        onStatusChange={jest.fn()}
        onDelete={jest.fn()}
        onHistory={jest.fn()}
      />
    )

    expect(screen.getByText('Google')).toBeInTheDocument()
    expect(screen.getByText('Meta')).toBeInTheDocument()
  })

  it('should handle pagination', async () => {
    const onPageChange = jest.fn()
    render(
      <ApplicationTable
        data={mockApps}
        total={20}
        page={0}
        size={10}
        onPageChange={onPageChange}
        onFilterChange={jest.fn()}
        onStatusChange={jest.fn()}
        onDelete={jest.fn()}
        onHistory={jest.fn()}
      />
    )

    const nextButton = screen.getByRole('button', { name: /next/i })
    await userEvent.click(nextButton)

    expect(onPageChange).toHaveBeenCalledWith(1)
  })

  it('should handle search input', async () => {
    const onFilterChange = jest.fn()
    render(
      <ApplicationTable
        data={mockApps}
        total={2}
        page={0}
        size={10}
        onPageChange={jest.fn()}
        onFilterChange={onFilterChange}
        onStatusChange={jest.fn()}
        onDelete={jest.fn()}
        onHistory={jest.fn()}
      />
    )

    const searchInput = screen.getByPlaceholderText(/search/i)
    await userEvent.type(searchInput, 'Google')

    await waitFor(() => {
        expect(onFilterChange).toHaveBeenCalledWith(expect.objectContaining({ search: 'Google' }))
    })
  })
})
