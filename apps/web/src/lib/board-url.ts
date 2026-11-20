// A careers or job URL -> the watchlist (source, slug) (#208). The TS port of the
// worker's feed/resolve.py shapes, widened to board URLs (no job id), for the sources a
// watchlist row can hold. One fixture (worker/tests/fixtures/board-url-cases.json) runs
// in both suites so the two resolvers cannot drift on the shapes they share. Pure: no
// I/O, so the Sources form resolves as the user types and /api/v1/watchlist reuses it.

export interface ResolvedBoard { source: string; slug: string }

const GREENHOUSE_HOSTS = new Set(['boards.greenhouse.io', 'job-boards.greenhouse.io', 'job-boards.eu.greenhouse.io'])
const SLUG_FIRST_HOSTS: Record<string, string> = {
    'jobs.lever.co': 'lever',
    'jobs.ashbyhq.com': 'ashby',
    'jobs.smartrecruiters.com': 'smartrecruiters',
    'careers.smartrecruiters.com': 'smartrecruiters',
    'apply.workable.com': 'workable',
}
// Boards addressed by a subdomain: {slug}.pinpointhq.com, {slug}.icims.com.
const SUBDOMAIN_HOSTS: Record<string, string> = { 'pinpointhq.com': 'pinpoint', 'icims.com': 'icims' }
const LOCALE = /^[a-z]{2}(-[A-Za-z]{2})?$/
// The watchlist's slug rule (addWatchedCompany): a resolved slug outside it, e.g. an
// Ashby "Initech%20Inc", is not offered as resolvable.
export const SLUG_OK = (slug: string) => /^[A-Za-z0-9._/-]+$/.test(slug) && !slug.includes('..')
    && !slug.startsWith('/') && !slug.endsWith('/') && !slug.includes('//')
// First path segments that are a route on the host, not a company slug.
const NOT_A_SLUG = new Set(['j', 'embed', 'oneclick-ui', 'wday', 'api', 'jobs'])

function decode(s: string): string | null {
    try { return decodeURIComponent(s) } catch { return null }
}

export function resolveBoardUrl(raw: string | null | undefined): ResolvedBoard | null {
    let u: URL
    try {
        u = new URL(String(raw ?? '').trim())
    } catch {
        return null
    }
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return null
    const host = u.hostname.toLowerCase()
    const parts = u.pathname.split('/').filter(Boolean)
    // Single-segment slugs never contain '/' (a decoded %2F); workday's is built below.
    const board = (source: string, slug: string | null | undefined, multi = false) =>
        (slug && SLUG_OK(slug) && (multi || !slug.includes('/')) && !NOT_A_SLUG.has(slug) ? { source, slug } : null)

    if (GREENHOUSE_HOSTS.has(host)) {
        // boards.greenhouse.io/embed/job_board?for=acme names the board in a query param.
        if (parts[0] === 'embed') return board('greenhouse', u.searchParams.get('for'))
        return board('greenhouse', parts[0] && decode(parts[0]))
    }
    if (SLUG_FIRST_HOSTS[host]) return board(SLUG_FIRST_HOSTS[host], parts[0] && decode(parts[0]))

    for (const [suffix, source] of Object.entries(SUBDOMAIN_HOSTS)) {
        if (host.endsWith(`.${suffix}`)) {
            const sub = host.slice(0, -suffix.length - 1)
            return board(source, sub && !sub.includes('.') && sub !== 'www' ? sub : null)
        }
    }

    // {tenant}.{dc}.myworkdayjobs.com/[locale/]{site}[/job/...] -> "tenant/dc/site": the
    // site is the segment before `job` (as resolve.py), else the first non-locale segment.
    if (host.endsWith('.myworkdayjobs.com')) {
        const labels = host.split('.')
        if (labels.length < 4 || !labels[0] || !labels[1]) return null
        const job = parts.indexOf('job')
        const site = job > 0 ? parts[job - 1] : parts.find((p) => !LOCALE.test(p))
        return site && !LOCALE.test(site) && !NOT_A_SLUG.has(site) && !site.includes('/')
            ? board('workday', `${labels[0]}/${labels[1]}/${site}`, true) : null
    }
    return null
}

// A display name from a slug: "acme-robotics" -> "Acme Robotics"; workday uses the tenant.
export function nameFromSlug(slug: string): string {
    const base = slug.split('/')[0]
    return base.replace(/[-_.]+/g, ' ').trim().replace(/\b\w/g, (c) => c.toUpperCase())
}
