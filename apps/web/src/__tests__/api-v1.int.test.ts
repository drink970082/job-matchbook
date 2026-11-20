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
import { PUT as putPreferences } from '@/app/api/v1/preferences/route'
import { PUT as putJevProfile } from '@/app/api/v1/jev-profile/route'
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

test('removing a missing watchlist row is a 400 and nothing is audited', async () => {
    const res = await removeWatch(req(undefined, RW, 'DELETE'), params(99))
    expect(res.status).toBe(400)
    expect((await res.json()).error).toBe('Watchlist entry 99 not found')
    expect(await prisma.audit_log.count()).toBe(0)
})

test('UI watchlist writes are audited as web, newest first in the activity list', async () => {
    const added = await addWatchedCompany({ source: 'lever', slug: 'beta', name: 'Beta' })
    expect(added.success).toBe(true)
    await removeWatchedCompany(added.data!.id)
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

test('preferences: first set creates v1, a change bumps the version, a no-op writes nothing', async () => {
    const put = (body: unknown) => putPreferences(req(body, RW, 'PUT'))
    const first = await put({ work_authorization: 'Needs Visa Sponsorship', locations: [' remote ', ''] })
    expect(first.status).toBe(200)
    const v1 = (await first.json()).data
    expect([v1.version, v1.work_authorization, v1.locations, v1.actor, v1.unchanged]).toEqual([1, 'needs visa sponsorship', ['remote'], 'mcp', false])
    expect(v1.changed_at).toBeTruthy()

    const same = (await (await put({ locations: ['remote'] })).json()).data
    expect([same.version, same.unchanged]).toEqual([1, true])

    const v2 = (await (await put({ highest_degree: "Master's", exclude_internships: true, exclude_contract: true })).json()).data
    expect([v2.version, v2.highest_degree, v2.exclude_internships, v2.exclude_contract, v2.locations]).toEqual([2, "Master's", true, true, ['remote']])

    const log = await prisma.audit_log.findMany({ orderBy: { id: 'asc' } })
    expect(log.map((l) => [l.actor, l.action, l.entity, l.entity_id])).toEqual([
        ['mcp', 'add', 'candidate_preferences', 1],
        ['mcp', 'update', 'candidate_preferences', 1],
    ])
    expect(JSON.parse(log[1].payload).before.version).toBe(1)
})

test('preferences reject off-vocabulary, wrong types, unknown fields and an empty body', async () => {
    const bad = async (body: unknown) => {
        const res = await putPreferences(req(body, RW, 'PUT'))
        return [res.status, (await res.json()).error]
    }
    expect(await bad({ work_authorization: 'F-1 OPT' })).toEqual([400, expect.stringContaining('work_authorization must be blank or one of')])
    expect(await bad({ locations: 'remote' })).toEqual([400, 'locations must be a list of strings'])
    expect(await bad({ exclude_internships: 'yes' })).toEqual([400, 'exclude_internships must be true or false'])
    expect(await bad({ exclude_contract: 1 })).toEqual([400, 'exclude_contract must be true or false'])
    expect(await bad({ years_experience: 3 })).toEqual([400, 'Unknown preference field(s): years_experience'])
    expect(await bad({})).toEqual([400, 'No preference fields given'])
    expect((await putPreferences(req({ highest_degree: 'PhD' }, READ, 'PUT'))).status).toBe(403)
    expect(await prisma.candidate_preferences.count()).toBe(0)
    expect(await prisma.audit_log.count()).toBe(0)
})

test('restating the worker-seeded values is a no-op (same bytes as db.seed_preferences)', async () => {
    await prisma.$executeRawUnsafe(
        "INSERT INTO candidate_preferences (id, work_authorization, locations, exclude_internships, version, actor, updated_at) " +
        `VALUES (1, 'needs visa sponsorship', '["remote","Z\u00fcrich"]', 1, 1, 'config', '2026-11-18T00:00:00Z')`)
    const res = await putPreferences(req({ work_authorization: 'Needs Visa Sponsorship', locations: ['remote', 'Z\u00fcrich'], exclude_internships: true }, RW, 'PUT'))
    const data = (await res.json()).data
    expect([data.unchanged, data.version, data.changed_at]).toEqual([true, 1, null])
    expect(await prisma.audit_log.count()).toBe(0)
})

const SEEDED_JEV = { id: 1, profile_text: '{"profile": {"a": 1}}', c_pack: '{"questions":[]}', yoe_pack: '{"questions":[]}', yoe_context: 'MS.', actor: 'config', updated_at: '2026-11-19T00:00:00Z' }

test('jev profile: verbatim update bumps the version and audits; a restatement is a no-op', async () => {
    await prisma.jev_profile.create({ data: SEEDED_JEV })
    const put = async (body: unknown) => (await (await putJevProfile(req(body, RW, 'PUT'))).json()).data
    const text = '{\n  "profile": {"b": 2}  }\n'
    const v2 = await put({ profile_text: text, yoe_context: '  MS, 1 year.  ' })
    expect([v2.version, v2.unchanged]).toEqual([2, false])
    const row = await prisma.jev_profile.findUniqueOrThrow({ where: { id: 1 } })
    expect([row.profile_text, row.yoe_context, row.actor, row.c_pack]).toEqual([text, 'MS, 1 year.', 'mcp', SEEDED_JEV.c_pack])
    expect((await put({ yoe_context: 'MS, 1 year.' })).unchanged).toBe(true)
    const log = await prisma.audit_log.findMany()
    expect(log.map((l) => [l.actor, l.action, l.entity])).toEqual([['mcp', 'update', 'jev_profile']])
    expect(JSON.parse(log[0].payload).before.version).toBe(1)
})

test('jev profile rejects packs, non-object JSON, an empty body and a missing seed', async () => {
    const bad = async (body: unknown) => {
        const res = await putJevProfile(req(body, RW, 'PUT'))
        return [res.status, (await res.json()).error]
    }
    expect(await bad({ profile_text: '{}' })).toEqual([400, expect.stringContaining('No JEV profile is stored yet')])
    await prisma.jev_profile.create({ data: SEEDED_JEV })
    expect(await bad({ c_pack: '{}' })).toEqual([400, expect.stringContaining('question packs come from jev_dir')])
    expect(await bad({ profile_text: '[1]' })).toEqual([400, 'profile_text must be a JSON object'])
    expect(await bad({ profile_text: 'not json' })).toEqual([400, 'profile_text must be a JSON object'])
    expect(await bad({ yoe_context: '   ' })).toEqual([400, 'yoe_context must not be empty'])
    expect(await bad({})).toEqual([400, 'Give profile_text and/or yoe_context'])
    expect((await putJevProfile(req({ yoe_context: 'x' }, READ, 'PUT'))).status).toBe(403)
    expect((await prisma.jev_profile.findUniqueOrThrow({ where: { id: 1 } })).version).toBe(1)
    expect(await prisma.audit_log.count()).toBe(0)
})

test('jev profile form: a free-text profile needs the whole form; then partial updates merge', async () => {
    await prisma.jev_profile.create({ data: SEEDED_JEV })
    const put = async (form: unknown) => {
        const res = await putJevProfile(req({ form }, RW, 'PUT'))
        return [res.status, (await res.json())]
    }
    expect(await put({ target_roles: ['Backend'] })).toEqual([400, { error: expect.stringContaining('stored profile is free text') }])
    const full = { target_roles: ['Backend'], open_to: [], not_interested: ['Sales'],
        education: [{ degree: 'BS', field: 'CS' }], experience: [{ title: 'SWE', company: 'Acme', years: 2 }] }
    expect((await put(full))[0]).toBe(200)
    expect((await put({ open_to: ['Data'] }))[0]).toBe(200)          // merges over the stored form
    const row = await prisma.jev_profile.findUniqueOrThrow({ where: { id: 1 } })
    expect(JSON.parse(row.profile_text)).toMatchObject({ target_roles: ['Backend'], open_to: ['Data'], not_interested: ['Sales'] })
    expect(row.yoe_context).toContain('Total years of experience: 2.')
    expect(row.version).toBe(3)
    expect((await put({ open_to: ['Data'] }))[1].data.unchanged).toBe(true)  // same bytes
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
