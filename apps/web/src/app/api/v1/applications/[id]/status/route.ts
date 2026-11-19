import { updateApplicationStatus } from '@/lib/actions'
import { idParam, str, write } from '@/lib/api-v1'

export const dynamic = 'force-dynamic'

export function POST(req: Request, { params }: { params: { id: string } }) {
    return write(req, (b) => updateApplicationStatus(idParam(params.id), str(b, 'status') ?? '', str(b, 'date'), 'mcp'))
}
