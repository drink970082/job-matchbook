import { addWatchedCompany } from '@/lib/watchlist-actions'
import { str, write } from '@/lib/api-v1'

export const dynamic = 'force-dynamic'

export function POST(req: Request) {
    return write(req, (b) => addWatchedCompany({
        url: str(b, 'url'),
        source: str(b, 'source'),
        slug: str(b, 'slug'),
        name: str(b, 'name') ?? '',
        recipe: str(b, 'recipe'),
    }, 'mcp'))
}
