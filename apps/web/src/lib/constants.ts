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

// The vocabulary the CHARTS key on: every real status plus 'No Response', the
// pseudo-status getStatusFlow synthesizes for an application that never left
// 'Applied' (see actions.ts). It is deliberately not a real status — nothing is ever
// stored as 'No Response' — which is why it lives here and not in STATUSES.
//
// SankeyChart and StatusFunnel each hold a hand-authored color per member. A color
// cannot be derived from a name, so those maps stay written out; what this type buys
// is that they must stay COMPLETE. Both `satisfies Record<ChartStatus, ...>`, so a
// status added to STATUSES fails the build until it is given a color in both — the
// alternative being a node that silently renders grey.
export const CHART_STATUSES = [...STATUSES, 'No Response'] as const
export type ChartStatus = (typeof CHART_STATUSES)[number]

// Default application-category vocabulary — the SEED / fallback for a fresh install.
// Users pick their own labels at onboarding or via the Categories editor (stored in
// the app_settings table; see actions.ts getCategories/setCategories), so this list is
// only what shows before they choose. Categories are free-form; keep an 'Others'
// catch-all. Broad and cross-industry on purpose — the app is not tech-only.
export const DEFAULT_CATEGORIES = [
  'Software Engineering',
  'Data & Analytics',
  'Product',
  'Design',
  'Finance',
  'Marketing',
  'Operations',
  'Sales',
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
  'custom',
  'browser',
] as const

// Sources whose fetch is driven by a declarative JSON `recipe` (not a slug alone).
// A watchlist row for one of these MUST carry a recipe. Mirrors the worker's
// config.RECIPE_SOURCES.
export const RECIPE_SOURCES = ['custom', 'browser'] as const

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
