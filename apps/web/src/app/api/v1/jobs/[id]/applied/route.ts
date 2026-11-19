import { markJobApplied } from '@/lib/actions'
import { idParam, str, write } from '@/lib/api-v1'

export const dynamic = 'force-dynamic'

// Scope 'all': the caller names one posting by id, not a filtered view.
export function POST(req: Request, { params }: { params: { id: string } }) {
    return write(req, (b) => markJobApplied(idParam(params.id), str(b, 'category'), { bucket: 'all' }, 'mcp'))
}
