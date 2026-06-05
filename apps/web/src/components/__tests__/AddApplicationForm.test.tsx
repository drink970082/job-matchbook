import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { AddApplicationForm } from '@/components/AddApplicationForm'
import userEvent from '@testing-library/user-event'

describe('AddApplicationForm', () => {
  it('should submit valid data', async () => {
    const onSubmit = jest.fn()
    render(<AddApplicationForm onSubmit={onSubmit} />)

    const companyInput = screen.getByPlaceholderText(/company name/i)
    const jobInput = screen.getByPlaceholderText(/job title/i)

    await act(async () => {
      fireEvent.change(companyInput, { target: { value: 'Amazon' } })
      fireEvent.change(jobInput, { target: { value: 'SDE' } })
    })

    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: /add/i }))
    })

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          company_name: 'Amazon',
          job_title: 'SDE',
        }),
      )
    })
  })

  it('should show validation error for missing fields', async () => {
    const onSubmit = jest.fn()
    render(<AddApplicationForm onSubmit={onSubmit} />)

    await act(async () => {
      fireEvent.change(screen.getByPlaceholderText(/company name/i), { target: { value: '' } })
      fireEvent.change(screen.getByPlaceholderText(/job title/i), { target: { value: '' } })
    })

    await act(async () => {
      fireEvent.submit(screen.getByRole('button', { name: /add/i }))
    })

    expect(onSubmit).not.toHaveBeenCalled()
  })
})
