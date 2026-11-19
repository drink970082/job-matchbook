import { parseJevProfile, renderJevProfile, validateJevForm } from '@/lib/jev-profile-form'

const FORM = {
    target_roles: ['Backend engineer', '  '], open_to: ['Data platform'], not_interested: ['Sales engineering'],
    education: [{ degree: "Master's", field: 'Computer Science' }, { degree: '', field: '' }],
    experience: [{ title: 'Software Engineer', company: 'Acme', years: 2 }, { title: 'Intern', company: 'Beta', years: 0.5 }],
}

test('the form renders the same bytes every time, and parses back', () => {
    const form = validateJevForm(FORM)
    expect(form.target_roles).toEqual(['Backend engineer'])       // blank dropped
    expect(form.education).toHaveLength(1)
    const a = renderJevProfile(form)
    expect(renderJevProfile(validateJevForm(JSON.parse(JSON.stringify(FORM))))).toEqual(a)
    expect(a.yoe_context).toBe("Education: Master's in Computer Science.\n"
        + 'Experience: Software Engineer at Acme, 2 years; Intern at Beta, 0.5 years.\nTotal years of experience: 2.5.')
    expect(parseJevProfile(a.profile_text, a.yoe_context)).toEqual(form)
})

test('a profile not written by the form does not parse into it', () => {
    const { profile_text, yoe_context } = renderJevProfile(validateJevForm(FORM))
    expect(parseJevProfile('{"domains":[],"profile":"free text"}', yoe_context)).toBeNull()
    expect(parseJevProfile(profile_text, yoe_context + ' edited')).toBeNull()
    expect(parseJevProfile('not json', yoe_context)).toBeNull()
})

test('validation rejects malformed input', () => {
    expect(() => validateJevForm({ ...FORM, salary: 1 })).toThrow('Unknown JEV profile field(s): salary')
    expect(() => validateJevForm({ ...FORM, target_roles: [] })).toThrow('at least one target role')
    expect(() => validateJevForm({ ...FORM, experience: [{ title: 'X', years: -1 }] })).toThrow('years must be')
    expect(() => validateJevForm({ ...FORM, open_to: 'x' })).toThrow('open_to must be a list')
})
