import { setCandidatePreferences } from '@/lib/preference-actions'
import { write } from '@/lib/api-v1'

export const dynamic = 'force-dynamic'

export function PUT(req: Request) {
    return write(req, (b) => setCandidatePreferences(b, 'mcp'))
}
