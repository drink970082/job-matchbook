'use client'

import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table'

export interface UnresolvedFeedGroup {
    host: string
    reason: string
    count: number
}

interface UnresolvedFeedsTableProps {
    data: UnresolvedFeedGroup[]
}

export function UnresolvedFeedsTable({ data }: UnresolvedFeedsTableProps) {
    return (
        <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
                Feed listings the resolver couldn&apos;t map to a supported board,
                grouped by host and reason.
            </p>

            <div className="rounded-md border overflow-hidden">
                <Table className="table-fixed w-full">
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[50%] whitespace-normal">Host</TableHead>
                            <TableHead className="w-[34%] whitespace-normal">Reason</TableHead>
                            <TableHead className="w-[16%] whitespace-normal text-right">Count</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {data.length === 0 ? (
                            <TableRow>
                                <TableCell colSpan={3} className="h-24 text-center text-muted-foreground">
                                    No unresolved feed listings.
                                </TableCell>
                            </TableRow>
                        ) : (
                            data.map((row) => (
                                <TableRow key={`${row.host}::${row.reason}`}>
                                    <TableCell className="whitespace-normal font-medium text-sm" title={row.host}>
                                        {row.host}
                                    </TableCell>
                                    <TableCell className="whitespace-normal text-sm text-muted-foreground" title={row.reason}>
                                        <span className="text-[11px] truncate max-w-full inline-block font-medium px-1.5 py-0.5 rounded bg-secondary text-secondary-foreground">
                                            {row.reason}
                                        </span>
                                    </TableCell>
                                    <TableCell className="text-right text-sm tabular-nums">
                                        {row.count}
                                    </TableCell>
                                </TableRow>
                            ))
                        )}
                    </TableBody>
                </Table>
            </div>
        </div>
    )
}
