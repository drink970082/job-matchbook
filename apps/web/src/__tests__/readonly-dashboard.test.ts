/**
 * #158 acceptance, widened by #207/#208: Discovered Jobs and Activity are read-only
 * except Mark Applied and Not interested; Sources adds and removes boards. Display
 * components import no server action; the views wire exactly these.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

const src = (f: string) => readFileSync(path.join(__dirname, '..', f), 'utf8')
const valueImportsFromActions = (code: string) =>
    [...code.matchAll(/^import\s+(?!type\b)\{([^}]*)\}\s+from\s+'@\/lib\/[a-z-]*actions'/gm)].map((m) => m[1].trim())

test.each(['components/DiscoveredJobsTable.tsx', 'components/JobDetailModal.tsx',
    'components/ActivityTab.tsx'])(
    '%s imports no server action', (file) => {
        expect(valueImportsFromActions(src(file))).toEqual([])
    })

test('the Jobs view wires only reads, Mark Applied and Not interested from the job actions', () => {
    const line = src('components/JobsView.tsx').match(/^import \{([^}]*)\} from '@\/lib\/job-actions'/m)
    expect(line?.[1].split(',').map((s) => s.trim()).sort()).toEqual(['clearTriageOverride', 'getJobPostings', 'markJobApplied', 'setTriageOverride'])
})

test('job-actions exports no pipeline-status mutation besides markJobApplied', async () => {
    const actions = await import('@/lib/job-actions')
    for (const gone of ['discardJobPosting', 'reopenJobPosting', 'bulkRemove', 'bulkReopen', 'removeAllInView']) {
        expect(actions).not.toHaveProperty(gone)
    }
})

test('the Sources and Activity pages read only; Sources writes only board add/remove', () => {
    const pages = src('app/sources/page.tsx') + src('app/activity/page.tsx')
    expect(pages.match(/^import \{([^}]*)\} from '@\/lib\/watchlist-actions'/m)?.[1].trim()).toBe('getWatchedCompanies')
    expect(pages.match(/^import \{([^}]*)\} from '@\/lib\/activity-actions'/m)?.[1].trim()).toBe('getRecentActivity')
    expect(valueImportsFromActions(src('components/SourcesTab.tsx'))).toEqual(['addWatchedCompany, removeWatchedCompany'])
    expect(pages + src('components/SourcesTab.tsx')).not.toMatch(/promotion-actions/)
})
