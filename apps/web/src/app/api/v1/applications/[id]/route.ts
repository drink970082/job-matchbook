import { updateApplicationDetails } from '@/lib/application-actions'
import { idParam, str, write } from '@/lib/api-v1'

export const dynamic = 'force-dynamic'

export function PATCH(req: Request, { params }: { params: { id: string } }) {
    return write(req, (b) => updateApplicationDetails(idParam(params.id), {
        company_name: str(b, 'company_name'),
        job_title: str(b, 'job_title'),
        category: str(b, 'category'),
        application_url: str(b, 'application_url'),
        date_applied: str(b, 'date_applied'),
        notes: str(b, 'notes'),
    }, 'mcp'))
}
