import { Briefcase, TrendingUp, FileText, Users, XCircle, Trophy } from 'lucide-react'

interface KPIGridProps {
    stats: {
        applied: number
        active: number
        assessment: number
        interviewing: number
        rejected: number
        offer: number
    }
}

const KPI_CONFIG = [
    { key: 'applied' as const, label: 'Applied', icon: Briefcase, color: 'text-blue-500' },
    { key: 'active' as const, label: 'Active', icon: TrendingUp, color: 'text-emerald-500' },
    { key: 'assessment' as const, label: 'OA', icon: FileText, color: 'text-purple-500' },
    { key: 'interviewing' as const, label: 'Interviewing', icon: Users, color: 'text-amber-500' },
    { key: 'rejected' as const, label: 'Rejected', icon: XCircle, color: 'text-red-500' },
    { key: 'offer' as const, label: 'Offer', icon: Trophy, color: 'text-emerald-600' },
]

export function KPIGrid({ stats }: KPIGridProps) {
    return (
        <div className="flex flex-wrap gap-3">
            {KPI_CONFIG.map(({ key, label, icon: Icon, color }) => (
                <div
                    key={key}
                    className="flex items-center gap-2 px-3 py-1.5 rounded-lg border bg-card text-card-foreground"
                >
                    <Icon className={`h-3.5 w-3.5 ${color}`} />
                    <span className="text-xs text-muted-foreground">{label}</span>
                    <span className="text-sm font-bold">{stats[key]}</span>
                </div>
            ))}
        </div>
    )
}
