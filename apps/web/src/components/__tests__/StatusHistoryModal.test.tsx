
import { render, screen, waitFor } from '@testing-library/react'
import { StatusHistoryModal } from '../StatusHistoryModal'
import userEvent from '@testing-library/user-event'

describe('StatusHistoryModal', () => {
    const mockHistory = [
        { id: 11, status: 'Applied', timestamp: '2023-01-01' },
        { id: 22, status: 'Interviewing: 1st round', timestamp: '2023-01-15' }
    ]

    const mockApplication = {
        id: 1,
        company_name: 'Google',
        job_title: 'SWE',
        category: 'SWE',
    }

    const makeProps = () => ({
        isOpen: true,
        onClose: jest.fn(),
        application: mockApplication,
        history: mockHistory,
        onAddStatus: jest.fn(),
        onDeleteHistory: jest.fn(),
        onEditApplication: jest.fn().mockResolvedValue(undefined),
    })

    // The history list renders an icon-only Trash button per row (no accessible
    // text), so identify those rows by their empty accessible name.
    const getDeleteButtons = () =>
        screen.getAllByRole('button').filter((b) => b.textContent?.trim() === '')

    it('should render history items', () => {
        render(<StatusHistoryModal {...makeProps()} />)
        expect(screen.getAllByText('Applied').length).toBeGreaterThan(0)
        // 'Interviewing: 1st round' also appears as a <select> option, so use
        // getAllByText (same pattern as 'Applied' above) rather than getByText.
        expect(screen.getAllByText('Interviewing: 1st round').length).toBeGreaterThan(0)
    })

    it('should call onClose when close button is clicked', async () => {
        const user = userEvent.setup()
        const props = makeProps()
        render(<StatusHistoryModal {...props} />)
        const closeButton = screen.getByRole('button', { name: /close/i })
        await user.click(closeButton)
        expect(props.onClose).toHaveBeenCalled()
    })

    it('adds a new status without a notes field', async () => {
        const user = userEvent.setup()
        const props = makeProps()
        render(<StatusHistoryModal {...props} />)

        // The Update-Status form no longer has a notes input (it was silently dropped).
        expect(screen.queryByLabelText(/notes/i)).not.toBeInTheDocument()

        await user.selectOptions(screen.getByLabelText(/status/i), 'Offer')
        await user.click(screen.getByRole('button', { name: /update status/i }))

        expect(props.onAddStatus).toHaveBeenCalledWith(
            expect.objectContaining({ status: 'Offer' }))
        expect(props.onAddStatus.mock.calls[0][0]).not.toHaveProperty('notes')
    })

    it('calls onDeleteHistory with the clicked row id', async () => {
        const user = userEvent.setup()
        const props = makeProps()
        render(<StatusHistoryModal {...props} />)

        const deleteButtons = getDeleteButtons()
        // Two history rows -> two delete buttons (and only those are icon-only).
        expect(deleteButtons).toHaveLength(2)

        // Second row is the 'First round' / id 22 entry.
        await user.click(deleteButtons[1])
        expect(props.onDeleteHistory).toHaveBeenCalledWith(22)
    })

    it('enters edit mode, saves changes, and returns to view mode', async () => {
        const user = userEvent.setup()
        const props = makeProps()
        render(<StatusHistoryModal {...props} />)

        // Enter edit mode.
        await user.click(screen.getByRole('button', { name: /^edit$/i }))

        // Edit fields are pre-populated from the application defaults.
        const companyInput = screen.getByPlaceholderText('Company Name')
        const titleInput = screen.getByPlaceholderText('Job Title')
        expect(companyInput).toHaveValue('Google')
        expect(titleInput).toHaveValue('SWE')

        // Category is a constrained dropdown, not free text (no data-loss on save).
        expect(screen.queryByPlaceholderText('Category')).not.toBeInTheDocument()
        const categorySelect = screen.getByRole('combobox', { name: /category/i })
        expect(categorySelect).toHaveValue('SWE')

        await user.clear(companyInput)
        await user.type(companyInput, 'Anthropic')
        await user.clear(titleInput)
        await user.type(titleInput, 'Research Engineer')
        await user.selectOptions(categorySelect, 'MLE')

        await user.click(screen.getByRole('button', { name: /^save$/i }))

        expect(props.onEditApplication).toHaveBeenCalledWith(
            mockApplication.id,
            expect.objectContaining({
                company_name: 'Anthropic',
                job_title: 'Research Engineer',
                category: 'MLE',
            }),
        )

        // After save the form collapses back to view mode (Edit button reappears).
        await waitFor(() => {
            expect(screen.getByRole('button', { name: /^edit$/i })).toBeInTheDocument()
        })
        expect(screen.queryByPlaceholderText('Company Name')).not.toBeInTheDocument()
    })

    it('cancels edit without calling onEditApplication and resets the form', async () => {
        const user = userEvent.setup()
        const props = makeProps()
        render(<StatusHistoryModal {...props} />)

        await user.click(screen.getByRole('button', { name: /^edit$/i }))

        const companyInput = screen.getByPlaceholderText('Company Name')
        await user.clear(companyInput)
        await user.type(companyInput, 'Throwaway')

        await user.click(screen.getByRole('button', { name: /^cancel$/i }))

        expect(props.onEditApplication).not.toHaveBeenCalled()

        // Back in view mode; re-opening edit shows the original (reset) value.
        await user.click(screen.getByRole('button', { name: /^edit$/i }))
        expect(screen.getByPlaceholderText('Company Name')).toHaveValue('Google')
    })
})
