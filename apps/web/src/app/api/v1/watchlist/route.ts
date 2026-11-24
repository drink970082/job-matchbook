import { addWatchedCompany } from '@/lib/watchlist-actions'
import { str, write } from '@/lib/api-v1'

export const dynamic = 'force-dynamic'

export function POST(req: Request) {
    return write(req, (b) => {
        if (b.dry_run !== undefined && typeof b.dry_run !== 'boolean') throw new Error('dry_run must be a boolean')
        return addWatchedCompany({
            url: str(b, 'url'),
            source: str(b, 'source'),
            slug: str(b, 'slug'),
            name: str(b, 'name') ?? '',
            recipe: str(b, 'recipe'),
            dryRun: b.dry_run === true,
        }, 'mcp')
    })
}
