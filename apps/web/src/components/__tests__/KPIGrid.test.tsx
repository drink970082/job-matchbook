import { render, screen, within } from '@testing-library/react'
import { KPIGrid } from '@/components/KPIGrid'

describe('KPIGrid', () => {
    // Distinct values so a mis-paired label/value (swapped stats key) would fail.
    const stats = {
        total: 10,
        active: 5,
        screening: 2,
        interviewing: 3,
        rejected: 4,
        offer: 1,
    }

    // Each tile is the div wrapping the label span; its sibling span holds the value.
    const expectPair = (label: string, value: string) => {
        const tile = screen.getByText(label).closest('div') as HTMLElement
        expect(tile).not.toBeNull()
        expect(within(tile).getByText(value)).toBeInTheDocument()
    }

    it('pairs each KPI label with its own value (all six buckets)', () => {
        render(<KPIGrid stats={stats} />)

        // label text -> stats key.
        expectPair('Total', '10')          // total
        expectPair('Active', '5')          // active
        expectPair('Screening', '2')       // screening
        expectPair('Interviewing', '3')    // interviewing
        expectPair('Rejected', '4')        // rejected
        expectPair('Offer', '1')           // offer
    })
})
