// Parse a job's raw score_detail JSON string into a plain object, tolerating null/
// undefined/empty input and malformed JSON. JobDetailModal reads the screen half of it;
// the retired fit scorer's fields in older rows are not shown anywhere.
export function safeParseDetail(raw?: string | null): any | null {
    if (!raw) return null
    try {
        const p = JSON.parse(raw)
        return p && typeof p === 'object' ? p : null
    } catch {
        return null
    }
}
