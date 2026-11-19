/**
 * #158 acceptance: Discovered Jobs, Sources and Activity are read-only, except Mark
 * Applied (an Applications write, the operator's call). Their components import no
 * server action; the Dashboard wires exactly these reads and that one write.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

const src = (f: string) => readFileSync(path.join(__dirname, '..', f), 'utf8')
const valueImportsFromActions = (code: string) =>
    [...code.matchAll(/^import\s+(?!type\b)\{([^}]*)\}\s+from\s+'@\/lib\/[a-z-]*actions'/gm)].map((m) => m[1].trim())

test.each(['components/DiscoveredJobsTable.tsx', 'components/DiscoveredJobsTab.tsx', 'components/JobDetailModal.tsx',
    'components/SourcesTab.tsx', 'components/ActivityTab.tsx', 'components/UnresolvedFeedsTable.tsx'])(
    '%s imports no server action', (file) => {
        expect(valueImportsFromActions(src(file))).toEqual([])
    })

test('the Dashboard wires only reads and Mark Applied from the job actions', () => {
    const line = src('components/Dashboard.tsx').match(/^import \{([^}]*)\} from '@\/lib\/job-actions'/m)
    expect(line?.[1].split(',').map((s) => s.trim()).sort()).toEqual(['getJobPostings', 'getJobStageCounts', 'markJobApplied'])
})

test('job-actions exports no pipeline-status mutation besides markJobApplied', async () => {
    const actions = await import('@/lib/job-actions')
    for (const gone of ['discardJobPosting', 'reopenJobPosting', 'bulkRemove', 'bulkReopen', 'removeAllInView']) {
        expect(actions).not.toHaveProperty(gone)
    }
})

test('the Dashboard reads sources and activity and writes neither', () => {
    const code = src('components/Dashboard.tsx')
    expect(code.match(/^import \{([^}]*)\} from '@\/lib\/watchlist-actions'/m)?.[1].trim()).toBe('getWatchedCompanies')
    expect(code.match(/^import \{([^}]*)\} from '@\/lib\/activity-actions'/m)?.[1].trim()).toBe('getRecentActivity')
    expect(code).not.toMatch(/promotion-actions|addWatchedCompany|removeWatchedCompany/)
})
