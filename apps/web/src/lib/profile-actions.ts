'use server'

import { prisma } from '@/lib/db'
import type { Actor } from '@/lib/constants'
import { checkedActor } from '@/lib/action-helpers'
import { type ProfileField, profileView, toColumn, validateProfilePatch } from '@/lib/candidate-profile'

// --- Candidate profile (#224): the one row every worker stage reads -----------------
// A set merges the given fields over the stored ones; an actual change bumps `version`,
// stamps `changed_at` and is audited with the row it replaced. A no-op writes nothing.
// The worker reads the row from its next pass on. Look forward only (#225): postings
// already evaluated keep their verdict and nothing is re-assessed.

// The Settings form's read: the stored profile (null until seeded or set).
export async function getCandidateProfile() {
    const row = await prisma.candidate_profile.findUnique({ where: { id: 1 } })
    return { profile: row ? profileView(row) : null }
}

// The audit snapshot: the custom pack texts are private and long, so only their presence.
const snapshot = (row: Record<string, unknown>) => ({ ...row, custom_packs: row.custom_packs ? '(custom)' : null })

export async function setCandidateProfile(input: Record<string, unknown>, actor: Actor = 'web') {
    checkedActor(actor)
    try {
        const current = await prisma.candidate_profile.findUnique({ where: { id: 1 }, select: { custom_triage_context: true } })
        const storedText = current?.custom_triage_context
            ? (JSON.parse(current.custom_triage_context) as { profile_text: string }).profile_text : undefined
        const patch = validateProfilePatch(input, storedText)
        const columns = Object.fromEntries(Object.entries(patch).map(([k, v]) => [k, toColumn(k as ProfileField, v)]))
        const data = await prisma.$transaction(async (tx) => {
            const before = await tx.candidate_profile.findUnique({ where: { id: 1 } })
            if (before && Object.entries(columns).every(([k, v]) => (before as Record<string, unknown>)[k] === v)) {
                return { ...profileView(before), unchanged: true }
            }
            const now = new Date().toISOString()
            const stamp = { ...columns, actor, changed_at: now, updated_at: now }
            const row = await tx.candidate_profile.upsert({
                where: { id: 1 },
                create: { id: 1, version: 1, ...stamp },
                update: { ...stamp, version: { increment: 1 } },
            })
            await tx.audit_log.create({ data: {
                at: now, actor, action: before ? 'update' : 'add', entity: 'candidate_profile', entity_id: 1,
                payload: JSON.stringify(before ? { before: snapshot(before), after: snapshot(row) } : snapshot(row)),
            } })
            return { ...profileView(row), unchanged: false }
        })
        return { success: true, data }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}
