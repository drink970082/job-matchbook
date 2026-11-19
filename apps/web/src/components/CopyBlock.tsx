'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'

// A copy-paste template: the text as written, plus a Copy button.
export function CopyBlock({ label, text }: { label: string; text: string }) {
    const [copied, setCopied] = useState(false)
    const copy = async () => {
        await navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
    }
    return (
        <div className="space-y-1">
            <div className="flex items-center justify-between">
                <span className="text-xs font-medium">{label}</span>
                <Button type="button" variant="outline" size="sm" className="h-6 px-2 text-xs" onClick={copy}>
                    {copied ? 'Copied' : 'Copy'}
                </Button>
            </div>
            <pre className="overflow-x-auto rounded-md border bg-muted/40 p-2 text-xs">{text}</pre>
        </div>
    )
}
