import { setJevProfile } from '@/lib/actions'
import { write } from '@/lib/api-v1'

export const dynamic = 'force-dynamic'

export function PUT(req: Request) {
    return write(req, (b) => setJevProfile(b, 'mcp'))
}
