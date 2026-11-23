'use client'

import { useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Pagination } from './Pagination'
import { addWatchedCompany, removeWatchedCompany } from '@/lib/watchlist-actions'
import { nameFromSlug, resolveBoardUrl } from '@/lib/board-url'
import { toast } from 'sonner'
import { Trash2 } from 'lucide-react'
import { BOARD_HEALTH, type BoardHealth } from '@/lib/board-health'

export interface WatchedSource {
    id: number
    source: string
    slug: string
    name: string
    created_at?: string
    postings_30d: number
    health: BoardHealth
    last_fetched_at: string | null
    last_fetch_status: string | null
    last_fetched: number | null
    last_kept: number | null
    last_new: number | null
    last_bodyless: number | null
    last_desc_median: number | null
}

const PAGE_SIZE = 25
type Sort = { key: 'name' | 'postings_30d'; dir: 'asc' | 'desc' }

// The last worker pass per board (#231): what it says, and whether it needs a look.
const HEALTH_LABEL: Record<BoardHealth, string> = {
    never_fetched: 'Never fetched', disabled: 'Browser sources off', fetch_failed: 'Fetch failed', empty: 'Board listed nothing',
    kept_zero: 'Filters kept 0', teaser: 'Teaser descriptions', ok: 'Healthy',
}
const ATTENTION: readonly BoardHealth[] = ['fetch_failed', 'empty', 'kept_zero', 'teaser']

function LastFetch({ s }: { s: WatchedSource }) {
    const at = s.last_fetched_at ? `Last pass ${s.last_fetched_at}` : 'Fetched on the next worker pass'
    const bodyless = s.last_bodyless ? `, ${s.last_bodyless} without a description` : ''
    const [text, tone, hint] = {
        never_fetched: ['Never fetched', 'text-muted-foreground', at],
        disabled: ['Not fetched: browser sources are off', 'text-muted-foreground',
            'The worker skips browser-recipe boards unless enable_browser_sources is on in config.yaml'],
        fetch_failed: [`Fetch failed: ${s.last_fetch_status}`, 'text-red-600',
            `${at}. A 404 is usually a wrong slug, or the company moved platforms`],
        empty: ['Board listed nothing', 'text-amber-600', `${at}. Usually a wrong slug, or the company moved platforms`],
        kept_zero: [`${s.last_fetched} listed, filters kept 0`, 'text-muted-foreground',
            `${at}. Your title and age filters matched none of this board's postings`],
        teaser: [`Teaser descriptions (median ${s.last_desc_median} chars)`, 'text-amber-600',
            `${at}. The board serves summaries, not full descriptions; it may need a detail step`],
        ok: [`${s.last_fetched} listed, ${s.last_kept} kept, ${s.last_new} new`, 'text-muted-foreground', at],
    }[s.health]
    return <span className={tone} title={hint}>{text}{s.health === 'ok' || s.health === 'teaser' ? bodyless : ''}</span>
}

// Add a board by pasting its careers or job URL (#208). Resolution is pure (lib/board-url.ts,
// the same resolver /api/v1/watchlist runs for MCP), so it updates as the user types.
function AddBoard({ onAdded }: { onAdded: () => void }) {
    const [url, setUrl] = useState('')
    const [name, setName] = useState('')
    const [nameEdited, setNameEdited] = useState(false)
    const [saving, setSaving] = useState(false)
    const resolved = url.trim() ? resolveBoardUrl(url) : null

    const change = (v: string) => {
        setUrl(v)
        const r = resolveBoardUrl(v)
        // A different board (or none) discards the name typed for the previous one.
        const changed = `${r?.source}/${r?.slug}` !== `${resolved?.source}/${resolved?.slug}`
        if (!nameEdited || changed) {
            setName(r ? nameFromSlug(r.slug) : '')
            setNameEdited(false)
        }
    }
    const add = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!resolved || !name.trim() || saving) return
        setSaving(true)
        try {
            const result = await addWatchedCompany({ url, name })
            if (!result.success) return toast.error(result.error)
            toast.success(`Added ${name}: fetched on the next worker pass`)
            setUrl('')
            setName('')
            setNameEdited(false)
            onAdded()
        } catch (err: any) {
            toast.error(err?.message ?? 'Could not add the board')
        } finally {
            setSaving(false)
        }
    }

    return (
        <form className="space-y-2" onSubmit={add}>
            <div className="flex flex-wrap gap-2">
                <Input aria-label="Careers or job URL" placeholder="Paste a careers or job URL, e.g. https://boards.greenhouse.io/acme"
                    value={url} onChange={(e) => change(e.target.value)} className="flex-[2] min-w-[18rem]" />
                <Input aria-label="Company name" placeholder="Company name" value={name}
                    onChange={(e) => { setName(e.target.value); setNameEdited(true) }} disabled={!resolved} className="flex-1 min-w-[10rem]" />
                <Button type="submit" disabled={!resolved || !name.trim() || saving}>Add board</Button>
            </div>
            {url.trim() && (
                <p className="text-xs text-muted-foreground">
                    {resolved
                        ? `${resolved.source} board "${resolved.slug}"`
                        : 'This site needs a custom recipe - set it up from your AI client with the onboard-board skill.'}
                </p>
            )}
        </form>
    )
}

// What the worker fetches (#208): search, source and last-fetch health filters, sortable
// Company and Postings (30d), 25 per page, add by URL, remove with a confirm.
export function SourcesTab({ sources }: { sources: WatchedSource[] }) {
    const router = useRouter()
    const [search, setSearch] = useState('')
    const [source, setSource] = useState('')
    const [health, setHealth] = useState('')
    const [sort, setSort] = useState<Sort>({ key: 'name', dir: 'asc' })
    const [page, setPage] = useState(0)

    const sourceOptions = useMemo(() => [...new Set(sources.map((s) => s.source))].sort(), [sources])
    const rows = useMemo(() => {
        const q = search.trim().toLowerCase()
        const out = sources.filter((s) => (!q || s.name.toLowerCase().includes(q))
            && (!source || s.source === source)
            && (!health || (health === 'attention' ? ATTENTION.includes(s.health) : s.health === health)))
        const sign = sort.dir === 'asc' ? 1 : -1
        return out.sort((a, b) => sign * (sort.key === 'name'
            ? a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
            : a.postings_30d - b.postings_30d) || a.id - b.id)
    }, [sources, search, source, health, sort])
    const last = Math.max(0, Math.ceil(rows.length / PAGE_SIZE) - 1)
    const shown = rows.slice(Math.min(page, last) * PAGE_SIZE, (Math.min(page, last) + 1) * PAGE_SIZE)
    const filter = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPage(0) }

    const remove = async (s: WatchedSource) => {
        if (!window.confirm(`Stop fetching ${s.name} (${s.source})? Postings already fetched stay.`)) return
        let result: Awaited<ReturnType<typeof removeWatchedCompany>>
        try { result = await removeWatchedCompany(s.id) } catch (err: any) { return toast.error(err?.message ?? 'Could not remove the board') }
        if (!result.success) return toast.error(result.error)
        toast.success(`Removed ${s.name}`)
        router.refresh()
    }

    const head = (key: Sort['key'], label: string, className: string) => (
        <TableHead className={className} aria-sort={sort.key === key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
            <button type="button" className="font-medium hover:underline"
                onClick={() => setSort({ key, dir: sort.key === key && sort.dir === 'asc' ? 'desc' : 'asc' })}>
                {label}{sort.key === key ? (sort.dir === 'asc' ? ' (asc)' : ' (desc)') : ''}
            </button>
        </TableHead>
    )

    return (
        <Card>
            <CardHeader className="pb-3">
                <CardTitle className="text-lg">Watched boards</CardTitle>
                <p className="text-sm text-muted-foreground">
                    Company boards the worker fetches each pass, with postings fetched in the last 30 days.
                </p>
            </CardHeader>
            <CardContent className="space-y-4">
                <AddBoard onAdded={() => router.refresh()} />
                <div className="flex flex-wrap items-center gap-3">
                    <Input aria-label="Search boards" placeholder="Search companies..." value={search}
                        onChange={(e) => filter(setSearch)(e.target.value)} className="flex-1 min-w-[14rem]" />
                    <select aria-label="Source" value={source} onChange={(e) => filter(setSource)(e.target.value)}
                        className="h-9 rounded-md border bg-transparent px-3 text-sm">
                        <option value="">All sources</option>
                        {sourceOptions.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <select aria-label="Health" value={health} onChange={(e) => filter(setHealth)(e.target.value)}
                        className="h-9 rounded-md border bg-transparent px-3 text-sm">
                        <option value="">Any last fetch</option>
                        <option value="attention">Needs attention</option>
                        {BOARD_HEALTH.map((h) => <option key={h} value={h}>{HEALTH_LABEL[h]}</option>)}
                    </select>
                </div>
                <div className="rounded-md border overflow-hidden">
                    <Table className="table-fixed w-full">
                        <TableHeader>
                            <TableRow>
                                {head('name', 'Company', 'w-[30%]')}
                                <TableHead className="w-[13%]">Source</TableHead>
                                <TableHead className="w-[37%]">Last fetch</TableHead>
                                {head('postings_30d', 'Postings (30d)', 'w-[14%] text-right')}
                                <TableHead className="w-[6%]"><span className="sr-only">Remove</span></TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {shown.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={5} className="h-24 text-center text-muted-foreground">
                                        {sources.length === 0 ? 'No boards watched yet.' : 'No boards match these filters.'}
                                    </TableCell>
                                </TableRow>
                            ) : shown.map((s) => (
                                <TableRow key={s.id}>
                                    <TableCell className="truncate text-sm font-medium" title={`${s.source}/${s.slug}`}>{s.name}</TableCell>
                                    <TableCell>
                                        <span className="rounded bg-secondary px-1.5 py-0.5 text-[11px] font-medium text-secondary-foreground">{s.source}</span>
                                    </TableCell>
                                    <TableCell className="truncate text-sm"><LastFetch s={s} /></TableCell>
                                    <TableCell className="text-right text-sm">{s.postings_30d}</TableCell>
                                    <TableCell className="text-right">
                                        <Button variant="ghost" size="icon" className="h-7 w-7" aria-label={`Remove ${s.name}`}
                                            title="Remove" onClick={() => remove(s)}>
                                            <Trash2 className="h-3.5 w-3.5" />
                                        </Button>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </div>
                <Pagination page={Math.min(page, last)} size={PAGE_SIZE} total={rows.length} onPageChange={setPage} />
            </CardContent>
        </Card>
    )
}
