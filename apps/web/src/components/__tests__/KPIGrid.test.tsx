import { render, screen, within } from '@testing-library/react'
import { KPIGrid } from '@/components/KPIGrid'

describe('KPIGrid', () => {
    // Distinct values so a mis-paired label/value (swapped stats key) would fail.
    const stats = {
        applied: 10,
        active: 5,
        assessment: 2,
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

        // label text -> stats key. 'OA' is the assessment bucket; 'Active' the active bucket.
        expectPair('Applied', '10')        // applied
        expectPair('Active', '5')          // active
        expectPair('OA', '2')              // assessment
        expectPair('Interviewing', '3')    // interviewing
        expectPair('Rejected', '4')        // rejected
        expectPair('Offer', '1')           // offer
    })
})
