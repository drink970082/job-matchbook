import { removeWatchedCompany } from '@/lib/actions'
import { idParam, write } from '@/lib/api-v1'

export const dynamic = 'force-dynamic'

export function DELETE(req: Request, { params }: { params: { id: string } }) {
    return write(req, () => removeWatchedCompany(idParam(params.id)), false)
}
