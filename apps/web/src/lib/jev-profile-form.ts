// The JEV profile as a form (#206). The structured fields are the source of truth; they
// render profile_text (a JSON document the model reads verbatim) and yoe_context
// deterministically, so the same form always yields the same bytes and an unchanged
// save does not move the policy hash. Shared by the web form and MCP set_jev_profile.

export interface JevForm {
    target_roles: string[]
    open_to: string[]
    not_interested: string[]
    education: { degree: string; field: string }[]
    experience: { title: string; company: string; years: number }[]
}

export const JEV_FORM_KEYS = ['target_roles', 'open_to', 'not_interested', 'education', 'experience'] as const
const LISTS = ['target_roles', 'open_to', 'not_interested'] as const
const MAX_ITEMS = 30
const MAX_TEXT = 200

const text = (v: unknown, what: string) => {
    if (typeof v !== 'string') throw new Error(`${what} must be a string`)
    const t = v.trim()
    if (t.length > MAX_TEXT) throw new Error(`${what} is over ${MAX_TEXT} characters`)
    return t
}
const rows = (v: unknown, what: string) => {
    if (!Array.isArray(v)) throw new Error(`${what} must be a list`)
    if (v.length > MAX_ITEMS) throw new Error(`${what} has over ${MAX_ITEMS} entries`)
    return v
}
const obj = (v: unknown, what: string) => {
    if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error(`${what} must be an object`)
    return v as Record<string, unknown>
}

// Throws on a malformed form; blank entries are dropped.
export function validateJevForm(input: unknown): JevForm {
    const o = obj(input, 'form')
    const unknown = Object.keys(o).filter((k) => !(JEV_FORM_KEYS as readonly string[]).includes(k))
    if (unknown.length) throw new Error(`Unknown JEV profile field(s): ${unknown.join(', ')}`)
    const form = {} as JevForm
    for (const k of LISTS) form[k] = rows(o[k] ?? [], k).map((x) => text(x, k)).filter(Boolean)
    form.education = rows(o.education ?? [], 'education').map((r) => {
        const e = obj(r, 'education entry')
        return { degree: text(e.degree ?? '', 'degree'), field: text(e.field ?? '', 'field') }
    }).filter((e) => e.degree || e.field)
    form.experience = rows(o.experience ?? [], 'experience').map((r) => {
        const e = obj(r, 'experience entry')
        const years = Number(e.years ?? 0)
        if (!Number.isFinite(years) || years < 0 || years > 60) throw new Error('years must be a number from 0 to 60')
        return { title: text(e.title ?? '', 'title'), company: text(e.company ?? '', 'company'), years }
    }).filter((e) => e.title || e.company)
    if (!form.target_roles.length) throw new Error('Give at least one target role')
    return form
}

export const totalYears = (form: JevForm) => form.experience.reduce((n, e) => n + e.years, 0)

export function renderJevProfile(form: JevForm): { profile_text: string; yoe_context: string } {
    const profile_text = JSON.stringify({
        target_roles: form.target_roles, open_to: form.open_to, not_interested: form.not_interested,
        education: form.education, experience: form.experience,
    }, null, 2)
    const edu = form.education.map((e) => [e.degree, e.field].filter(Boolean).join(' in '))
    const exp = form.experience.map((e) => `${[e.title, e.company].filter(Boolean).join(' at ')}, ${e.years} years`)
    const yoe_context = [
        `Education: ${edu.length ? edu.join('; ') : 'none listed'}.`,
        `Experience: ${exp.length ? exp.join('; ') : 'none listed'}.`,
        `Total years of experience: ${totalYears(form)}.`,
    ].join('\n')
    return { profile_text, yoe_context }
}

// The stored profile as a form, or null when it was not written by this form (free
// text, or edited by hand since): re-rendering must reproduce both stored texts exactly.
export function parseJevProfile(profile_text: string, yoe_context: string): JevForm | null {
    try {
        const form = validateJevForm(JSON.parse(profile_text))
        const back = renderJevProfile(form)
        return back.profile_text === profile_text && back.yoe_context === yoe_context ? form : null
    } catch {
        return null
    }
}
