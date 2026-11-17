import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ImportCSVDialog } from '@/components/ImportCSVDialog'

jest.mock('sonner', () => ({ toast: { error: jest.fn(), success: jest.fn() } }))

// jsdom ships Blob without .text() (every target browser has it) — back it with the
// FileReader jsdom does implement, so the test asserts on real file content.
if (!Blob.prototype.text) {
    Blob.prototype.text = function () {
        return new Promise((resolve) => {
            const r = new FileReader()
            r.onload = () => resolve(String(r.result))
            r.readAsText(this)
        })
    }
}

const drop = (file: File) => {
    const zone = screen.getByText(/Drop a CSV here/i).parentElement as HTMLElement
    fireEvent.drop(zone, { dataTransfer: { files: [file] } })
}

describe('ImportCSVDialog', () => {
    it('hands the dropped CSV text to onImport and closes on success', async () => {
        const onImport = jest.fn().mockResolvedValue(true)
        const onOpenChange = jest.fn()
        render(<ImportCSVDialog open onOpenChange={onOpenChange} onImport={onImport} />)

        drop(new File(['company_name,job_title\n'], 'apps.csv', { type: 'text/csv' }))
        await screen.findByText('apps.csv')

        fireEvent.click(screen.getByRole('button', { name: 'Import' }))
        await waitFor(() => expect(onImport).toHaveBeenCalledWith('company_name,job_title\n'))
        expect(onOpenChange).toHaveBeenCalledWith(false)
    })

    // The guard is on the extension, not the MIME type — Excel on Windows reports a
    // .csv as application/vnd.ms-excel, so a type check would reject real CSVs.
    it('rejects a non-CSV file', () => {
        const onImport = jest.fn()
        render(<ImportCSVDialog open onOpenChange={jest.fn()} onImport={onImport} />)

        drop(new File(['x'], 'apps.xlsx', { type: 'text/csv' }))

        expect(screen.queryByText('apps.xlsx')).not.toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled()
        expect(onImport).not.toHaveBeenCalled()
    })
})
