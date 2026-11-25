// Does this application belong to this posting? (#241). Pure, the only implementation:
// the web form, Mark Applied and the /api/v1 suggest route (MCP) all call it.
//
//   tier 1  same posting: the two URLs identify the same page
//   tier 2  same company and the same title, normalized
//   tier 3  same company, another title: a picker, never a suggestion
//
// A tier is a suggestion for one human click; nothing is ever linked by it. Title
// similarity is not a match signal (in the sample, every company-matched pair at
// 0.55-0.83 was a different role): it only orders the tier-3 picker. There is no date
// gate: a posting is often first fetched after the apply date.

export type MatchTier = 1 | 2 | 3
export interface MatchApplication { company_name: string; job_title: string; application_url?: string | null }
export interface MatchPosting { company_name: string; job_title: string; job_url?: string | null }

// "D.E. Shaw", "D. E. Shaw" and "DE Shaw" are one name: dots and apostrophes vanish and
// runs of single letters join. Other punctuation separates words.
function words(raw: string): string[] {
    const flat = raw.normalize('NFKC').toLowerCase().replace(/&/g, ' and ').replace(/[.'’]/g, '')
    const out: string[] = []
    let joined = false
    for (const w of flat.split(/[^\p{L}\p{M}\p{N}]+/u).filter(Boolean)) {
        const single = /^\p{L}$/u.test(w)
        if (single && joined) out[out.length - 1] += w
        else out.push(w)
        joined = single
    }
    return out
}

const LEGAL = new Set(['inc', 'incorporated', 'llc', 'ltd', 'limited', 'corp', 'corporation', 'co', 'company',
    'lp', 'plc', 'group', 'holdings', 'technologies', 'the', 'and']) // 'and' is left by "& Co."

// Legal words go from the end (and a leading "the"); a name made only of them keeps one.
export function normalizeCompany(raw: string): string {
    const w = words(raw)
    if (w.length > 1 && w[0] === 'the') w.shift()
    while (w.length > 1 && LEGAL.has(w[w.length - 1])) w.pop()
    return w.join(' ')
}

// Equal, or one name inside the other on word boundaries ("Point72" in "Point72 Asset
// Management").
export function sameCompany(a: string, b: string): boolean {
    return sameName(normalizeCompany(a), normalizeCompany(b))
}

function sameName(x: string, y: string): boolean {
    return !!x && !!y && (` ${x} `.includes(` ${y} `) || ` ${y} `.includes(` ${x} `))
}

// Parentheticals are kept as words, and so are + and #: "(C++)" and "(C#)" and
// "(Python)" can be different requisitions.
export function normalizeTitle(raw: string): string {
    return raw.normalize('NFKC').toLowerCase().replace(/['’]/g, '').split(/[^\p{L}\p{M}\p{N}+#]+/u).filter(Boolean).join(' ')
}

const TRACKING = /^(utm_.*|gh_src|src|source|ref|referrer|lever-source.*|lever-origin)$/i

// The page a URL names: scheme, trailing slash and tracking parameters dropped. Query
// values and a fragment holding a digit are kept: many boards carry the posting id there
// (`/careers?gh_jid=123`, `/#/jobs/123`), and without it every posting of the board is
// one URL.
export function urlIdentity(raw: string | null | undefined): string | null {
    let u: URL
    try {
        u = new URL(String(raw ?? '').trim())
    } catch {
        return null
    }
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return null
    const ids = [...u.searchParams].filter(([k, v]) => /\d/.test(v) && !TRACKING.test(k))
        .map(([k, v]) => `${k}=${v}`).sort()
    return `${u.host}${u.pathname.replace(/\/+$/, '')}?${ids.join('&')}${/\d/.test(u.hash) ? u.hash : ''}`
}

// Each row is normalized once, however many rows it is compared with (the whole-list view
// is every unlinked application against every stored posting).
interface Keys { url: string | null; company: string; title: string }
const cache = new WeakMap<object, Keys>()
function keysOf(row: { company_name: string; job_title: string }, url: string | null | undefined): Keys {
    let k = cache.get(row)
    if (!k) {
        k = { url: urlIdentity(url), company: normalizeCompany(row.company_name), title: normalizeTitle(row.job_title) }
        cache.set(row, k)
    }
    return k
}

export function matchTier(app: MatchApplication, posting: MatchPosting): MatchTier | null {
    const a = keysOf(app, app.application_url)
    const p = keysOf(posting, posting.job_url)
    if (a.url && a.url === p.url) return 1
    if (!sameName(a.company, p.company)) return null
    return a.title && a.title === p.title ? 2 : 3
}

// Shared words over all words (Dice), for ordering only.
export function titleSimilarity(a: string, b: string): number {
    const x = new Set(normalizeTitle(a).split(' '))
    const y = new Set(normalizeTitle(b).split(' '))
    return (2 * [...x].filter((w) => y.has(w)).length) / (x.size + y.size)
}

// The postings an application may belong to, best first: tier, then title similarity,
// then newest.
export function rankPostings<P extends MatchPosting & { id: number }>(app: MatchApplication, postings: P[]): Array<P & { tier: MatchTier }> {
    return postings.flatMap((p) => {
        const tier = matchTier(app, p)
        return tier ? [{ ...p, tier, score: titleSimilarity(app.job_title, p.job_title) }] : []
    }).sort((a, b) => a.tier - b.tier || b.score - a.score || b.id - a.id)
        .map(({ score: _s, ...p }) => p as unknown as P & { tier: MatchTier })
}

// The application a posting is probably already recorded as: tier 1 or 2 only.
export function bestApplication<A extends MatchApplication & { id: number }>(posting: MatchPosting, apps: A[]): (A & { tier: 1 | 2 }) | null {
    let best: (A & { tier: 1 | 2 }) | null = null
    for (const a of apps) {
        const tier = matchTier(a, posting)
        if ((tier === 1 || tier === 2) && (!best || tier < best.tier || (tier === best.tier && a.id > best.id))) best = { ...a, tier }
    }
    return best
}
