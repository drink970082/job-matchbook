'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ChevronsLeft, ChevronLeft, ChevronRight, ChevronsRight } from 'lucide-react'

interface PaginationProps {
    page: number // 0-indexed
    size: number
    total: number
    onPageChange: (page: number) => void
}

// Windowed page list: always show first + last + current±1, with ellipsis for gaps.
// e.g. current=40 of 81 -> [1, …, 39, 40, 41, …, 81]
export function pageItems(current: number, totalPages: number): (number | 'ellipsis')[] {
    const pages = new Set<number>([1, totalPages])
    for (let p = current - 1; p <= current + 1; p++) {
        if (p >= 1 && p <= totalPages) pages.add(p)
    }
    const sorted = Array.from(pages).sort((a, b) => a - b)
    const out: (number | 'ellipsis')[] = []
    let prev = 0
    for (const p of sorted) {
        if (prev && p - prev > 1) out.push('ellipsis')
        out.push(p)
        prev = p
    }
    return out
}

export function Pagination({ page, size, total, onPageChange }: PaginationProps) {
    const [jump, setJump] = useState('')
    const totalPages = Math.max(1, Math.ceil(total / size))
    const current = page + 1
    const go = (p: number) => onPageChange(Math.min(totalPages, Math.max(1, p)) - 1)

    const submitJump = () => {
        const n = parseInt(jump, 10)
        if (!Number.isNaN(n)) go(n)
        setJump('')
    }

    return (
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 py-2">
            <div className="text-sm text-muted-foreground">
                {total === 0
                    ? '0 results'
                    : `Showing ${page * size + 1}–${Math.min((page + 1) * size, total)} of ${total}`}
            </div>
            <div className="flex items-center gap-1 flex-wrap justify-end">
                <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => go(1)} disabled={current <= 1} aria-label="First page">
                    <ChevronsLeft className="h-4 w-4" />
                </Button>
                <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => go(current - 1)} disabled={current <= 1} aria-label="Previous page">
                    <ChevronLeft className="h-4 w-4" />
                </Button>
                {pageItems(current, totalPages).map((it, i) =>
                    it === 'ellipsis' ? (
                        <span key={`e${i}`} className="px-1 text-muted-foreground select-none">…</span>
                    ) : (
                        <Button
                            key={it}
                            variant={it === current ? 'default' : 'outline'}
                            size="sm"
                            className="h-8 min-w-8 px-2"
                            onClick={() => go(it)}
                            aria-label={`Page ${it}`}
                            aria-current={it === current ? 'page' : undefined}
                        >
                            {it}
                        </Button>
                    )
                )}
                <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => go(current + 1)} disabled={current >= totalPages} aria-label="Next page">
                    <ChevronRight className="h-4 w-4" />
                </Button>
                <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => go(totalPages)} disabled={current >= totalPages} aria-label="Last page">
                    <ChevronsRight className="h-4 w-4" />
                </Button>
                {totalPages > 1 && (
                    <div className="flex items-center gap-1 ml-2">
                        <Input
                            type="number"
                            min={1}
                            max={totalPages}
                            value={jump}
                            onChange={(e) => setJump(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') submitJump()
                            }}
                            placeholder={`1-${totalPages}`}
                            className="h-8 w-20"
                            aria-label="Go to page"
                        />
                        <Button variant="outline" size="sm" className="h-8" onClick={submitJump}>
                            Go
                        </Button>
                    </div>
                )}
            </div>
        </div>
    )
}
