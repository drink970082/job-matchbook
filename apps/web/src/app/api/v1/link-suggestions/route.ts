import { getLinkSuggestions } from '@/lib/link-actions'
import { idParam, read } from '@/lib/api-v1'

export const dynamic = 'force-dynamic'

// ?application_id= | ?job_id= | neither (every unlinked application with a candidate).
export function GET(req: Request) {
    return read(req, async () => {
        const q = new URL(req.url).searchParams
        const id = (key: string) => (q.has(key) ? idParam(q.get(key)!) : undefined)
        return getLinkSuggestions({ applicationId: id('application_id'), jobId: id('job_id') })
    })
}
