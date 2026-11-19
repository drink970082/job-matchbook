'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { UnresolvedFeedsTable } from './UnresolvedFeedsTable'
import type { UnresolvedFeedGroup } from '@/lib/unresolved-actions'

export interface WatchedSource {
    id: number
    source: string
    slug: string
    name: string
    created_at?: string
    postings_30d: number
}

interface SourcesTabProps {
    sources: WatchedSource[]
    unresolved: UnresolvedFeedGroup[]
}

// Read-only (#158): what the worker fetches and what feeds could not resolve. Sources
// are added or removed through MCP (add_source / remove_source).
export function SourcesTab({ sources, unresolved }: SourcesTabProps) {
    return (
        <div className="space-y-6">
            <Card>
                <CardHeader className="pb-3">
                    <CardTitle className="text-lg">Watched boards</CardTitle>
                    <p className="text-sm text-muted-foreground">
                        Company boards the worker fetches each pass, with postings fetched in the
                        last 30 days. Add or remove them through your AI client (MCP).
                    </p>
                </CardHeader>
                <CardContent>
                    <div className="rounded-md border overflow-hidden">
                        <Table className="table-fixed w-full">
                            <TableHeader>
                                <TableRow>
                                    <TableHead className="w-[34%]">Company</TableHead>
                                    <TableHead className="w-[16%]">Source</TableHead>
                                    <TableHead className="w-[34%]">Slug</TableHead>
                                    <TableHead className="w-[16%] text-right">Postings (30d)</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {sources.length === 0 ? (
                                    <TableRow>
                                        <TableCell colSpan={4} className="h-24 text-center text-muted-foreground">
                                            No boards watched yet.
                                        </TableCell>
                                    </TableRow>
                                ) : sources.map((s) => (
                                    <TableRow key={s.id}>
                                        <TableCell className="truncate text-sm font-medium" title={s.name}>{s.name}</TableCell>
                                        <TableCell>
                                            <span className="rounded bg-secondary px-1.5 py-0.5 text-[11px] font-medium text-secondary-foreground">{s.source}</span>
                                        </TableCell>
                                        <TableCell className="truncate text-sm text-muted-foreground" title={s.slug}>{s.slug}</TableCell>
                                        <TableCell className="text-right text-sm">{s.postings_30d}</TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </div>
                </CardContent>
            </Card>
            <Card>
                <CardHeader className="pb-3">
                    <CardTitle className="text-lg">Unresolved feed listings</CardTitle>
                    <p className="text-sm text-muted-foreground">
                        Feed listings whose apply URL could not be mapped to a supported board.
                    </p>
                </CardHeader>
                <CardContent>
                    <UnresolvedFeedsTable data={unresolved} />
                </CardContent>
            </Card>
        </div>
    )
}
