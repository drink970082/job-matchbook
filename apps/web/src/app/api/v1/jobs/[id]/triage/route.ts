import { clearTriageOverride, setTriageOverride } from '@/lib/job-actions'
import { idParam, str, write } from '@/lib/api-v1'

export const dynamic = 'force-dynamic'

export function POST(req: Request, { params }: { params: { id: string } }) {
    return write(req, (b) => setTriageOverride(idParam(params.id), str(b, 'decision') ?? '', str(b, 'reason'), 'mcp'))
}

export function DELETE(req: Request, { params }: { params: { id: string } }) {
    return write(req, () => clearTriageOverride(idParam(params.id), 'mcp'), false)
}
