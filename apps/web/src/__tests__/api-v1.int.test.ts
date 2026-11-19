/**
 * The key-scoped loopback write API (/api/v1/*). Route handlers are called directly
 * against the throwaway integration DB; they wrap lib/actions.ts, so these tests pin
 * the auth contract and that the API and the UI share one validation path.
 */
import { POST as createApplication } from '@/app/api/v1/applications/route'
import { PATCH as patchApplication } from '@/app/api/v1/applications/[id]/route'
import { POST as postStatus } from '@/app/api/v1/applications/[id]/status/route'
import { POST as postApplied } from '@/app/api/v1/jobs/[id]/applied/route'
import { POST as addWatch } from '@/app/api/v1/watchlist/route'
import { DELETE as removeWatch } from '@/app/api/v1/watchlist/[id]/route'
import { updateApplicationStatus } from '@/lib/actions'
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
    const res = await postStatus(req({ status: 'Phone Screen', date: '2026-11-17' }, RW), params(app.id))
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

test('watchlist add and remove', async () => {
    const res = await addWatch(req({ source: 'greenhouse', slug: 'acme', name: 'Acme' }, RW))
    expect(res.status).toBe(200)
    const row = await prisma.watched_companies.findFirstOrThrow()
    expect((await removeWatch(req(undefined, RW, 'DELETE'), params(row.id))).status).toBe(200)
    expect(await prisma.watched_companies.count()).toBe(0)
})

test('an unknown status on create is a 400, not a silent Applied', async () => {
    const res = await createApplication(req({ ...NEW_APP, status: 'Offerr' }, RW))
    expect(res.status).toBe(400)
    expect((await res.json()).error).toBe('Invalid status')
    expect(await prisma.applications.count()).toBe(0)
})
