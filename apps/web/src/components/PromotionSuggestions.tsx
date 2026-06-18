'use client'

import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Check, X } from 'lucide-react'

export interface PromotionSuggestion {
    source: string
    slug: string
    name: string
    applied: number
    highScores: number
    total: number
}

interface PromotionSuggestionsProps {
    data: PromotionSuggestion[]
    onApprove: (c: { source: string; slug: string; name: string }) => void
    onDismiss: (source: string, slug: string) => void
}

export function PromotionSuggestions({
    data,
    onApprove,
    onDismiss,
}: PromotionSuggestionsProps) {
    // The parent decides whether to render the surrounding section; nothing to
    // suggest means we render nothing at all.
    if (data.length === 0) return null

    return (
        <div className="space-y-4">
            <div className="rounded-md border overflow-hidden">
                <Table className="table-fixed w-full">
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[48%] whitespace-normal">Company</TableHead>
                            <TableHead className="w-[30%] whitespace-normal">Traction</TableHead>
                            <TableHead className="w-[22%] whitespace-normal text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {data.map((c) => (
                            <TableRow key={`${c.source}/${c.slug}`}>
                                <TableCell className="whitespace-normal" title={c.name}>
                                    <div className="font-medium text-sm">{c.name}</div>
                                    <div className="text-[11px] text-muted-foreground" title={`${c.source}/${c.slug}`}>
                                        {c.source}/{c.slug}
                                    </div>
                                </TableCell>
                                <TableCell className="whitespace-normal">
                                    <div className="flex flex-wrap gap-1">
                                        {c.applied > 0 && (
                                            <Badge variant="default">{c.applied} applied</Badge>
                                        )}
                                        <Badge variant="secondary">{c.highScores} strong</Badge>
                                    </div>
                                </TableCell>
                                <TableCell className="text-right">
                                    <div className="inline-flex gap-1">
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            onClick={() => onApprove({ source: c.source, slug: c.slug, name: c.name })}
                                            title="Add to watchlist"
                                            className="h-7 w-7 text-emerald-600 hover:text-emerald-600"
                                        >
                                            <Check className="h-3.5 w-3.5" />
                                        </Button>
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            onClick={() => onDismiss(c.source, c.slug)}
                                            title="Dismiss suggestion"
                                            className="h-7 w-7 text-destructive hover:text-destructive"
                                        >
                                            <X className="h-3.5 w-3.5" />
                                        </Button>
                                    </div>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>

            <div className="flex items-center justify-between py-2">
                <div className="text-sm text-muted-foreground">
                    {data.length} suggestion{data.length === 1 ? '' : 's'}
                </div>
            </div>
        </div>
    )
}
