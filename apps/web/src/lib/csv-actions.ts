'use server'

import { prisma } from '@/lib/db'
import { LEGACY_STATUS_MAP, STATUSES } from '@/lib/constants'
import { applicationAudit, CATEGORY_FALLBACK } from '@/lib/action-helpers'

const CSV_COLUMNS = [
    'company_name',
    'job_title',
    'application_url',
    'date_applied',
    'category',
    'status',
    'notes',
    'last_updated',
] as const

function csvEscape(value: string | null | undefined): string {
    if (value === null || value === undefined) return ''
    let s = String(value)
    // Formula-injection + reversibility guard: a cell whose first char is one a spreadsheet
    // may treat as a formula lead (= + - @, or a tab/CR) — OR a cell that already starts with
    // `'` — is prefixed with a single quote so Excel/Sheets render it as literal text. Guarding
    // a leading `'` too (not just formula-lead chars) makes this a proper bijection with get()'s
    // strip below: every value, including ones that start with an apostrophe, round-trips
    // losslessly through export -> import. Prefix BEFORE the quote check so a comma-bearing
    // cell still gets wrapped.
    if (/^['=+\-@\t\r]/.test(s)) s = "'" + s
    if (/[",\r\n]/.test(s)) {
        return `"${s.replace(/"/g, '""')}"`
    }
    return s
}

function parseCSV(text: string): string[][] {
    const rows: string[][] = []
    let row: string[] = []
    let field = ''
    let inQuotes = false
    let i = 0
    while (i < text.length) {
        const ch = text[i]
        if (inQuotes) {
            if (ch === '"') {
                if (text[i + 1] === '"') {
                    field += '"'
                    i += 2
                    continue
                }
                inQuotes = false
                i++
                continue
            }
            field += ch
            i++
            continue
        }
        if (ch === '"') {
            inQuotes = true
            i++
            continue
        }
        if (ch === ',') {
            row.push(field)
            field = ''
            i++
            continue
        }
        if (ch === '\r') {
            i++
            continue
        }
        if (ch === '\n') {
            row.push(field)
            rows.push(row)
            row = []
            field = ''
            i++
            continue
        }
        field += ch
        i++
    }
    if (field.length > 0 || row.length > 0) {
        row.push(field)
        rows.push(row)
    }
    return rows.filter((r) => r.length > 0 && !(r.length === 1 && r[0] === ''))
}

export async function exportApplicationsCSV() {
    try {
        const apps = await prisma.applications.findMany({
            orderBy: { date_applied: 'desc' },
        })

        const header = CSV_COLUMNS.join(',')
        const lines = apps.map((app) =>
            CSV_COLUMNS.map((col) => csvEscape((app as any)[col])).join(',')
        )

        const csv = [header, ...lines].join('\n') + '\n'
        return { success: true, csv, count: apps.length }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function importApplicationsCSV(csvText: string) {
    try {
        const rows = parseCSV(csvText)
        if (rows.length === 0) {
            return { success: false, error: 'CSV is empty' }
        }

        const header = rows[0].map((h) => h.trim())
        const dataRows = rows.slice(1)

        const required = ['company_name', 'job_title', 'date_applied']
        for (const r of required) {
            if (!header.includes(r)) {
                return { success: false, error: `Missing required column: ${r}` }
            }
        }

        const colIndex = (name: string) => header.indexOf(name)
        const statusSet = new Set<string>(STATUSES as readonly string[])

        const CHUNK = 100
        let added = 0
        let skipped = 0
        const errors: string[] = []

        for (let start = 0; start < dataRows.length; start += CHUNK) {
            const batch = dataRows.slice(start, start + CHUNK)

            const r = await prisma.$transaction(async (tx) => {
                let a = 0
                let s = 0
                const e: string[] = []

                for (let j = 0; j < batch.length; j++) {
                    const row = batch[j]
                    const rowNum = start + j + 2

                    const get = (col: string) => {
                        const idx = colIndex(col)
                        if (idx === -1) return ''
                        let v = (row[idx] ?? '').trim()
                        // Reverse csvEscape's guard: strip a single leading `'` only when the
                        // rest of the value also starts with a formula-lead char or another `'`
                        // — the exact inverse of the export-side prepend above, so a value that
                        // never went through csvEscape (e.g. "O'Brien", no guard char following
                        // the `'`) is left untouched, while a guarded value (including one whose
                        // original first char was itself `'`) round-trips exactly.
                        if (v[0] === "'" && /^['=+\-@\t\r]/.test(v.slice(1))) v = v.slice(1)
                        return v
                    }

                    const company_name = get('company_name')
                    const job_title = get('job_title')
                    const date_applied = get('date_applied')

                    if (!company_name || !job_title || !date_applied) {
                        e.push(`Row ${rowNum}: missing required field`)
                        continue
                    }

                    const existing = await tx.applications.findFirst({
                        where: { company_name, job_title },
                    })
                    if (existing) {
                        s++
                        continue
                    }

                    const rawStatus = get('status') || 'Applied'
                    // An export from before #205 carries the old 14 names; map them.
                    const status = statusSet.has(rawStatus) ? rawStatus : LEGACY_STATUS_MAP[rawStatus] ?? 'Applied'
                    // Category is free-form (the user's own vocabulary) — keep whatever
                    // the CSV supplies, defaulting only when blank.
                    const category = (get('category') || '').trim() || CATEGORY_FALLBACK

                    const created = await tx.applications.create({
                        data: {
                            company_name,
                            job_title,
                            date_applied,
                            category,
                            status,
                            application_url: get('application_url') || '',
                            notes: get('notes') || '',
                            last_updated: new Date().toISOString(),
                        },
                    })
                    await tx.audit_log.create({ data: applicationAudit('web', 'add', created.id, created) })
                    a++
                }

                return { a, s, e }
            }, { timeout: 15_000 })

            added += r.a
            skipped += r.s
            errors.push(...r.e)
        }

        return { success: true, added, skipped, errors }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}
