'use client'

import { useState } from 'react'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select'
import { Trash2, Plus } from 'lucide-react'
import { VALID_SOURCES } from '@/lib/constants'

export interface WatchedCompany {
    id: number
    source: string
    slug: string
    name: string
    created_at?: string
}

interface WatchlistTableProps {
    data: WatchedCompany[]
    onAdd: (c: { source: string; slug: string; name: string }) => void
    onRemove: (id: number) => void
}

export function WatchlistTable({ data, onAdd, onRemove }: WatchlistTableProps) {
    const [source, setSource] = useState<string>(VALID_SOURCES[0])
    const [slug, setSlug] = useState('')
    const [name, setName] = useState('')

    const canAdd = slug.trim() !== '' && name.trim() !== ''

    const submit = () => {
        if (!canAdd) return
        onAdd({ source, slug: slug.trim(), name: name.trim() })
        setSlug('')
        setName('')
    }

    return (
        <div className="space-y-4">
            {/* Add company row */}
            <div className="flex flex-col sm:flex-row gap-2">
                <Select value={source} onValueChange={setSource}>
                    <SelectTrigger className="w-full sm:w-[150px]">
                        <SelectValue placeholder="Source" />
                    </SelectTrigger>
                    <SelectContent>
                        {VALID_SOURCES.map((s) => (
                            <SelectItem key={s} value={s}>{s}</SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <Input
                    placeholder="Board slug (e.g. acme)"
                    value={slug}
                    onChange={(e) => setSlug(e.target.value)}
                    className="flex-1"
                />
                <Input
                    placeholder="Display name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') submit() }}
                    className="flex-1"
                />
                <Button onClick={submit} disabled={!canAdd}>
                    <Plus className="mr-1 h-4 w-4" /> Add
                </Button>
            </div>

            <div className="rounded-md border overflow-hidden">
                <Table className="table-fixed w-full">
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[34%] whitespace-normal">Company</TableHead>
                            <TableHead className="w-[18%] whitespace-normal">Source</TableHead>
                            <TableHead className="w-[34%] whitespace-normal">Slug</TableHead>
                            <TableHead className="w-[14%] whitespace-normal text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {data.length === 0 ? (
                            <TableRow>
                                <TableCell colSpan={4} className="h-24 text-center text-muted-foreground">
                                    No companies on the watchlist yet.
                                </TableCell>
                            </TableRow>
                        ) : (
                            data.map((c) => (
                                <TableRow key={c.id}>
                                    <TableCell className="whitespace-normal font-medium text-sm" title={c.name}>
                                        {c.name}
                                    </TableCell>
                                    <TableCell>
                                        <span className="text-[11px] truncate max-w-full inline-block font-medium px-1.5 py-0.5 rounded bg-secondary text-secondary-foreground">
                                            {c.source}
                                        </span>
                                    </TableCell>
                                    <TableCell className="whitespace-normal text-sm text-muted-foreground" title={c.slug}>
                                        {c.slug}
                                    </TableCell>
                                    <TableCell className="text-right">
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            onClick={() => onRemove(c.id)}
                                            title="Remove from watchlist"
                                            className="h-7 w-7 text-destructive hover:text-destructive"
                                        >
                                            <Trash2 className="h-3.5 w-3.5" />
                                        </Button>
                                    </TableCell>
                                </TableRow>
                            ))
                        )}
                    </TableBody>
                </Table>
            </div>

            <div className="flex items-center justify-between py-2">
                <div className="text-sm text-muted-foreground">
                    {data.length} watched compan{data.length === 1 ? 'y' : 'ies'}
                </div>
            </div>
        </div>
    )
}
