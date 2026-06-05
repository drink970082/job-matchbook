export const STATUSES = [
  'Applied',
  'Online Assessment',
  'Phone Screen',
  'Interviewing: 1st round',
  'Interviewing: 2nd round',
  'Interviewing: 3rd round',
  'Interviewing: 4th round',
  'Interviewing: 5th round',
  'Final Round',
  'Offer',
  'Accepted',
  'Rejected',
  'Withdrew',
  'Ghosted',
] as const

export const CATEGORIES = [
  'SWE',
  'MLE',
  'DS',
  'DA',
  'Quant Dev',
  'Quant Analyst',
  'Quant Trader',
  'AI Engineer',
  'Others',
] as const

export type Status = (typeof STATUSES)[number]
export type Category = (typeof CATEGORIES)[number]

/** Statuses that end the application lifecycle (don't count as Active). */
export const TERMINAL_STATUSES: readonly Status[] = [
  'Offer',
  'Accepted',
  'Rejected',
  'Withdrew',
  'Ghosted',
] as const

/** Map status to a display color class */
export function getStatusColor(status: string) {
  if (status === 'Applied') return { bg: 'bg-blue-500/15', text: 'text-blue-700', dot: 'bg-blue-500' }
  if (status === 'Online Assessment') return { bg: 'bg-purple-500/15', text: 'text-purple-700', dot: 'bg-purple-500' }
  if (status === 'Phone Screen') return { bg: 'bg-violet-500/15', text: 'text-violet-700', dot: 'bg-violet-500' }
  if (status === 'Final Round') return { bg: 'bg-orange-500/15', text: 'text-orange-700', dot: 'bg-orange-500' }
  if (status.includes('Interviewing')) return { bg: 'bg-amber-500/15', text: 'text-amber-700', dot: 'bg-amber-500' }
  if (status === 'Offer') return { bg: 'bg-emerald-500/15', text: 'text-emerald-700', dot: 'bg-emerald-500' }
  if (status === 'Accepted') return { bg: 'bg-emerald-600/15', text: 'text-emerald-800', dot: 'bg-emerald-600' }
  if (status === 'Rejected') return { bg: 'bg-red-500/15', text: 'text-red-700', dot: 'bg-red-500' }
  if (status === 'Withdrew') return { bg: 'bg-slate-500/15', text: 'text-slate-700', dot: 'bg-slate-500' }
  if (status === 'Ghosted') return { bg: 'bg-zinc-400/15', text: 'text-zinc-600', dot: 'bg-zinc-400' }
  return { bg: 'bg-gray-500/15', text: 'text-gray-700', dot: 'bg-gray-500' }
}
