import { render, screen } from '@testing-library/react'
import { StatusFunnel } from '@/components/StatusFunnel'
import { STATUSES } from '@/lib/constants'

// Characterization test for the funnel's status vocabulary, written BEFORE the
// vocabulary was consolidated so it pins today's behavior rather than tomorrow's
// intent.
//
// Two properties matter and neither had a test:
//   1. ORDER. The progression stages and the terminal stages each render in a
//      hand-authored sequence. Reordering either is a visible chart change.
//   2. TOTALITY. The funnel partitions its vocabulary three ways — the 'Applied'
//      header, the progression list, and the terminal list. A status in none of
//      them is silently absent from the chart, with nothing to catch it.
//
// The vocabulary is STATUSES plus 'No Response', the pseudo-status
// getStatusFlow synthesizes for an application that never left 'Applied'.

const NO_RESPONSE = 'No Response'

// Hand-written on purpose: deriving it from the component's own constants would
// make the test agree with any reordering.
const EXPECTED_PROGRESSION = [
    'Online Assessment',
    'Phone Screen',
    'Interviewing: 1st round',
    'Interviewing: 2nd round',
    'Interviewing: 3rd round',
    'Interviewing: 4th round',
    'Interviewing: 5th round',
    'Final Round',
    'Offer',
    'Accepted',
]

const EXPECTED_TERMINAL = [NO_RESPONSE, 'Rejected', 'Withdrew', 'Ghosted']

// One transition into every status, distinct values so a mis-paired name/count fails.
const ALL_TARGETS = [...EXPECTED_PROGRESSION, ...EXPECTED_TERMINAL]
const data = ALL_TARGETS.map((to, i) => ({ from: 'Applied', to, value: i + 1 }))

/** Assert the named elements appear in this order in the document. */
function expectDocumentOrder(names: string[]) {
    const els = names.map((n) => screen.getByText(n))
    for (let i = 0; i + 1 < els.length; i++) {
        const rel = els[i].compareDocumentPosition(els[i + 1])
        expect({
            earlier: names[i],
            later: names[i + 1],
            followsEarlier: Boolean(rel & Node.DOCUMENT_POSITION_FOLLOWING),
        }).toEqual({ earlier: names[i], later: names[i + 1], followsEarlier: true })
    }
}

describe('StatusFunnel status vocabulary', () => {
    it('renders the progression stages in their declared order', () => {
        render(<StatusFunnel data={data} />)
        expectDocumentOrder(EXPECTED_PROGRESSION)
    })

    it('renders the terminal stages after the progression, in their declared order', () => {
        render(<StatusFunnel data={data} />)
        expectDocumentOrder([...EXPECTED_PROGRESSION, ...EXPECTED_TERMINAL])
    })

    it('pairs every stage with its own count', () => {
        render(<StatusFunnel data={data} />)
        // Name and count are siblings in the same row, so a swapped pairing fails.
        ALL_TARGETS.forEach((name, i) => {
            const row = screen.getByText(name).parentElement as HTMLElement
            expect({ name, row: row.textContent }).toEqual({
                name,
                row: expect.stringContaining(String(i + 1)),
            })
        })
    })

    // The totality guard. 'Applied' is the header bar, never a stage row; every
    // other member of the chart vocabulary must land in exactly one list. If this
    // fails after a status is added to STATUSES, that status is invisible in the
    // funnel — which is the silent failure the test exists to make loud.
    it('covers the whole chart vocabulary: STATUSES + No Response, partitioned', () => {
        const chartVocabulary = [...STATUSES, NO_RESPONSE]
        const partitioned = ['Applied', ...EXPECTED_PROGRESSION, ...EXPECTED_TERMINAL]

        expect([...partitioned].sort()).toEqual([...chartVocabulary].sort())
        expect(new Set(partitioned).size).toBe(partitioned.length)
    })

    it('shows the empty state when there is no flow data', () => {
        render(<StatusFunnel data={[]} />)
        expect(screen.getByText('No status flow data')).toBeInTheDocument()
    })
})
