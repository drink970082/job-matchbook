import { addApplication } from '@/lib/application-actions'
import { STATUSES } from '@/lib/constants'
import { str, write } from '@/lib/api-v1'

export const dynamic = 'force-dynamic'

export function POST(req: Request) {
    return write(req, async (b) => {
        // The UI action quietly falls back to 'Applied'; an API caller is told instead.
        const status = str(b, 'status')
        if (status !== undefined && !(STATUSES as readonly string[]).includes(status)) {
            return { success: false, error: 'Invalid status' }
        }
        return addApplication({
        company_name: str(b, 'company_name') ?? '',
        job_title: str(b, 'job_title') ?? '',
        date_applied: str(b, 'date_applied') ?? '',
        category: str(b, 'category'),
        status,
        application_url: str(b, 'application_url'),
        notes: str(b, 'notes'),
    }, 'mcp')
    })
}
