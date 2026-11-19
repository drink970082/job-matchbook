import { getStatusColor, LEGACY_STATUS_MAP, STATUSES } from '@/lib/constants'

describe('getStatusColor', () => {
    test.each([
        ['Applied', 'blue'],
        ['Screening', 'purple'],
        ['Interviewing', 'amber'],
        ['Offer', 'emerald'],
        ['Accepted', 'emerald'],
        ['Rejected', 'red'],
        ['Withdrew', 'slate'],
        ['Totally Unknown Status', 'gray'],
    ])('%s maps to the %s color family', (status, family) => {
        const c = getStatusColor(status)
        expect(c.bg).toContain(family)
        expect(c.text).toContain(family)
        expect(c.dot).toContain(family)
    })
})

test('every legacy status maps onto a current one', () => {
    expect(Object.keys(LEGACY_STATUS_MAP)).toHaveLength(9)
    for (const to of Object.values(LEGACY_STATUS_MAP)) expect(STATUSES).toContain(to)
})
