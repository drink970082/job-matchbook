import { addWatchedCompany } from '@/lib/actions'
import { str, write } from '@/lib/api-v1'

export const dynamic = 'force-dynamic'

export function POST(req: Request) {
    return write(req, (b) => addWatchedCompany({
        source: str(b, 'source') ?? '',
        slug: str(b, 'slug') ?? '',
        name: str(b, 'name') ?? '',
        recipe: str(b, 'recipe'),
    }, 'mcp'))
}
