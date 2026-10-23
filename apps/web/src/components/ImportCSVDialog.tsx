'use client'

import { useRef, useState } from 'react'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { STATUSES } from '@/lib/constants'
import { Upload, FileText, X } from 'lucide-react'
import { toast } from 'sonner'

interface ImportCSVDialogProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    // Receives the file's text; the caller owns the server action, the result toast
    // and the refresh. Resolve false to keep the dialog open (import failed).
    onImport: (text: string) => Promise<boolean>
}

// The import file picker: drag-and-drop or click-to-browse, plus the column contract
// spelled out inline. The contract mirrors importApplicationsCSV in lib/actions.ts —
// keep the two in sync. Native drag events only; no drop-zone dependency.
export function ImportCSVDialog({ open, onOpenChange, onImport }: ImportCSVDialogProps) {
    const [file, setFile] = useState<File | null>(null)
    const [dragging, setDragging] = useState(false)
    const [busy, setBusy] = useState(false)
    const inputRef = useRef<HTMLInputElement>(null)

    const accept = (f: File | undefined) => {
        if (!f) return
        // Windows/Excel often reports a .csv as application/vnd.ms-excel, so trust the
        // extension over the MIME type.
        if (!f.name.toLowerCase().endsWith('.csv')) {
            toast.error('Pick a .csv file (Excel: Save As -> CSV UTF-8)')
            return
        }
        setFile(f)
    }

    const run = async () => {
        if (!file) return
        setBusy(true)
        const ok = await onImport(await file.text())
        setBusy(false)
        if (ok) {
            setFile(null)
            onOpenChange(false)
        }
    }

    return (
        <Dialog
            open={open}
            onOpenChange={(o) => {
                if (!o) setFile(null)
                onOpenChange(o)
            }}
        >
            <DialogContent className="sm:max-w-lg">
                <DialogHeader>
                    <DialogTitle>Import applications</DialogTitle>
                    <DialogDescription>
                        Adds new rows only — an application whose company and job title already
                        exist is skipped, never overwritten.
                    </DialogDescription>
                </DialogHeader>

                <div
                    onDragOver={(e) => {
                        e.preventDefault()
                        setDragging(true)
                    }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={(e) => {
                        e.preventDefault()
                        setDragging(false)
                        accept(e.dataTransfer.files?.[0])
                    }}
                    onClick={() => inputRef.current?.click()}
                    // min-w-0: DialogContent is a grid, whose children default to
                    // min-width:auto and would otherwise be sized by their content.
                    className={`flex min-w-0 cursor-pointer flex-col items-center gap-2 rounded-lg border-2 border-dashed p-6 text-center transition-colors ${
                        dragging ? 'border-primary bg-primary/5' : 'border-muted-foreground/50 hover:bg-muted/40'
                    }`}
                >
                    {file ? (
                        <>
                            <FileText className="h-6 w-6 text-muted-foreground" />
                            <div className="flex items-center gap-2 text-sm font-medium">
                                {file.name}
                                <button
                                    type="button"
                                    aria-label="Clear file"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        setFile(null)
                                    }}
                                    className="text-muted-foreground hover:text-foreground"
                                >
                                    <X className="h-4 w-4" />
                                </button>
                            </div>
                            <p className="text-xs text-muted-foreground">Click to pick a different file</p>
                        </>
                    ) : (
                        <>
                            <Upload className="h-6 w-6 text-muted-foreground" />
                            <p className="text-sm font-medium">Drop a CSV here, or click to browse</p>
                            <p className="text-xs text-muted-foreground">
                                Excel: Save As -&gt; CSV UTF-8 (Comma delimited)
                            </p>
                        </>
                    )}
                    <input
                        ref={inputRef}
                        type="file"
                        accept=".csv,text/csv"
                        className="hidden"
                        onChange={(e) => {
                            accept(e.target.files?.[0])
                            e.target.value = ''
                        }}
                    />
                </div>

                <details className="min-w-0 rounded-md border bg-muted/30 px-3 py-2 text-xs">
                    <summary className="cursor-pointer font-medium">Expected format</summary>
                    <div className="mt-2 space-y-2 text-muted-foreground">
                        <p>First row must be this header (extra columns are ignored):</p>
                        {/* Template literal, not JSX text: JSX collapses a newline between
                            text children into a space, which would merge the two rows. */}
                        <pre className="whitespace-pre-wrap break-all rounded bg-background p-2 text-[11px] leading-relaxed">
                            {`company_name,job_title,application_url,date_applied,category,status,notes,last_updated
Acme,Backend Engineer,https://acme.com/jobs/1,2026-08-01,Software Engineering,Applied,,`}
                        </pre>
                        <ul className="list-disc space-y-1 pl-4">
                            <li>
                                Required: <code>company_name</code>, <code>job_title</code>,{' '}
                                <code>date_applied</code>. Other columns may be left out entirely.
                            </li>
                            <li>
                                <code>date_applied</code> is <code>YYYY-MM-DD</code>.
                            </li>
                            <li>
                                <code>status</code> must match exactly, otherwise the row imports as
                                Applied: {STATUSES.join(', ')}.
                            </li>
                            <li>
                                <code>category</code> is free-form (your own labels); blank becomes
                                Others.
                            </li>
                            <li>
                                <code>last_updated</code> is ignored — it is stamped at import time.
                            </li>
                        </ul>
                        <p>Export CSV gives you a file in exactly this shape to edit and re-import.</p>
                    </div>
                </details>

                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
                        Cancel
                    </Button>
                    <Button onClick={run} disabled={!file || busy}>
                        {busy ? 'Importing...' : 'Import'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
