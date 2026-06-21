import { render, screen, waitFor } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { ApplicationTable } from '@/components/ApplicationTable'
import userEvent from '@testing-library/user-event'

const mockApps = [
  { id: 1, company_name: 'Google', job_title: 'SWE', status: 'Applied', category: 'SWE', date_applied: '2023-01-01', notes: '' },
  { id: 2, company_name: 'Meta', job_title: 'MLE', status: 'Applied', category: 'MLE', date_applied: '2023-01-02', notes: '' },
]

function renderTable(overrides: Partial<ComponentProps<typeof ApplicationTable>> = {}) {
  const props: ComponentProps<typeof ApplicationTable> = {
    data: mockApps,
    total: 2,
    page: 0,
    size: 10,
    onPageChange: jest.fn(),
    onFilterChange: jest.fn(),
    onStatusChange: jest.fn(),
    onDelete: jest.fn(),
    onHistory: jest.fn(),
    ...overrides,
  }
  render(<ApplicationTable {...props} />)
  return props
}

describe('ApplicationTable', () => {
  it('should render applications', () => {
    renderTable()
    expect(screen.getByText('Google')).toBeInTheDocument()
    expect(screen.getByText('Meta')).toBeInTheDocument()
  })

  it('should handle pagination', async () => {
    const { onPageChange } = renderTable({ total: 20 })

    const nextButton = screen.getByRole('button', { name: /next/i })
    await userEvent.click(nextButton)

    expect(onPageChange).toHaveBeenCalledWith(1)
  })

  it('should handle search input', async () => {
    const { onFilterChange } = renderTable()

    const searchInput = screen.getByPlaceholderText(/search/i)
    await userEvent.type(searchInput, 'Google')

    await waitFor(() => {
        expect(onFilterChange).toHaveBeenCalledWith(expect.objectContaining({ search: 'Google' }))
    })
  })

  it('calls onStatusChange with the row id and the newly selected status', async () => {
    const { onStatusChange } = renderTable()

    // Each row has a native <select> for its status. The filter dropdowns are
    // Radix triggers (also role=combobox), so narrow to real <select> elements;
    // first native select belongs to row id 1.
    const nativeSelects = screen
      .getAllByRole('combobox')
      .filter((el): el is HTMLSelectElement => el.tagName === 'SELECT')
    expect(nativeSelects.length).toBe(2)
    await userEvent.selectOptions(nativeSelects[0], 'Offer')

    expect(onStatusChange).toHaveBeenCalledWith(1, 'Offer')
  })

  it('calls onDelete with the row id when the Delete button is clicked', async () => {
    const { onDelete } = renderTable()

    const deleteButtons = screen.getAllByRole('button', { name: /delete/i })
    await userEvent.click(deleteButtons[0])

    expect(onDelete).toHaveBeenCalledWith(1)
  })

  it('calls onHistory with the row id when the History button is clicked', async () => {
    const { onHistory } = renderTable()

    const historyButtons = screen.getAllByRole('button', { name: /history/i })
    await userEvent.click(historyButtons[0])

    expect(onHistory).toHaveBeenCalledWith(1)
  })
})
