'use client'

import type { ComponentProps } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DiscoveredJobsTable } from './DiscoveredJobsTable'
import { QuotaBar } from './QuotaBar'

export function DiscoveredJobsTab(props: ComponentProps<typeof DiscoveredJobsTable>) {
    return (
        <Card>
            <CardHeader className="pb-3">
                <CardTitle className="text-lg">Discovered Jobs</CardTitle>
            </CardHeader>
            <CardContent>
                <QuotaBar />
                <DiscoveredJobsTable {...props} />
            </CardContent>
        </Card>
    )
}
