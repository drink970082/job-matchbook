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

// Watchlist-capable board sources — must match the worker's config.VALID_SOURCES
// (the per-board, enumerable subset of fetch.ADAPTERS). Feed-only per-listing
// sources (oracle, jobvite) are intentionally absent: they can't be watch-listed,
// and promotion suggestions are restricted to these (see promotion-actions.ts).
// Used by the Watchlist add-company form.
export const VALID_SOURCES = [
  'greenhouse',
  'lever',
  'ashby',
  'workday',
  'pinpoint',
  'smartrecruiters',
  'workable',
  'icims',
  'phenom',
] as const

// A scored posting whose JD body (trimmed) is shorter than this many characters is
// treated as "low-context": too thin to screen/score with confidence. Such rows are
// pulled out of Matched/Discarded into their own Low-context bucket so they're
// visibly distinct rather than silently scored alongside confidently-parsed JDs.
// Single tuning knob (derived at query time — no persisted flag / schema change):
// raise it to catch more borderline-thin JDs, lower it to catch only the barest
// stubs. See getJobPostings / lowContextIds in lib/actions.ts.
export const LOW_CONTEXT_MAX_DESCRIPTION_LENGTH = 200

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
