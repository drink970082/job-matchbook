import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Today as 'YYYY-MM-DD', in UTC — the default date for a newly recorded application
// and the stamp on an exported CSV filename.
//
// UTC is what the five call sites this replaced already did (`new
// Date().toISOString().split('T')[0]`), so this is their exact behavior, named once.
// It is NOT the only date rule in the app and deliberately does not become one:
// TimelineHeatmap builds its own reference from getFullYear/getMonth/getDate, which
// is LOCAL, because the heatmap grid has to line up with the user's own calendar.
// Folding the two together would move real dates for anyone west of UTC.
//
// Consequence worth knowing: past ~19:00 US Eastern, UTC has already rolled over, so
// a form defaulted from here offers tomorrow. Changing that is a behavior change, not
// a cleanup — see the deep-clean decision register.
export function todayISO(): string {
  return new Date().toISOString().split('T')[0]
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
