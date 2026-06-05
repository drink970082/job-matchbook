
'use client'

import { useState } from 'react'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { STATUSES, getStatusColor } from '@/lib/constants'
import { Trash2 } from 'lucide-react'

interface StatusHistoryModalProps {
    isOpen: boolean
    onClose: () => void
    application: {
        id: number
        company_name: string
        job_title: string
        category: string
        application_url?: string | null
        date_applied?: string
        notes?: string | null
    }
    history: Array<{
        id: number
        status: string
        timestamp: string
        notes?: string
    }>
    onAddStatus: (data: { status: string; notes: string; date: string }) => void
    onDeleteHistory: (id: number) => void
    onEditApplication: (
        id: number,
        data: {
            company_name: string
            job_title: string
            category: string
            application_url: string
            date_applied: string
            notes: string
        }
    ) => Promise<void>
}

export function StatusHistoryModal({
    isOpen,
    onClose,
    application,
    history,
    onAddStatus,
    onDeleteHistory,
    onEditApplication,
}: StatusHistoryModalProps) {
    const [isEditing, setIsEditing] = useState(false)
    const [editForm, setEditForm] = useState({
        company_name: application.company_name,
        job_title: application.job_title,
        category: application.category || '',
        application_url: application.application_url || '',
        date_applied: application.date_applied || '',
        notes: application.notes || '',
    })
    const [newStatus, setNewStatus] = useState<string>(STATUSES[0])
    const [newNotes, setNewNotes] = useState('')
    const [newDate, setNewDate] = useState(new Date().toISOString().split('T')[0])

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault()
        onAddStatus({
            status: newStatus,
            notes: newNotes,
            date: newDate,
        })
        setNewNotes('')
    }

    const handleSaveEdit = async () => {
        await onEditApplication(application.id, editForm)
        setIsEditing(false)
    }

    const handleCancelEdit = () => {
        setEditForm({
            company_name: application.company_name,
            job_title: application.job_title,
            category: application.category || '',
            application_url: application.application_url || '',
            date_applied: application.date_applied || '',
            notes: application.notes || '',
        })
        setIsEditing(false)
    }

    const titleContent = isEditing ? (
        <div className="flex flex-col gap-2 mt-2 font-normal">
            <Input
                value={editForm.company_name}
                onChange={(e) => setEditForm(prev => ({ ...prev, company_name: e.target.value }))}
                placeholder="Company Name"
                className="h-8"
            />
            <Input
                value={editForm.job_title}
                onChange={(e) => setEditForm(prev => ({ ...prev, job_title: e.target.value }))}
                placeholder="Job Title"
                className="h-8"
            />
            <div className="grid grid-cols-2 gap-2">
                <Input
                    value={editForm.category}
                    onChange={(e) => setEditForm(prev => ({ ...prev, category: e.target.value }))}
                    placeholder="Category"
                    className="h-8"
                />
                <Input
                    type="date"
                    value={editForm.date_applied}
                    onChange={(e) => setEditForm(prev => ({ ...prev, date_applied: e.target.value }))}
                    className="h-8"
                />
            </div>
            <Input
                value={editForm.application_url}
                onChange={(e) => setEditForm(prev => ({ ...prev, application_url: e.target.value }))}
                placeholder="https://..."
                className="h-8"
            />
            <Textarea
                value={editForm.notes}
                onChange={(e) => setEditForm(prev => ({ ...prev, notes: e.target.value }))}
                placeholder="Notes..."
                className="text-sm"
                rows={2}
            />
            <div className="flex gap-2">
                <Button size="sm" onClick={handleSaveEdit}>Save</Button>
                <Button size="sm" variant="ghost" onClick={handleCancelEdit}>Cancel</Button>
            </div>
        </div>
    ) : (
        <div className="flex justify-between items-start pr-6">
            <div>
                History for {application.company_name} — {application.job_title}
                {application.category && <span className="ml-2 px-1.5 py-0.5 rounded text-xs bg-secondary text-secondary-foreground">{application.category}</span>}
            </div>
            <Button size="sm" variant="outline" onClick={() => setIsEditing(true)}>Edit</Button>
        </div>
    )

    return (
        <Dialog open={isOpen} onOpenChange={onClose}>
            <DialogContent className="sm:max-w-[600px]">
                <DialogHeader>
                    <DialogTitle asChild>
                        <div>{titleContent}</div>
                    </DialogTitle>
                </DialogHeader>

                <div className="space-y-6">
                    {/* History List */}
                    <div className="max-h-[300px] overflow-y-auto space-y-2 border rounded-md p-4">
                        {history.length === 0 ? (
                            <p className="text-muted-foreground text-sm text-center py-4">No history recorded.</p>
                        ) : (
                            history.map((item) => {
                                const color = getStatusColor(item.status)
                                return (
                                    <div key={item.id} className="flex justify-between items-center border-b last:border-0 pb-2 last:pb-0">
                                        <div className="flex items-center gap-3">
                                            <span className={`h-2.5 w-2.5 rounded-full shrink-0 ${color.dot}`} />
                                            <div>
                                                <div className="font-semibold text-sm">{item.status}</div>
                                                <div className="text-xs text-muted-foreground">
                                                    {new Date(item.timestamp).toLocaleDateString()}
                                                </div>
                                                {item.notes && <div className="text-sm mt-0.5 text-muted-foreground">{item.notes}</div>}
                                            </div>
                                        </div>
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            onClick={() => onDeleteHistory(item.id)}
                                            className="text-destructive hover:text-destructive h-8 w-8"
                                        >
                                            <Trash2 className="h-3.5 w-3.5" />
                                        </Button>
                                    </div>
                                )
                            })
                        )}
                    </div>

                    {/* Add Status Form */}
                    <form onSubmit={handleSubmit} className="space-y-4 border-t pt-4">
                        <h4 className="font-medium">Update Status</h4>
                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <Label htmlFor="status">Status</Label>
                                <select
                                    id="status"
                                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                                    value={newStatus}
                                    onChange={(e) => setNewStatus(e.target.value)}
                                >
                                    {STATUSES.map(s => (
                                        <option key={s} value={s}>{s}</option>
                                    ))}
                                </select>
                            </div>
                            <div className="space-y-2">
                                <Label htmlFor="date">Date</Label>
                                <Input
                                    id="date"
                                    type="date"
                                    value={newDate}
                                    onChange={(e) => setNewDate(e.target.value)}
                                    required
                                />
                            </div>
                        </div>
                        <div className="space-y-2">
                            <Label htmlFor="notes">Notes</Label>
                            <Textarea
                                id="notes"
                                placeholder="Notes..."
                                value={newNotes}
                                onChange={(e) => setNewNotes(e.target.value)}
                            />
                        </div>
                        <div className="flex justify-end">
                            <Button type="submit">Update Status</Button>
                        </div>
                    </form>
                </div>
            </DialogContent>
        </Dialog>
    )
}
