import { markJobApplied } from '@/lib/job-actions'
import { bool, idParam, str, write } from '@/lib/api-v1'

export const dynamic = 'force-dynamic'

// Scope 'all': the caller names one posting by id, not a filtered view.
export function POST(req: Request, { params }: { params: { id: string } }) {
    return write(req, (b) => markJobApplied(idParam(params.id), str(b, 'category'), { stage: 'all' }, 'mcp',
        { date: str(b, 'date'), createNew: bool(b, 'create_new') }))
}
