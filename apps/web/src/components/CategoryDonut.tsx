'use client'

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts'

interface CategoryDonutProps {
    data: { name: string; value: number }[]
}

const COLORS = [
    '#6366f1', // indigo
    '#8b5cf6', // violet
    '#0ea5e9', // sky
    '#14b8a6', // teal
    '#f59e0b', // amber
    '#ef4444', // red
    '#ec4899', // pink
    '#22c55e', // green
    '#f97316', // orange
]

const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
        const { name, value } = payload[0]
        return (
            <div className="bg-popover text-popover-foreground border border-border rounded-lg px-3 py-2 shadow-lg">
                <p className="font-medium text-sm">{name}</p>
                <p className="text-muted-foreground text-xs">{value} application{value !== 1 ? 's' : ''}</p>
            </div>
        )
    }
    return null
}

export function CategoryDonut({ data }: CategoryDonutProps) {
    if (!data || data.length === 0) {
        return (
            <div className="flex items-center justify-center h-[300px] text-muted-foreground text-sm">
                No category data
            </div>
        )
    }

    return (
        <div style={{ width: '100%', height: 300 }}>
            <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                    <Pie
                        data={data}
                        cx="50%"
                        cy="45%"
                        innerRadius={55}
                        outerRadius={95}
                        paddingAngle={3}
                        dataKey="value"
                        nameKey="name"
                        stroke="none"
                        isAnimationActive={false}
                    >
                        {data.map((_, index) => (
                            <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                        ))}
                    </Pie>
                    <Tooltip content={<CustomTooltip />} />
                    <Legend
                        verticalAlign="bottom"
                        height={36}
                        wrapperStyle={{ fontSize: '12px' }}
                    />
                </PieChart>
            </ResponsiveContainer>
        </div>
    )
}
