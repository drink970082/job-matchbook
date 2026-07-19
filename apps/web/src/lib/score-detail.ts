// Shared verdict formatting + score_detail JSON parsing used by JobDetailModal and
// DiscoveredJobsTable. Each component still owns its own view-model shaping
// (parseScoreDetail / parseDetail) — this module only extracts the genuinely
// duplicated leaf helpers.

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
