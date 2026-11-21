import type { Prisma } from '@prisma/client'
import { ACTORS, type Actor } from '@/lib/constants'

// The company/title text filter. Returns {} for an empty search so it can sit
// unconditionally in an AND array — the shape all three call sites already used when
// each spelled it out. Structurally valid for both `applications` and `job_postings`,
// which is why it is not typed to either.
export function searchClause(search: string) {
    return search
        ? { OR: [{ company_name: { contains: search } }, { job_title: { contains: search } }] }
        : {}
}

// Category label for a posting/application whose category is blank or absent. A fixed
// sentinel, deliberately NOT read from DEFAULT_CATEGORIES: that list is the seed for a
// user-editable vocabulary and can legitimately stop containing 'Others', while this
// fallback must not move with it.
export const CATEGORY_FALLBACK = 'Others'

// Server Actions are callable with arbitrary arguments, so the actor is checked, not trusted.
export function checkedActor(actor: unknown): Actor {
    if (!(ACTORS as readonly unknown[]).includes(actor)) throw new Error('Invalid actor')
    return actor as Actor
}

// applications.status is the status of the latest status_history row by timestamp, ties
// by id (#243) - not "whichever row was written last", so a backdated change does not
// become current. 'Applied' when no row remains. Every status write ends with this;
// returns the updated row (the audit `after` snapshot). `data` rides the same update.
export async function syncStatusFromHistory(tx: Prisma.TransactionClient, applicationId: number,
    data: Prisma.applicationsUpdateInput = {}) {
    const latest = await tx.status_history.findFirst({
        where: { application_id: applicationId }, orderBy: [{ timestamp: 'desc' }, { id: 'desc' }] })
    return tx.applications.update({ where: { id: applicationId }, data: { ...data, status: latest?.status ?? 'Applied' } })
}

// An application's first history: an Applied row at the start of date_applied (UTC),
// never later than now, so a same-day change (dated noon, or now) sorts after it; a
// date_applied that does not start YYYY-MM-DD (CSV and /api/v1 take any string) is
// stamped now.
// A non-Applied creation status gets a second row on the same timestamp; its later id
// makes it current.
export async function writeInitialHistory(tx: Prisma.TransactionClient,
    app: { id: number; date_applied: string; status: string; actor: string }) {
    const now = new Date().toISOString()
    const day = /^\d{4}-\d{2}-\d{2}(T|$)/.test(app.date_applied) ? app.date_applied.slice(0, 10) : null
    const start = day ? `${day}T00:00:00.000Z` : now
    const timestamp = start < now ? start : now
    for (const status of app.status === 'Applied' ? ['Applied'] : ['Applied', app.status]) {
        await tx.status_history.create({ data: { application_id: app.id, status, timestamp, actor: app.actor } })
    }
}

// One audit_log row for an application write (#242). Actions: add | update | status |
// remove_history | remove. The payload is the row as added/removed, or {before, after}.
export function applicationAudit(actor: Actor, action: string, entityId: number, payload: unknown) {
    return {
        at: new Date().toISOString(), actor, action,
        entity: 'applications', entity_id: entityId, payload: JSON.stringify(payload),
    }
}
