import { getStatusColor } from '@/lib/constants'

describe('getStatusColor', () => {
    test.each([
        ['Applied', 'blue'],
        ['Online Assessment', 'purple'],
        ['Phone Screen', 'violet'],
        ['Final Round', 'orange'],
        ['Interviewing: 1st round', 'amber'],
        ['Interviewing: 3rd round', 'amber'],
        ['Offer', 'emerald'],
        ['Accepted', 'emerald'],
        ['Rejected', 'red'],
        ['Withdrew', 'slate'],
        ['Ghosted', 'zinc'],
        ['Totally Unknown Status', 'gray'],
    ])('%s maps to the %s color family', (status, family) => {
        const c = getStatusColor(status)
        expect(c.bg).toContain(family)
        expect(c.text).toContain(family)
        expect(c.dot).toContain(family)
    })
})
