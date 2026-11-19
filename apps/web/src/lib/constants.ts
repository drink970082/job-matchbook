import legacyStatuses from './legacy-statuses.json'

export const STATUSES = [
  'Applied',
  'Screening',
  'Interviewing',
  'Offer',
  'Accepted',
  'Rejected',
  'Withdrew',
] as const

// The 14 statuses before #205, mapped onto the 7 above: an old CSV export re-imports
// correctly. One JSON file so the one-off data migration (prisma/migrate-statuses-205.mjs)
// reads the same map.
export const LEGACY_STATUS_MAP: Record<string, (typeof STATUSES)[number]> = legacyStatuses as any

// Who made a write: the web UI or the MCP server (through /api/v1). Stamped on
// applications (creation) and status_history (each change); schema default is 'web'.
export const ACTORS = ['web', 'mcp'] as const
export type Actor = (typeof ACTORS)[number]

// candidate.work_authorization's closed vocabulary; must match the worker's
// config.VALID_WORK_AUTHORIZATION (the screen reads the value by substring).
export const WORK_AUTHORIZATIONS = ['citizen', 'permanent resident', 'authorized-no-sponsorship', 'needs visa sponsorship'] as const

// The vocabulary the CHARTS key on: every real status plus 'No Response', the
// pseudo-status getStatusFlow synthesizes for an application that never left
// 'Applied' (see analytics-actions.ts). It is deliberately not a real status — nothing is ever
// stored as 'No Response' — which is why it lives here and not in STATUSES.
//
// SankeyChart holds a hand-authored color per member. A color
// cannot be derived from a name, so the map stays written out; what this type buys
// is that it must stay COMPLETE. It `satisfies Record<ChartStatus, ...>`, so a
// status added to STATUSES fails the build until it is given a color — the
// alternative being a node that silently renders grey.
export const CHART_STATUSES = [...STATUSES, 'No Response'] as const
export type ChartStatus = (typeof CHART_STATUSES)[number]

// Default application-category vocabulary — the SEED / fallback for a fresh install.
// Users pick their own labels at onboarding or via the Categories editor (stored in
// the app_settings table; see category-actions.ts getCategories/setCategories), so this list is
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
// sources (oracle, jobvite) are intentionally absent: they can't be watch-listed.
// addWatchedCompany (the MCP add_source write API) validates against it.
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

// Below this trimmed JD length the Discovered Jobs table labels a row "Short JD" (too
// thin to judge with confidence). Hand-synced with the worker's db.py constant.
export const LOW_CONTEXT_MAX_DESCRIPTION_LENGTH = 200

/** Map status to a display color class */
export function getStatusColor(status: string) {
  if (status === 'Applied') return { bg: 'bg-blue-500/15', text: 'text-blue-700', dot: 'bg-blue-500' }
  if (status === 'Screening') return { bg: 'bg-purple-500/15', text: 'text-purple-700', dot: 'bg-purple-500' }
  if (status === 'Interviewing') return { bg: 'bg-amber-500/15', text: 'text-amber-700', dot: 'bg-amber-500' }
  if (status === 'Offer') return { bg: 'bg-emerald-500/15', text: 'text-emerald-700', dot: 'bg-emerald-500' }
  if (status === 'Accepted') return { bg: 'bg-emerald-600/15', text: 'text-emerald-800', dot: 'bg-emerald-600' }
  if (status === 'Rejected') return { bg: 'bg-red-500/15', text: 'text-red-700', dot: 'bg-red-500' }
  if (status === 'Withdrew') return { bg: 'bg-slate-500/15', text: 'text-slate-700', dot: 'bg-slate-500' }
  return { bg: 'bg-gray-500/15', text: 'text-gray-700', dot: 'bg-gray-500' }
}
