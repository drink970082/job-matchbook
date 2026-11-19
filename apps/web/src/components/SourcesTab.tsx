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

export interface WatchedSource {
    id: number
    source: string
    slug: string
    name: string
    created_at?: string
    postings_30d: number
    pending?: boolean
}

const PAGE_SIZE = 25
type Sort = { key: 'name' | 'postings_30d'; dir: 'asc' | 'desc' }

// Add a board by pasting its careers or job URL (#208). Resolution is pure (lib/board-url.ts,
// the same resolver /api/v1/watchlist runs for MCP), so it updates as the user types.
function AddBoard({ onAdded }: { onAdded: () => void }) {
    const [url, setUrl] = useState('')
    const [name, setName] = useState('')
    const [saving, setSaving] = useState(false)
    const resolved = url.trim() ? resolveBoardUrl(url) : null

    const change = (v: string) => {
        setUrl(v)
        const r = resolveBoardUrl(v)
        setName(r ? nameFromSlug(r.slug) : '')
    }
    const add = async () => {
        setSaving(true)
        try {
            const result = await addWatchedCompany({ url, name })
            if (!result.success) return toast.error(result.error)
            toast.success(`Added ${name}: fetched on the next worker pass`)
            setUrl('')
            setName('')
            onAdded()
        } finally {
            setSaving(false)
        }
    }

    return (
        <div className="space-y-2">
            <div className="flex flex-wrap gap-2">
                <Input aria-label="Careers or job URL" placeholder="Paste a careers or job URL, e.g. https://boards.greenhouse.io/acme"
                    value={url} onChange={(e) => change(e.target.value)} className="flex-[2] min-w-[18rem]" />
                <Input aria-label="Company name" placeholder="Company name" value={name}
                    onChange={(e) => setName(e.target.value)} disabled={!resolved} className="flex-1 min-w-[10rem]" />
                <Button onClick={add} disabled={!resolved || !name.trim() || saving}>Add board</Button>
            </div>
            {url.trim() && (
                <p className="text-xs text-muted-foreground">
                    {resolved
                        ? `${resolved.source} board "${resolved.slug}"`
                        : 'This site needs a custom recipe - set it up from your AI client with the onboard-board skill.'}
                </p>
            )}
        </div>
    )
}

// What the worker fetches (#208): search, source and dead-board filters, sortable
// Company and Postings (30d), 25 per page, add by URL, remove with a confirm.
export function SourcesTab({ sources }: { sources: WatchedSource[] }) {
    const router = useRouter()
    const [search, setSearch] = useState('')
    const [source, setSource] = useState('')
    const [deadOnly, setDeadOnly] = useState(false)
    const [sort, setSort] = useState<Sort>({ key: 'name', dir: 'asc' })
    const [page, setPage] = useState(0)

    const sourceOptions = useMemo(() => [...new Set(sources.map((s) => s.source))].sort(), [sources])
    const rows = useMemo(() => {
        const q = search.trim().toLowerCase()
        const out = sources.filter((s) => (!q || s.name.toLowerCase().includes(q))
            && (!source || s.source === source) && (!deadOnly || (!s.pending && s.postings_30d === 0)))
        const sign = sort.dir === 'asc' ? 1 : -1
        return out.sort((a, b) => sign * (sort.key === 'name'
            ? a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
            : a.postings_30d - b.postings_30d) || a.id - b.id)
    }, [sources, search, source, deadOnly, sort])
    const last = Math.max(0, Math.ceil(rows.length / PAGE_SIZE) - 1)
    const shown = rows.slice(Math.min(page, last) * PAGE_SIZE, (Math.min(page, last) + 1) * PAGE_SIZE)
    const filter = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPage(0) }

    const remove = async (s: WatchedSource) => {
        if (!window.confirm(`Stop fetching ${s.name} (${s.source})? Postings already fetched stay.`)) return
        const result = await removeWatchedCompany(s.id)
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
                    <label className="flex items-center gap-2 text-sm">
                        <input type="checkbox" checked={deadOnly} onChange={(e) => filter(setDeadOnly)(e.target.checked)} />
                        Only boards with no postings
                    </label>
                </div>
                <div className="rounded-md border overflow-hidden">
                    <Table className="table-fixed w-full">
                        <TableHeader>
                            <TableRow>
                                {head('name', 'Company', 'w-[46%]')}
                                <TableHead className="w-[18%]">Source</TableHead>
                                {head('postings_30d', 'Postings (30d)', 'w-[28%] text-right')}
                                <TableHead className="w-[8%]"><span className="sr-only">Remove</span></TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {shown.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={4} className="h-24 text-center text-muted-foreground">
                                        {sources.length === 0 ? 'No boards watched yet.' : 'No boards match these filters.'}
                                    </TableCell>
                                </TableRow>
                            ) : shown.map((s) => (
                                <TableRow key={s.id}>
                                    <TableCell className="truncate text-sm font-medium" title={`${s.source}/${s.slug}`}>{s.name}</TableCell>
                                    <TableCell>
                                        <span className="rounded bg-secondary px-1.5 py-0.5 text-[11px] font-medium text-secondary-foreground">{s.source}</span>
                                    </TableCell>
                                    <TableCell className="text-right text-sm">
                                        {s.pending ? <span className="text-muted-foreground">Pending first fetch</span>
                                            : s.postings_30d === 0
                                                ? <span className="text-amber-600" title="Usually a wrong slug, or the company moved platforms">No postings in 30 days</span>
                                                : s.postings_30d}
                                    </TableCell>
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
