import { linkApplication } from '@/lib/link-actions'
import { idParam, int, write } from '@/lib/api-v1'

export const dynamic = 'force-dynamic'

export function POST(req: Request, { params }: { params: { id: string } }) {
    return write(req, async (b) => {
        const job = int(b, 'job_id')
        return job === undefined ? { success: false, error: 'job_id is required' } : linkApplication(idParam(params.id), job, 'mcp')
    })
}
