'use server'

import { prisma } from '@/lib/db'
import { DEFAULT_CATEGORIES } from '@/lib/constants'

// --- Categories (DB-backed vocabulary the user picks at onboarding) ----------
// The application-category list lives in one app_settings row (key='categories',
// value = a JSON string array) so a user can pick their own field's labels instead
// of the built-in DEFAULT_CATEGORIES. Categories are free-form: they drive only the
// dropdowns and the donut, never any pipeline logic.

export async function getCategories(): Promise<{ categories: string[]; configured: boolean }> {
    const row = await prisma.app_settings.findUnique({ where: { key: 'categories' } })
    if (!row) return { categories: [...DEFAULT_CATEGORIES], configured: false }
    try {
        const parsed = JSON.parse(row.value)
        const categories = Array.isArray(parsed)
            ? parsed.map((c) => String(c)).filter((c) => c.trim())
            : []
        // An empty / garbage stored value falls back to defaults and reads as
        // NOT configured, so the first-run prompt still offers to set a real list.
        if (categories.length === 0) return { categories: [...DEFAULT_CATEGORIES], configured: false }
        return { categories, configured: true }
    } catch {
        return { categories: [...DEFAULT_CATEGORIES], configured: false }
    }
}

export async function setCategories(list: string[]) {
    try {
        // Trim, drop blanks, dedupe case-insensitively (first spelling wins). Order
        // is preserved — it's the dropdown order the user sees.
        const seen = new Set<string>()
        const categories: string[] = []
        for (const raw of list ?? []) {
            const c = String(raw).trim()
            if (c && !seen.has(c.toLowerCase())) {
                seen.add(c.toLowerCase())
                categories.push(c)
            }
        }
        if (categories.length === 0) {
            return { success: false, error: 'Pick at least one category' }
        }
        const now = new Date().toISOString()
        const value = JSON.stringify(categories)
        await prisma.app_settings.upsert({
            where: { key: 'categories' },
            update: { value, updated_at: now },
            create: { key: 'categories', value, updated_at: now },
        })
        return { success: true, data: categories }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}
