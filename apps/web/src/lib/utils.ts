import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
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
