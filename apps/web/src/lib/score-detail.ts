// Shared verdict formatting + score_detail parsing for JobDetailModal and
// DiscoveredJobsTable.
//
// `parseAssessment` below is the whole S2.1 scorecard, and both components read it
// identically — the modal renders it nested, the table flattens it into a one-line
// subline, but the extraction and coercion underneath are the same and now happen
// once.
//
// What is deliberately NOT unified is the TOP-LEVEL shaping each component layers on
// top, because the two genuinely disagree there and the difference is observable:
// for a non-string `recommended_resume` (say the number 5) the modal yields '' —
// `typeof p.recommended_resume === 'string' ? … : ''` — while the table yields '5'
// via `String(...)`. Same for `reasoning`, which the modal leaves undefined and the
// table coerces to ''. Picking a winner would change what one of them renders on
// malformed input, so each keeps its own rule and this comment records that they
// differ on purpose. See the deep-clean decision register.

// Verdict chip color: a clean match is green; a hard mismatch red; the in-between
// verdicts (too_junior / too_senior / adjacent) amber.
export function verdictClass(v: string): string {
    if (v === 'match') return 'bg-emerald-500/15 text-emerald-700 border-transparent'
    if (v === 'mismatch') return 'bg-red-500/15 text-red-700 border-transparent'
    return 'bg-amber-500/15 text-amber-700 border-transparent'
}

// Human label for a verdict token ("too_junior" → "Too junior", "adjacent" → "Adjacent").
export function verdictLabel(v: string): string {
    if (v === 'too_junior') return 'Too junior'
    if (v === 'too_senior') return 'Too senior'
    return v ? v.charAt(0).toUpperCase() + v.slice(1) : v
}

// Parse a job's raw score_detail JSON string into a plain object, tolerating null/
// undefined/empty input and malformed JSON. Callers layer their own view-model
// shaping on top of the returned object.
export function safeParseDetail(raw?: string | null): any | null {
    if (!raw) return null
    try {
        const p = JSON.parse(raw)
        return p && typeof p === 'object' ? p : null
    } catch {
        return null
    }
}

export interface Verdict {
    verdict: string
    note: string
}

// The S2.1 fit scorecard — per-dimension verdicts that supersede the flat
// matched/missing keyword lists + prose reasoning (both kept as a legacy fallback by
// the modal).
export interface Assessment {
    seniority: Verdict
    domain: Verdict
    mustHaves: { met: string[]; missing: string[] }
    niceToHaves: { missing: string[] }
    summary: string
}

// Normalize the `assessment` object out of a parsed score_detail. Returns null for a
// pre-S2.1 row (or any non-object), which is the signal both callers use to fall back:
// the modal to the keyword lists, the table to the disqualification reason.
//
// Every field is coerced, never trusted: this is worker-written JSON describing an
// LLM's output, so a missing verdict must read as '' rather than crash a render.
export function parseAssessment(a: any): Assessment | null {
    if (!a || typeof a !== 'object') return null
    const verdict = (v: any): Verdict => ({
        verdict: String(v?.verdict ?? ''),
        note: String(v?.note ?? ''),
    })
    const list = (x: any): string[] => (Array.isArray(x) ? x.map(String) : [])
    return {
        seniority: verdict(a.seniority),
        domain: verdict(a.domain),
        mustHaves: { met: list(a.must_haves?.met), missing: list(a.must_haves?.missing) },
        niceToHaves: { missing: list(a.nice_to_haves?.missing) },
        summary: String(a.summary ?? ''),
    }
}
