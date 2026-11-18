import { addApplication } from '@/lib/actions'
import { str, write } from '@/lib/api-v1'

export const dynamic = 'force-dynamic'

export function POST(req: Request) {
    return write(req, (b) => addApplication({
        company_name: str(b, 'company_name') ?? '',
        job_title: str(b, 'job_title') ?? '',
        date_applied: str(b, 'date_applied') ?? '',
        category: str(b, 'category'),
        status: str(b, 'status'),
        application_url: str(b, 'application_url'),
        notes: str(b, 'notes'),
    }, 'mcp'))
}
