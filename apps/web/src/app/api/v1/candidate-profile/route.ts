import { setCandidateProfile } from '@/lib/profile-actions'
import { write } from '@/lib/api-v1'

export const dynamic = 'force-dynamic'

export function PUT(req: Request) {
    return write(req, (b) => setCandidateProfile(b, 'mcp'))
}
