import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { SettingsPanel } from '@/components/SettingsPanel'
import { getCandidateProfile, setCandidateProfile } from '@/lib/profile-actions'

jest.mock('next/navigation', () => ({ useRouter: () => ({ refresh: jest.fn() }) }))
jest.mock('sonner', () => ({ toast: { error: jest.fn(), success: jest.fn() } }))
jest.mock('@/lib/profile-actions', () => ({
    getCandidateProfile: jest.fn(),
    setCandidateProfile: jest.fn(),
}))

const PROFILE = {
    title_include: ['engineer'], title_exclude: [], max_age_days: 0,
    locations: ['remote', 'Boston'], work_authorization: 'citizen', security_clearance: '',
    exclude_internships: true, exclude_contract: false,
    education: [{ degree: "master's", field: 'CS' }], experience: [{ title: 'SWE', company: 'Acme', years: 2 }],
    target_roles: ['Backend'], open_to: [], not_interested: [],
    custom_triage_context: null as null | { profile_text: string; yoe_context: string },
    packs: 'default', highest_degree: "master's", total_years: 2, triage_configured: true,
    version: 2, actor: 'mcp', changed_at: null, confirmed_at: null,
}
const LOADED = { profile: PROFILE, reassessOnChange: 400 }
const FIELDS = {
    title_include: ['engineer'], title_exclude: [], max_age_days: 0, locations: ['Boston', 'remote'],
    work_authorization: 'citizen', security_clearance: '', exclude_internships: true, exclude_contract: false,
    education: [{ degree: "master's", field: 'CS' }], experience: [{ title: 'SWE', company: 'Acme', years: 2 }],
    target_roles: ['Backend'], open_to: [], not_interested: [],
}
const withContext = (profile_text: string, yoe_context = 'MS.') =>
    ({ ...LOADED, profile: { ...PROFILE, custom_triage_context: { profile_text, yoe_context }, packs: 'custom' } })
const save = () => fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))

beforeEach(() => {
    jest.clearAllMocks()
    jest.mocked(getCandidateProfile).mockResolvedValue(LOADED as any)
    jest.mocked(setCandidateProfile).mockResolvedValue({ success: true, data: { unchanged: false } } as any)
})

describe('SettingsPanel (the one candidate profile form)', () => {
    it('loads every section and saves them in one write; a requirements change costs nothing', async () => {
        const confirm = jest.spyOn(window, 'confirm')
        render(<SettingsPanel />)
        expect(await screen.findByLabelText('Title must contain one of (one per line)')).toHaveValue('engineer')
        expect(screen.getByLabelText('Locations (one per line)')).toHaveValue('Boston')
        expect(screen.getByLabelText('Include remote-eligible postings')).toBeChecked()
        expect(screen.getByLabelText('Degree 1')).toHaveValue("master's")
        expect(screen.getByText(/Highest degree: Master's/)).toBeInTheDocument()
        fireEvent.change(screen.getByLabelText('Locations (one per line)'), { target: { value: 'Boston\nAustin' } })
        fireEvent.change(screen.getByLabelText('Security clearance'), { target: { value: 'none' } })
        fireEvent.change(screen.getByLabelText('Drop postings older than (days)'), { target: { value: '30' } })
        fireEvent.click(screen.getByLabelText('Exclude contract / part-time / temporary'))
        save()
        await waitFor(() => expect(setCandidateProfile).toHaveBeenCalledWith({
            ...FIELDS, locations: ['Boston', 'Austin', 'remote'], security_clearance: 'none', max_age_days: 30,
            exclude_contract: true,
        }))
        expect(confirm).not.toHaveBeenCalled()
        confirm.mockRestore()
    })

    it('blank locations read as open to anywhere and the remote box is off', async () => {
        jest.mocked(getCandidateProfile).mockResolvedValue({ ...LOADED, profile: { ...PROFILE, locations: [] } } as any)
        render(<SettingsPanel />)
        expect(await screen.findByText('Open to anywhere (no location screening).')).toBeInTheDocument()
        expect(screen.getByLabelText('Include remote-eligible postings')).toBeDisabled()
    })

    it('a fresh install is configured from the empty form; background is entered once', async () => {
        jest.mocked(getCandidateProfile).mockResolvedValue({ profile: null, reassessOnChange: 0 } as any)
        render(<SettingsPanel />)
        expect(await screen.findByText(/Nothing is set yet/)).toBeInTheDocument()
        expect(screen.getByText(/degree is not screened/)).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: 'Add education' }))
        fireEvent.change(screen.getByLabelText('Degree 1'), { target: { value: 'phd' } })
        fireEvent.click(screen.getByRole('button', { name: 'Add experience' }))
        fireEvent.change(screen.getByLabelText('Years 1'), { target: { value: '1.5' } })
        fireEvent.change(screen.getByLabelText('Target roles'), { target: { value: 'Backend' } })
        fireEvent.click(screen.getByRole('button', { name: 'Add to Target roles' }))
        expect(screen.getByText(/Total years of experience: 1.5/)).toBeInTheDocument()
        save()
        await waitFor(() => expect(setCandidateProfile).toHaveBeenCalledWith({
            title_include: [], title_exclude: [], max_age_days: 0, locations: [], work_authorization: '',
            security_clearance: '', exclude_internships: false, exclude_contract: false,
            education: [{ degree: 'phd', field: '' }], experience: [{ title: '', company: '', years: 1.5 }],
            target_roles: ['Backend'], open_to: [], not_interested: [],
        }))
    })

    it('a change to what triage reads is saved only after confirming the re-assessment cost', async () => {
        const confirm = jest.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
        render(<SettingsPanel />)
        fireEvent.change(await screen.findByLabelText('Open to'), { target: { value: 'Data' } })
        fireEvent.click(screen.getByRole('button', { name: 'Add to Open to' }))
        save()
        expect(confirm.mock.calls[0][0]).toContain('400 recent postings are re-assessed')
        expect(setCandidateProfile).not.toHaveBeenCalled()
        save()
        await waitFor(() => expect(setCandidateProfile).toHaveBeenCalledWith({ ...FIELDS, open_to: ['Data'] }))
        confirm.mockRestore()
    })

    it('a blank added row is no triage change and asks nothing', async () => {
        const confirm = jest.spyOn(window, 'confirm')
        render(<SettingsPanel />)
        fireEvent.click(await screen.findByRole('button', { name: 'Add experience' }))
        save()
        await waitFor(() => expect(setCandidateProfile).toHaveBeenCalledWith(FIELDS))
        expect(confirm).not.toHaveBeenCalled()
        confirm.mockRestore()
    })

    it('custom packs can be swapped for the committed defaults', async () => {
        jest.mocked(getCandidateProfile).mockResolvedValue({ ...LOADED, profile: { ...PROFILE, packs: 'custom' } } as any)
        jest.spyOn(window, 'confirm').mockReturnValue(true)
        render(<SettingsPanel />)
        expect(await screen.findByText('Question packs: your custom packs.')).toBeInTheDocument()
        fireEvent.click(screen.getByLabelText('Use the committed default packs instead'))
        save()
        await waitFor(() => expect(setCandidateProfile).toHaveBeenCalledWith({ ...FIELDS, custom_packs: null }))
    })
})

describe('SettingsPanel custom triage context (a migrated free-text profile)', () => {
    it('unedited it is not resent; an entry edit saves compact in, compact out', async () => {
        const profile_text = '{"profile":{"background":[{"id":"edu","text":"MS"}],"as_of":"2026-11"}}'
        jest.mocked(getCandidateProfile).mockResolvedValue(withContext(profile_text) as any)
        jest.spyOn(window, 'confirm').mockReturnValue(true)
        render(<SettingsPanel />)
        expect(await screen.findByLabelText('Profile (JSON)')).toHaveValue(JSON.stringify(JSON.parse(profile_text), null, 2))
        save()
        await waitFor(() => expect(setCandidateProfile).toHaveBeenLastCalledWith(FIELDS))  // indenting alone is not a change
        await waitFor(() => expect(getCandidateProfile).toHaveBeenCalledTimes(2))        // the form reloads after a save
        fireEvent.change(screen.getByLabelText('edu text'), { target: { value: 'MEng' } })
        fireEvent.click(screen.getByRole('button', { name: 'Add to background' }))
        save()
        await waitFor(() => expect(setCandidateProfile).toHaveBeenLastCalledWith({ ...FIELDS, custom_triage_context: {
            profile_text: '{"profile":{"background":[{"id":"edu","text":"MEng"},{"id":"","text":""}],"as_of":"2026-11"}}',
            yoe_context: 'MS.' } }))
    })

    it('a CRLF-only difference keeps the stored bytes', async () => {
        jest.mocked(getCandidateProfile).mockResolvedValue(withContext('{\r\n"profile":{}}') as any)
        render(<SettingsPanel />)
        fireEvent.change(await screen.findByLabelText('Profile (JSON)'), { target: { value: '{\n"profile":{}}' } })
        save()
        await waitFor(() => expect(setCandidateProfile).toHaveBeenCalledWith(FIELDS))
    })

    it('the structured view and Advanced edit one profile, and a list keeps its last entry', async () => {
        jest.mocked(getCandidateProfile).mockResolvedValue(withContext('{"profile":{"background":[{"id":"edu","text":"MS"}]}}') as any)
        render(<SettingsPanel />)
        fireEvent.change(await screen.findByLabelText('edu text'), { target: { value: 'MEng' } })
        expect(JSON.parse((screen.getByLabelText('Profile (JSON)') as HTMLTextAreaElement).value).profile.background[0].text).toBe('MEng')
        fireEvent.change(screen.getByLabelText('Profile (JSON)'), { target: { value: '{"profile":{"background":[{"id":"edu","text":"PhD"}]}}' } })
        expect(screen.getByLabelText('edu text')).toHaveValue('PhD')
        expect(screen.queryByRole('button', { name: 'Remove edu' })).toBeNull()  // the shape Add copies
    })

    it('a context that is not a JSON object is edited only as raw text', async () => {
        jest.mocked(getCandidateProfile).mockResolvedValue(withContext('plain text') as any)
        render(<SettingsPanel />)
        expect(await screen.findByText(/not a JSON object/)).toBeInTheDocument()
        expect(screen.getByLabelText('Profile (JSON)')).toHaveValue('plain text')
    })

    it('stopping the custom context sends the fields instead', async () => {
        jest.mocked(getCandidateProfile).mockResolvedValue(withContext('{"a":1}') as any)
        jest.spyOn(window, 'confirm').mockReturnValue(true)
        render(<SettingsPanel />)
        fireEvent.click(await screen.findByLabelText('Stop using the custom context; send the fields above instead'))
        expect(screen.queryByLabelText('Profile (JSON)')).toBeNull()
        save()
        await waitFor(() => expect(setCandidateProfile).toHaveBeenCalledWith({ ...FIELDS, custom_triage_context: null }))
    })
})
