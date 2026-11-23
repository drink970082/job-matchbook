import { readFileSync } from 'node:fs'
import path from 'node:path'
import { DEGREES } from '@/lib/constants'
import { highestDegree, profileView, requirementsConfigured, toColumn, totalYears, validateProfilePatch } from '@/lib/candidate-profile'

// Shared with the worker (tests/test_profile.py): the derived fields and what both refuse.
const CASES = JSON.parse(readFileSync(
    path.join(__dirname, '../../../../worker/tests/fixtures/candidate-profile-cases.json'), 'utf8'))

test('the degree vocabulary is the worker one', () => {
    expect([...DEGREES]).toEqual(CASES.degrees)
})

test.each<[string, any]>(CASES.derived.map((c: any) => [c.name, c]))('derived fields: %s', (_name, c: any) => {
    expect(highestDegree(c.education)).toBe(c.highest_degree)
    expect(totalYears(c.experience)).toBe(c.total_years)
})

test.each<[string, any]>(CASES.invalid.map((c: any) => [c.name, c]))('refused like the worker: %s', (_name, c: any) => {
    expect(() => validateProfilePatch({ [c.field]: c.value })).toThrow(c.error)
})

test('a patch is normalized: trimmed, blank entries dropped, degree case folded', () => {
    expect(validateProfilePatch({
        title_include: [' eng ', ''], education: [{ degree: "Master's", field: ' CS ' }, { degree: '', field: '' }],
        experience: [{ title: '', company: '', years: 0 }, { title: 'SWE', years: 1 }],
        work_authorization: 'Citizen', custom_packs: null, custom_triage_context: null,
    })).toEqual({
        title_include: ['eng'], education: [{ degree: "master's", field: 'CS' }],
        experience: [{ title: 'SWE', company: '', years: 1 }], work_authorization: 'citizen',
        custom_packs: null, custom_triage_context: null,
    })
})

test('a custom context keeps its profile bytes and takes nothing else', () => {
    const text = '{ "a": 1 }  '
    expect(validateProfilePatch({ custom_triage_context: { profile_text: text, yoe_context: ' MS ' } }))
        .toEqual({ custom_triage_context: { profile_text: text, yoe_context: 'MS' } })
    expect(() => validateProfilePatch({ custom_triage_context: { profile_text: '{}', yoe_context: 'x', c_pack: '{}' } }))
        .toThrow('takes only profile_text and yoe_context')
    expect(() => validateProfilePatch({ custom_triage_context: 'x' })).toThrow('must be an object')
    expect(() => validateProfilePatch({ custom_triage_context: { profile_text: 1, yoe_context: 'x' } })).toThrow('profile_text must be a string')
    expect(() => validateProfilePatch({ custom_triage_context: { profile_text: 'x'.repeat(16001), yoe_context: 'x' } })).toThrow('over 16000')
})

test('limits and types', () => {
    expect(() => validateProfilePatch({ locations: Array(51).fill('x') })).toThrow('over 50 entries')
    expect(() => validateProfilePatch({ target_roles: ['x'.repeat(201)] })).toThrow('over 200 characters')
    expect(() => validateProfilePatch({ education: Array(31).fill({ degree: 'phd' }) })).toThrow('over 30 entries')
    expect(() => validateProfilePatch({ education: ['phd'] })).toThrow('education entry must be an object')
    expect(() => validateProfilePatch({ max_age_days: 3651 })).toThrow('max_age_days')
    expect(() => validateProfilePatch({ security_clearance: 1 })).toThrow('security_clearance must be a string')
    expect(() => validateProfilePatch([])).toThrow('profile must be an object')
})

test('columns hold the bytes the worker seed writes, and read back as the view', () => {
    expect(toColumn('locations', ['remote', 'Zürich'])).toBe('["remote","Zürich"]')
    expect(toColumn('custom_triage_context', { yoe_context: 'b', profile_text: 'a' })).toBe('{"profile_text":"a","yoe_context":"b"}')
    expect(toColumn('custom_triage_context', null)).toBeNull()
    expect(toColumn('max_age_days', 3)).toBe(3)
    const view = profileView({ title_include: '[]', title_exclude: '[]', locations: '[]', education: '[{"degree":"phd","field":""}]',
        experience: '[{"title":"a","company":"b","years":1.5}]', target_roles: '[]', open_to: '[]', not_interested: '[]',
        max_age_days: 0, work_authorization: '', security_clearance: '', exclude_internships: false, exclude_contract: false,
        custom_packs: '{"preference_pack":"p","yoe_pack":"y"}', custom_triage_context: null, version: 1, actor: 'web',
        changed_at: null, confirmed_at: null })
    expect([view.highest_degree, view.total_years, view.packs, view.triage_configured]).toEqual(['phd', 1.5, 'custom', false])
    expect(requirementsConfigured(view)).toBe(true)
    expect(requirementsConfigured({ ...view, education: [] })).toBe(false)
})
