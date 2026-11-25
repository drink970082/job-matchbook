/**
 * The key-scoped loopback write API (/api/v1/*). Route handlers are called directly
 * against the throwaway integration DB; they wrap the lib/*-actions.ts Server Actions, so these tests pin
 * the auth contract and that the API and the UI share one validation path.
 */
import { POST as createApplication } from '@/app/api/v1/applications/route'
import { PATCH as patchApplication } from '@/app/api/v1/applications/[id]/route'
import { POST as postStatus } from '@/app/api/v1/applications/[id]/status/route'
import { POST as postApplied } from '@/app/api/v1/jobs/[id]/applied/route'
import { POST as addWatch } from '@/app/api/v1/watchlist/route'
import { POST as setTriage, DELETE as clearTriage } from '@/app/api/v1/jobs/[id]/triage/route'
import { DELETE as removeWatch } from '@/app/api/v1/watchlist/[id]/route'
import { PUT as putProfile } from '@/app/api/v1/candidate-profile/route'
import { updateApplicationStatus } from '@/lib/application-actions'
import { addWatchedCompany, removeWatchedCompany } from '@/lib/watchlist-actions'
import { getActivityTimeline } from '@/lib/activity-actions'
import { prisma, resetDb } from '@/test-utils/db'
import { makeApplication, makeJobPosting } from '@/test-utils/factories'

const READ = 'read-key-0123456789'
const RW = 'rw-key-0123456789'

function req(body: unknown, key?: string, method = 'POST') {
    const headers: Record<string, string> = { 'content-type': 'application/json' }
    if (key) headers.authorization = `Bearer ${key}`
    return new Request('http://127.0.0.1:3000/api/v1/x', {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
    })
}
const params = (id: number | string) => ({ params: { id: String(id) } })

beforeEach(async () => {
    await resetDb()
    process.env.ATS_API_KEY_READ = READ
    process.env.ATS_API_KEY_READ_WRITE = RW
})
afterAll(() => prisma.$disconnect())

const NEW_APP = { company_name: 'Acme', job_title: 'Engineer', date_applied: '2026-11-17' }

test('no key configured -> 503, the API is disabled rather than open', async () => {
    delete process.env.ATS_API_KEY_READ
    process.env.ATS_API_KEY_READ_WRITE = ''
    const res = await createApplication(req(NEW_APP, RW))
    expect(res.status).toBe(503)
    expect(await prisma.applications.count()).toBe(0)
})

test('missing or wrong bearer -> 401', async () => {
    expect((await createApplication(req(NEW_APP))).status).toBe(401)
    expect((await createApplication(req(NEW_APP, 'nope'))).status).toBe(401)
    expect(await prisma.applications.count()).toBe(0)
})

test('read key on a write -> 403', async () => {
    expect((await createApplication(req(NEW_APP, READ))).status).toBe(403)
    expect(await prisma.applications.count()).toBe(0)
})

test('read_write key creates an application stamped actor=mcp', async () => {
    const res = await createApplication(req(NEW_APP, RW))
    expect(res.status).toBe(200)
    const app = await prisma.applications.findFirstOrThrow()
    expect(app.actor).toBe('mcp')
    expect(app.status).toBe('Applied')
})

test('UI-created rows default to actor=web', async () => {
    const app = await prisma.applications.create({ data: makeApplication() })
    expect(app.actor).toBe('web')
})

test('status update appends history with actor=mcp', async () => {
    const app = await prisma.applications.create({ data: makeApplication() })
    const res = await postStatus(req({ status: 'Screening', date: '2026-11-17' }, RW), params(app.id))
    expect(res.status).toBe(200)
    const hist = await prisma.status_history.findMany({ where: { application_id: app.id } })
    expect(hist).toHaveLength(1)
    expect(hist[0].actor).toBe('mcp')
    expect(hist[0].timestamp).toBe('2026-11-17T12:00:00.000Z')
})

test('status update returns the current status, which a backdated change does not move', async () => {
    const app = await prisma.applications.create({ data: makeApplication() })
    await postStatus(req({ status: 'Interviewing', date: '2026-11-10' }, RW), params(app.id))
    const res = await postStatus(req({ status: 'Rejected', date: '2026-11-01' }, RW), params(app.id))
    expect(res.status).toBe(200)
    expect((await res.json()).data).toEqual({ status: 'Interviewing', recorded: 'Rejected' })
})

test('status validation is the UI function: same error through both paths', async () => {
    const app = await prisma.applications.create({ data: makeApplication() })
    const ui = await updateApplicationStatus(app.id, 'Nonsense')
    const res = await postStatus(req({ status: 'Nonsense' }, RW), params(app.id))
    expect(res.status).toBe(400)
    expect((await res.json()).error).toBe(ui.error)
    expect(await prisma.status_history.count()).toBe(0)
})

test('UI status update stamps actor=web', async () => {
    const app = await prisma.applications.create({ data: makeApplication() })
    await updateApplicationStatus(app.id, 'Offer')
    expect((await prisma.status_history.findFirstOrThrow()).actor).toBe('web')
})

test('PATCH updates only the given fields (category is not reset)', async () => {
    const app = await prisma.applications.create({ data: makeApplication({ category: 'SWE' }) })
    const res = await patchApplication(req({ notes: 'recruiter called' }, RW, 'PATCH'), params(app.id))
    expect(res.status).toBe(200)
    const after = await prisma.applications.findUniqueOrThrow({ where: { id: app.id } })
    expect(after.notes).toBe('recruiter called')
    expect(after.category).toBe('SWE')
    expect(after.company_name).toBe('Acme')
})

test('mark a discovered job applied -> application with actor=mcp', async () => {
    const jp = await prisma.job_postings.create({ data: makeJobPosting() })
    const res = await postApplied(req({ category: 'SWE' }, RW), params(jp.id))
    expect(res.status).toBe(200)
    const app = await prisma.applications.findFirstOrThrow()
    expect(app.actor).toBe('mcp')
    expect((await prisma.job_postings.findUniqueOrThrow({ where: { id: jp.id } })).pipeline_status).toBe('applied')
})

test('bad id and bad JSON -> 400', async () => {
    expect((await postStatus(req({ status: 'Offer' }, RW), params('abc'))).status).toBe(400)
    const bad = new Request('http://127.0.0.1:3000/api/v1/x', {
        method: 'POST',
        headers: { authorization: `Bearer ${RW}` },
        body: '{not json',
    })
    expect((await createApplication(bad)).status).toBe(400)
})

test('watchlist add and remove are audited with the full row and actor=mcp', async () => {
    const res = await addWatch(req({ source: 'greenhouse', slug: 'acme', name: 'Acme' }, RW))
    expect(res.status).toBe(200)
    const row = await prisma.watched_companies.findFirstOrThrow()
    const del = await removeWatch(req(undefined, RW, 'DELETE'), params(row.id))
    expect(del.status).toBe(200)
    expect((await del.json()).data).toEqual(row)
    expect(await prisma.watched_companies.count()).toBe(0)
    const log = await prisma.audit_log.findMany({ orderBy: { id: 'asc' } })
    expect(log.map((l) => [l.actor, l.action, l.entity, l.entity_id])).toEqual([
        ['mcp', 'add', 'watched_companies', row.id],
        ['mcp', 'remove', 'watched_companies', row.id],
    ])
    expect(JSON.parse(log[1].payload)).toEqual(row)
})

test('an invalid slug is rejected with the UI message and nothing is audited', async () => {
    const res = await addWatch(req({ source: 'greenhouse', slug: 'evil.com/@x', name: 'X' }, RW))
    expect(res.status).toBe(400)
    expect((await res.json()).error).toBe('slug contains invalid characters')
    expect(await prisma.audit_log.count()).toBe(0)
})

test('a watchlist dry run returns the resolved board and adds nothing (#231)', async () => {
    const res = await addWatch(req({ url: 'https://boards.greenhouse.io/acme', name: 'Acme', dry_run: true }, RW))
    expect(res.status).toBe(200)
    expect((await res.json()).data).toEqual({ source: 'greenhouse', slug: 'acme', name: 'Acme', recipe: null })
    expect(await prisma.watched_companies.count()).toBe(0)
    const bad = await addWatch(req({ source: 'greenhouse', slug: 'acme', name: 'Acme', dry_run: 'yes' }, RW))
    expect(bad.status).toBe(400)
    expect(await prisma.watched_companies.count()).toBe(0)
})

test('removing a missing watchlist row is a 400 and nothing is audited', async () => {
    const res = await removeWatch(req(undefined, RW, 'DELETE'), params(99))
    expect(res.status).toBe(400)
    expect((await res.json()).error).toBe('Watchlist entry 99 not found')
    expect(await prisma.audit_log.count()).toBe(0)
})

test('UI watchlist writes are audited as web, newest first in the activity list', async () => {
    const added = await addWatchedCompany({ source: 'lever', slug: 'beta', name: 'Beta' })
    expect(added.success).toBe(true)
    await removeWatchedCompany((added.data as { id: number }).id)
    const { items } = await getActivityTimeline()
    expect(items.map((a) => [a.actor, a.text])).toEqual([
        ['web', 'Removed board Beta'],
        ['web', 'Added board Beta'],
    ])
    await expect(addWatchedCompany({ source: 'lever', slug: 'x', name: 'X' }, 'root' as any))
        .rejects.toThrow('Invalid actor')
})

test('an unknown status on create is a 400, not a silent Applied', async () => {
    const res = await createApplication(req({ ...NEW_APP, status: 'Offerr' }, RW))
    expect(res.status).toBe(400)
    expect((await res.json()).error).toBe('Invalid status')
    expect(await prisma.applications.count()).toBe(0)
})

test('triage override: set, replace and clear, each audited with actor=mcp', async () => {
    const job = await prisma.job_postings.create({ data: makeJobPosting({ pipeline_status: 'new', source_content_revision: 3 }) })
    const set = await setTriage(req({ decision: 'keep', reason: 'operator wants it' }, RW), params(job.id))
    expect(set.status).toBe(200)
    const row = await prisma.job_triage_overrides.findUniqueOrThrow({ where: { job_posting_id: job.id } })
    expect([row.decision, row.reason, row.actor, row.source_content_revision]).toEqual(['keep', 'operator wants it', 'mcp', 3])
    expect((await setTriage(req({ decision: 'skip' }, RW), params(job.id))).status).toBe(200)
    expect((await prisma.job_triage_overrides.findUniqueOrThrow({ where: { job_posting_id: job.id } })).decision).toBe('skip')
    const cleared = await clearTriage(req(undefined, RW, 'DELETE'), params(job.id))
    expect(cleared.status).toBe(200)
    expect(await prisma.job_triage_overrides.count()).toBe(0)
    const log = await prisma.audit_log.findMany({ orderBy: { id: 'asc' } })
    expect(log.map((l) => [l.actor, l.action, l.entity, l.entity_id])).toEqual([
        ['mcp', 'add', 'job_triage_overrides', job.id],
        ['mcp', 'update', 'job_triage_overrides', job.id],
        ['mcp', 'remove', 'job_triage_overrides', job.id],
    ])
    // A replace or clear keeps the row it overwrote.
    expect(JSON.parse(log[1].payload).before.decision).toBe('keep')
    expect(JSON.parse(log[2].payload).decision).toBe('skip')
})

test('triage override rejects a bad decision, a missing job and a clear with nothing set', async () => {
    const job = await prisma.job_postings.create({ data: makeJobPosting() })
    const bad = await setTriage(req({ decision: 'maybe' }, RW), params(job.id))
    expect([bad.status, (await bad.json()).error]).toEqual([400, 'decision must be keep or skip'])
    const missing = await setTriage(req({ decision: 'keep' }, RW), params(999))
    expect([missing.status, (await missing.json()).error]).toEqual([400, 'Job 999 not found'])
    const none = await clearTriage(req(undefined, RW, 'DELETE'), params(job.id))
    expect([none.status, (await none.json()).error]).toEqual([400, `Job ${job.id} has no triage override`])
    const long = await setTriage(req({ decision: 'keep', reason: 'x'.repeat(501) }, RW), params(job.id))
    expect(long.status).toBe(400)
    expect(await prisma.audit_log.count()).toBe(0)
})

test('candidate profile: first set creates v1, a change bumps the version, a no-op writes nothing', async () => {
    const put = (body: unknown) => putProfile(req(body, RW, 'PUT'))
    const first = await put({ work_authorization: 'Needs Visa Sponsorship', locations: [' remote ', ''], title_include: ['engineer'] })
    expect(first.status).toBe(200)
    const v1 = (await first.json()).data
    expect([v1.version, v1.work_authorization, v1.locations, v1.title_include, v1.actor, v1.unchanged])
        .toEqual([1, 'needs visa sponsorship', ['remote'], ['engineer'], 'mcp', false])
    expect(v1.changed_at).toBeTruthy()

    const same = (await (await put({ locations: ['remote'] })).json()).data
    expect([same.version, same.unchanged]).toEqual([1, true])

    const v2 = (await (await put({
        education: [{ degree: "Master's", field: 'CS' }, { degree: "bachelor's", field: 'Math' }, { degree: '', field: '' }],
        experience: [{ title: 'SWE', company: 'Acme', years: 1.1 }, { title: 'TA', company: 'U', years: 2.2 }],
        exclude_internships: true, max_age_days: 30,
    })).json()).data
    expect([v2.version, v2.highest_degree, v2.total_years, v2.education.length, v2.max_age_days, v2.locations])
        .toEqual([2, "master's", 3.3, 2, 30, ['remote']])

    const log = await prisma.audit_log.findMany({ orderBy: { id: 'asc' } })
    expect(log.map((l) => [l.actor, l.action, l.entity, l.entity_id])).toEqual([
        ['mcp', 'add', 'candidate_profile', 1],
        ['mcp', 'update', 'candidate_profile', 1],
    ])
    expect(JSON.parse(log[1].payload).before.version).toBe(1)
})

test('candidate profile rejects off-vocabulary, wrong types, unknown fields and an empty body', async () => {
    const bad = async (body: unknown) => {
        const res = await putProfile(req(body, RW, 'PUT'))
        return [res.status, (await res.json()).error]
    }
    expect(await bad({ work_authorization: 'F-1 OPT' })).toEqual([400, expect.stringContaining('work_authorization must be blank or one of')])
    expect(await bad({ locations: 'remote' })).toEqual([400, 'locations must be a list'])
    expect(await bad({ exclude_internships: 'yes' })).toEqual([400, 'exclude_internships must be true or false'])
    expect(await bad({ education: [{ degree: 'BS' }] })).toEqual([400, expect.stringContaining('degree must be one of')])
    expect(await bad({ experience: [{ years: '2' }] })).toEqual([400, 'years must be a number from 0 to 60'])
    expect(await bad({ max_age_days: 1.5 })).toEqual([400, expect.stringContaining('max_age_days')])
    expect(await bad({ custom_packs: '{}' })).toEqual([400, expect.stringContaining('custom_packs can only be cleared')])
    expect(await bad({ custom_triage_context: { profile_text: '[1]', yoe_context: 'x' } })).toEqual([400, 'profile_text must be a JSON object'])
    expect(await bad({ custom_triage_context: { profile_text: '{}', yoe_context: '  ' } })).toEqual([400, 'yoe_context must not be empty'])
    expect(await bad({ highest_degree: 'PhD' })).toEqual([400, 'Unknown profile field(s): highest_degree'])
    expect(await bad({})).toEqual([400, 'No profile fields given'])
    expect((await putProfile(req({ locations: [] }, READ, 'PUT'))).status).toBe(403)
    expect(await prisma.candidate_profile.count()).toBe(0)
    expect(await prisma.audit_log.count()).toBe(0)
})

test('restating the worker-seeded values is a no-op (same bytes as profile.seed_values)', async () => {
    await prisma.$executeRawUnsafe(
        "INSERT INTO candidate_profile (id, work_authorization, locations, exclude_internships, education, experience, version, actor, updated_at) " +
        `VALUES (1, 'needs visa sponsorship', '["remote","Zürich"]', 1, '[{"degree":"master''s","field":""}]', ` +
        `'[{"title":"SWE","company":"A","years":2}]', 1, 'config', '2026-11-18T00:00:00Z')`)
    const res = await putProfile(req({ work_authorization: 'Needs Visa Sponsorship', locations: ['remote', 'Zürich'],
        exclude_internships: true, education: [{ degree: "master's", field: '' }],
        experience: [{ title: 'SWE', company: 'A', years: 2 }] }, RW, 'PUT'))
    const data = (await res.json()).data
    expect([data.unchanged, data.version, data.changed_at]).toEqual([true, 1, null])
    expect(await prisma.audit_log.count()).toBe(0)
})

const MIGRATED = { id: 1, custom_triage_context: JSON.stringify({ profile_text: '{"profile": {"a": 1}}', yoe_context: 'MS.' }),
    custom_packs: JSON.stringify({ preference_pack: '{"questions":[]}', yoe_pack: '{"questions":[]}' }),
    actor: 'migration', updated_at: '2026-11-19T00:00:00Z' }

test('a custom triage context is kept verbatim, restated as a no-op, and can be cleared with the packs', async () => {
    await prisma.candidate_profile.create({ data: MIGRATED })
    const put = async (body: unknown) => (await (await putProfile(req(body, RW, 'PUT'))).json()).data
    const text = '{\n  "profile": {"b": 2}  }\n'
    const v2 = await put({ custom_triage_context: { profile_text: text, yoe_context: '  MS, 1 year.  ' } })
    expect([v2.version, v2.unchanged, v2.packs, v2.triage_configured]).toEqual([2, false, 'custom', true])
    const row = await prisma.candidate_profile.findUniqueOrThrow({ where: { id: 1 } })
    expect(JSON.parse(row.custom_triage_context!)).toEqual({ profile_text: text, yoe_context: 'MS, 1 year.' })
    expect((await put({ custom_triage_context: { profile_text: text, yoe_context: 'MS, 1 year.' } })).unchanged).toBe(true)
    const v3 = await put({ custom_triage_context: null, custom_packs: null })
    expect([v3.version, v3.custom_triage_context, v3.packs, v3.triage_configured]).toEqual([3, null, 'default', false])
    const log = await prisma.audit_log.findMany({ orderBy: { id: 'asc' } })
    expect(log.map((l) => [l.actor, l.action, l.entity])).toEqual([['mcp', 'update', 'candidate_profile'], ['mcp', 'update', 'candidate_profile']])
    // The private pack texts never reach the audit payload.
    expect(log[1].payload).not.toContain('questions')
})

test('a non-JSON stored profile text can be restated with a new yoe_context, not replaced by other non-JSON', async () => {
    await prisma.candidate_profile.create({ data: { ...MIGRATED,
        custom_triage_context: JSON.stringify({ profile_text: 'free text', yoe_context: 'MS.' }) } })
    const put = async (body: unknown) => (await putProfile(req(body, RW, 'PUT'))).json()
    const ok = await put({ custom_triage_context: { profile_text: 'free text', yoe_context: 'MS, 2 years.' } })
    expect([ok.data.version, ok.data.custom_triage_context]).toEqual([2, { profile_text: 'free text', yoe_context: 'MS, 2 years.' }])
    expect((await put({ custom_triage_context: { profile_text: 'other text', yoe_context: 'x' } })).error).toBe('profile_text must be a JSON object')
})

test('an unknown key inside an education or experience entry is refused', async () => {
    const put = async (body: unknown) => (await putProfile(req(body, RW, 'PUT'))).json()
    expect((await put({ education: [{ degree: 'phd', school: 'X' }] })).error).toContain('takes only degree, field')
    expect((await put({ experience: [{ title: 'SWE', level: 'senior' }] })).error).toContain('takes only title, company, years')
})

test('watchlist add by careers URL resolves through the shared resolver (#208)', async () => {
    const res = await addWatch(req({ url: 'https://relx.wd3.myworkdayjobs.com/en-US/relx/job/X_R1', name: 'RELX' }, RW))
    expect(res.status).toBe(200)
    expect(await prisma.watched_companies.findFirstOrThrow()).toMatchObject({ source: 'workday', slug: 'relx/wd3/relx', name: 'RELX' })
    const custom = await addWatch(req({ url: 'https://www.acme.com/careers', name: 'Acme' }, RW))
    expect(custom.status).toBe(400)
    expect((await custom.json()).error).toMatch(/custom recipe .* onboard-board skill/)
    const both = await addWatch(req({ url: 'https://jobs.lever.co/x', source: 'lever', slug: 'x', name: 'X' }, RW))
    expect(both.status).toBe(400)
})

test('adding a browser board warns unless the latest pass recorded browser sources on (#233)', async () => {
    const recipe = JSON.stringify({ url: 'https://careers.example.com', item: 'li',
        fields: { title: 'a', external_id: 'a@href' } })
    const add = async (slug: string, extra: object = {}) =>
        (await (await addWatch(req({ source: 'browser', slug, name: 'Acme', recipe, ...extra }, RW))).json()).data
    const pass = (started_at: string, config_json: string) =>
        prisma.worker_runs.create({ data: { started_at, status: 'ok', config_json, counts_json: '{}', fetch_only: true, jev_enabled: false } })

    expect((await add('none')).warning).toMatch(/No worker pass has recorded .* skips this board unless it starts with enable_browser_sources/)
    await pass('2026-11-02T00:00:00.000Z', '{"browser_sources":true}')
    await pass('2026-11-01T00:00:00.000Z', '{"browser_sources":false}')  // an older pass, higher id
    expect(await add('on')).not.toHaveProperty('warning')
    await pass('2026-11-03T00:00:00.000Z', 'not json')
    expect((await add('unknown')).warning).toMatch(/No worker pass has recorded/)
    await pass('2026-11-04T00:00:00.000Z', '{"browser_sources":false}')
    expect((await add('off', { dry_run: true })).warning).toMatch(/were off in the latest worker pass/)
    expect((await add('off')).warning).toMatch(/were off in the latest worker pass/)
    expect(await prisma.watched_companies.count()).toBe(4)            // warned, never refused
    // Every other source is fetched whatever the flag says; the audit row holds the row alone.
    const known = (await (await addWatch(req({ source: 'lever', slug: 'acme', name: 'Acme' }, RW))).json()).data
    expect(known).not.toHaveProperty('warning')
    for (const a of await prisma.audit_log.findMany()) expect(a.payload).not.toContain('warning')
})

test('watchlist add validates a recipe against the recipe schema (#238)', async () => {
    const recipe = { url: 'https://boards.example.com/api/jobs', item_path: 'jobs', fields: { title: 'title', external_id: 'id' } }
    const add = (r: object) => addWatch(req({ source: 'custom', slug: 'acme', name: 'Acme', recipe: JSON.stringify(r) }, RW))
    const typo = await add({ ...recipe, item_path: undefined, item_pth: 'jobs' })
    expect(typo.status).toBe(400)
    expect((await typo.json()).error).toMatch(/invalid custom recipe: .*item_pth/)
    expect(await prisma.watched_companies.count()).toBe(0)
    expect((await add(recipe)).status).toBe(200)
})
