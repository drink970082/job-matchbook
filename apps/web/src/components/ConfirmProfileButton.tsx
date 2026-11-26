'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { confirmCandidateProfile } from '@/lib/profile-actions'

// The confirmation gate (#227): the one click that lets the worker spend on model stages.
export function ConfirmProfileButton() {
    const router = useRouter()
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const confirm = async () => {
        setBusy(true)
        const res = await confirmCandidateProfile()
        setBusy(false)
        if (res.success) router.refresh()
        else setError(res.error ?? 'Could not confirm')
    }
    return (
        <div className="flex items-center gap-3">
            <Button size="sm" onClick={confirm} disabled={busy}>Confirm profile and start evaluating</Button>
            {error && <span role="alert" className="text-sm text-red-600">{error}</span>}
        </div>
    )
}
