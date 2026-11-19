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
