/**
 * #158 acceptance: Discovered Jobs, Sources and Activity are read-only, except Mark
 * Applied (an Applications write) and Not interested (a triage skip override, #207).
 * Their components import no server action; their pages wire exactly these.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

const src = (f: string) => readFileSync(path.join(__dirname, '..', f), 'utf8')
const valueImportsFromActions = (code: string) =>
    [...code.matchAll(/^import\s+(?!type\b)\{([^}]*)\}\s+from\s+'@\/lib\/[a-z-]*actions'/gm)].map((m) => m[1].trim())

test.each(['components/DiscoveredJobsTable.tsx', 'components/JobDetailModal.tsx',
    'components/SourcesTab.tsx', 'components/ActivityTab.tsx', 'components/UnresolvedFeedsTable.tsx'])(
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

test('the Sources and Activity pages read and write nothing else', () => {
    const code = src('app/sources/page.tsx') + src('app/activity/page.tsx')
    expect(code.match(/^import \{([^}]*)\} from '@\/lib\/watchlist-actions'/m)?.[1].trim()).toBe('getWatchedCompanies')
    expect(code.match(/^import \{([^}]*)\} from '@\/lib\/activity-actions'/m)?.[1].trim()).toBe('getRecentActivity')
    expect(code).not.toMatch(/promotion-actions|addWatchedCompany|removeWatchedCompany/)
})
