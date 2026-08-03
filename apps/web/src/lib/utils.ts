import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Today as 'YYYY-MM-DD', in LOCAL time — the default date for a newly recorded
// application and the stamp on an exported CSV filename.
//
// It was UTC (`new Date().toISOString().split('T')[0]`, the five call sites this
// replaced), which meant that past ~19:00 US Eastern the date had already rolled over
// and a form pre-filled with TOMORROW. Local is now the one rule: TimelineHeatmap
// already built its own LOCAL reference from getFullYear/getMonth/getDate so the grid
// lines up with the user's calendar, and the two agree by construction rather than by
// coincidence.
//
// Built from the local getters rather than `toLocaleDateString('en-CA')` on purpose —
// the locale route is one line shorter but silently emits M/D/YYYY on a small-ICU
// runtime, and a wrong FORMAT is worse than the wrong day it replaces.
//
// The three browser call sites get the viewer's own today. The one SERVER call site
// (markJobApplied) gets the container's, which is UTC unless `TZ` is set — see the
// `TZ` env var on the web service in docker-compose.yml.
export function todayISO(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

// Scraped job_url is untrusted; an <a href> with a javascript:/data: scheme executes
// on click. Allow only http(s); anything else (or a parse failure) renders as '#'.
export function safeHref(url: string | null | undefined): string {
  if (!url) return '#'
  try {
    const proto = new URL(url).protocol
    return proto === 'http:' || proto === 'https:' ? url : '#'
  } catch {
    return '#'
  }
}
