import { createHash, timingSafeEqual } from 'node:crypto'
import { NextResponse } from 'next/server'

// The key-scoped loopback write API (/api/v1/*, SPEC §8). The MCP server writes
// through it so the lib/*-actions.ts validation exists once. Keys come from the env:
// ATS_API_KEY_READ (scope read) and ATS_API_KEY_READ_WRITE (scope read_write).
// No key configured -> 503: the API is disabled, never open.
export type Scope = 'read' | 'read_write'

const digest = (s: string) => createHash('sha256').update(s).digest()
const same = (a: string, b: string) => timingSafeEqual(digest(a), digest(b))

export function authorize(req: Request, need: Scope): NextResponse | null {
    const rw = process.env.ATS_API_KEY_READ_WRITE || ''
    const read = process.env.ATS_API_KEY_READ || ''
    if (!rw && !read) return NextResponse.json({ error: 'API disabled: no key configured' }, { status: 503 })
    const m = /^Bearer (.+)$/.exec(req.headers.get('authorization') || '')
    const key = m?.[1] ?? ''
    const scope: Scope | null = rw && same(key, rw) ? 'read_write' : read && same(key, read) ? 'read' : null
    if (!scope) return NextResponse.json({ error: 'Invalid or missing API key' }, { status: 401 })
    if (need === 'read_write' && scope !== 'read_write') {
        return NextResponse.json({ error: 'Key lacks read_write scope' }, { status: 403 })
    }
    return null
}

type Result = { success: boolean; error?: string; data?: unknown }

// Auth -> parse -> run one action -> map {success:false} to 400. The action's own
// error text is returned as-is so the API reports exactly what the UI would.
export async function write(
    req: Request,
    run: (body: Record<string, unknown>) => Promise<Result>,
    hasBody = true,
): Promise<NextResponse> {
    const denied = authorize(req, 'read_write')
    if (denied) return denied
    let body: Record<string, unknown> = {}
    if (hasBody) {
        try {
            const parsed = await req.json()
            if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
            body = parsed
        } catch {
            return NextResponse.json({ error: 'Body must be a JSON object' }, { status: 400 })
        }
    }
    try {
        const res = await run(body)
        return res.success
            ? NextResponse.json({ data: res.data ?? null })
            : NextResponse.json({ error: res.error }, { status: 400 })
    } catch (e: any) {
        return NextResponse.json({ error: e.message }, { status: 400 })
    }
}

// The read routes: the same auth at read scope, {success:false} -> 400.
export async function read(req: Request, run: () => Promise<Result>): Promise<NextResponse> {
    const denied = authorize(req, 'read')
    if (denied) return denied
    try {
        const res = await run()
        return res.success
            ? NextResponse.json({ data: res.data ?? null })
            : NextResponse.json({ error: res.error }, { status: 400 })
    } catch (e: any) {
        return NextResponse.json({ error: e.message }, { status: 400 })
    }
}

export function idParam(id: string): number {
    if (!/^\d+$/.test(id)) throw new Error('id must be a positive integer')
    return Number(id)
}

// Optional string fields only: anything else is rejected rather than coerced.
export function str(body: Record<string, unknown>, key: string): string | undefined {
    const v = body[key]
    if (v === undefined || v === null) return undefined
    if (typeof v !== 'string') throw new Error(`${key} must be a string`)
    return v
}

export function int(body: Record<string, unknown>, key: string): number | undefined {
    const v = body[key]
    if (v === undefined || v === null) return undefined
    if (!Number.isInteger(v) || (v as number) < 1) throw new Error(`${key} must be a positive integer`)
    return v as number
}

export function bool(body: Record<string, unknown>, key: string): boolean | undefined {
    const v = body[key]
    if (v === undefined || v === null) return undefined
    if (typeof v !== 'boolean') throw new Error(`${key} must be a boolean`)
    return v
}
