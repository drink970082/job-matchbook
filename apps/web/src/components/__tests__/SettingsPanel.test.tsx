import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { SettingsPanel } from '@/components/SettingsPanel'
import { renderJevProfile } from '@/lib/jev-profile-form'
import { getSettings, setCandidatePreferences, setJevProfile } from '@/lib/preference-actions'

jest.mock('next/navigation', () => ({ useRouter: () => ({ refresh: jest.fn() }) }))
jest.mock('sonner', () => ({ toast: { error: jest.fn(), success: jest.fn() } }))
jest.mock('@/lib/preference-actions', () => ({
    getSettings: jest.fn(),
    setCandidatePreferences: jest.fn(),
    setJevProfile: jest.fn(),
}))

const SETTINGS = {
    preferences: { highest_degree: "Master's", work_authorization: 'citizen', security_clearance: '',
        locations: ['remote', 'Boston'], exclude_internships: true, version: 2, actor: 'mcp' },
    jev: { profile_text: '{"profile":{}}', yoe_context: 'MS.', version: 1, actor: 'config', changed_at: null },
    reassessOnChange: 400,
}

beforeEach(() => {
    jest.clearAllMocks()
    jest.mocked(getSettings).mockResolvedValue(SETTINGS as any)
    jest.mocked(setCandidatePreferences).mockResolvedValue({ success: true, data: { unchanged: false } } as any)
    jest.mocked(setJevProfile).mockResolvedValue({ success: true, data: { unchanged: false } } as any)
})

describe('SettingsPanel', () => {
    it('loads the stored requirements and saves them as entered', async () => {
        render(<SettingsPanel />)
        expect(await screen.findByLabelText('Highest degree')).toHaveValue("Master's")
        expect(screen.getByLabelText('Locations (one per line)')).toHaveValue('Boston')
        expect(screen.getByLabelText('Include remote-eligible postings')).toBeChecked()
        fireEvent.change(screen.getByLabelText('Locations (one per line)'), { target: { value: 'Boston\nAustin' } })
        fireEvent.change(screen.getByLabelText('Security clearance'), { target: { value: 'none' } })
        fireEvent.click(screen.getByLabelText('Exclude contract / part-time / temporary'))
        fireEvent.click(screen.getByRole('button', { name: 'Save requirements' }))
        await waitFor(() => expect(setCandidatePreferences).toHaveBeenCalledWith({
            highest_degree: "Master's", work_authorization: 'citizen', security_clearance: 'none',
            locations: ['Boston', 'Austin', 'remote'], exclude_internships: true, exclude_contract: true,
        }))
    })

    it('blank locations read as open to anywhere and the remote box is off', async () => {
        jest.mocked(getSettings).mockResolvedValue({ ...SETTINGS,
            preferences: { ...SETTINGS.preferences, locations: [] } } as any)
        render(<SettingsPanel />)
        expect(await screen.findByText('Open to anywhere (no location screening).')).toBeInTheDocument()
        expect(screen.getByLabelText('Include remote-eligible postings')).toBeDisabled()
    })

    it('saves the JEV profile only after confirming the re-assessment cost', async () => {
        const confirm = jest.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
        render(<SettingsPanel />)
        fireEvent.change(await screen.findByLabelText('Profile (JSON)'), { target: { value: '{"profile":{"a":1}}' } })
        fireEvent.click(screen.getByRole('button', { name: 'Save raw text' }))
        expect(confirm.mock.calls[0][0]).toContain('re-assesses 400 recent postings')
        expect(setJevProfile).not.toHaveBeenCalled()
        fireEvent.click(screen.getByRole('button', { name: 'Save raw text' }))
        await waitFor(() => expect(setJevProfile).toHaveBeenCalledWith({ profile_text: '{"profile":{"a":1}}', yoe_context: 'MS.' }))
        confirm.mockRestore()
    })

    it('an unchanged JEV profile (even with CRLF stored) neither confirms nor writes', async () => {
        jest.mocked(getSettings).mockResolvedValue({ ...SETTINGS, jev: { ...SETTINGS.jev, profile_text: '{\r\n"profile":{}}' } } as any)
        const confirm = jest.spyOn(window, 'confirm')
        render(<SettingsPanel />)
        const box = await screen.findByLabelText('Profile (JSON)')
        fireEvent.change(box, { target: { value: '{\n"profile":{}}' } })
        fireEvent.click(screen.getByRole('button', { name: 'Save JEV profile' }))
        expect(confirm).not.toHaveBeenCalled()
        expect(setJevProfile).not.toHaveBeenCalled()
        confirm.mockRestore()
    })

    it('saves requirements when none are stored yet', async () => {
        jest.mocked(getSettings).mockResolvedValue({ preferences: null, jev: null, reassessOnChange: 0 } as any)
        render(<SettingsPanel />)
        fireEvent.change(await screen.findByLabelText('Highest degree'), { target: { value: 'PhD' } })
        fireEvent.click(screen.getByRole('button', { name: 'Save requirements' }))
        await waitFor(() => expect(setCandidatePreferences).toHaveBeenCalledWith({
            highest_degree: 'PhD', work_authorization: '', security_clearance: '', locations: [], exclude_internships: false, exclude_contract: false,
        }))
    })

    it('explains the missing JEV profile instead of offering an empty editor', async () => {
        jest.mocked(getSettings).mockResolvedValue({ preferences: null, jev: null, reassessOnChange: 0 } as any)
        render(<SettingsPanel />)
        expect(await screen.findByText(/No JEV profile yet/)).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Save JEV profile' })).toBeNull()
    })

    it('a profile written by the form loads into it and saves the structured fields', async () => {
        const form = { target_roles: ['Backend'], open_to: [], not_interested: [], education: [],
            experience: [{ title: 'SWE', company: 'Acme', years: 2 }] }
        jest.mocked(getSettings).mockResolvedValue({ ...SETTINGS, jev: { ...SETTINGS.jev, ...renderJevProfile(form) } } as any)
        const confirm = jest.spyOn(window, 'confirm').mockReturnValue(true)
        render(<SettingsPanel />)
        expect(await screen.findByText('Backend')).toBeInTheDocument()
        expect(screen.getByLabelText('Company 1')).toHaveValue('Acme')
        expect(screen.queryByText(/written as free text/)).toBeNull()
        fireEvent.click(screen.getByRole('button', { name: 'Add education' }))   // a blank row is no change
        fireEvent.click(screen.getByRole('button', { name: 'Save JEV profile' }))
        expect(confirm).not.toHaveBeenCalled()                 // unchanged form: no cost prompt, no write
        fireEvent.change(screen.getByLabelText('Open to'), { target: { value: 'Data' } })
        fireEvent.click(screen.getByRole('button', { name: 'Add to Open to' }))
        fireEvent.click(screen.getByRole('button', { name: 'Save JEV profile' }))
        await waitFor(() => expect(setJevProfile).toHaveBeenCalledWith({ form: { ...form, open_to: ['Data'] } }))  // blank row dropped
        confirm.mockRestore()
    })

    it('a profile the form did not write is edited field by field as its JSON', async () => {
        const profile_text = '{"profile":{"background":[{"id":"edu","text":"MS"}],"as_of":"2026-11"}}'
        jest.mocked(getSettings).mockResolvedValue({ ...SETTINGS, jev: { ...SETTINGS.jev, profile_text } } as any)
        const confirm = jest.spyOn(window, 'confirm').mockReturnValue(true)
        render(<SettingsPanel />)
        // Unedited: no change, and the raw view under Advanced is the same JSON indented.
        fireEvent.click(await screen.findByRole('button', { name: 'Save JEV profile' }))
        expect(setJevProfile).not.toHaveBeenCalled()
        expect(screen.getByLabelText('Profile (JSON)')).toHaveValue(JSON.stringify(JSON.parse(profile_text), null, 2))
        fireEvent.click(screen.getByRole('button', { name: 'Save raw text' }))
        expect(setJevProfile).not.toHaveBeenCalled()  // indenting alone is not a change
        // Edit a list entry (labelled by its id), add a same-shaped one, remove nothing else.
        fireEvent.change(screen.getByLabelText('edu text'), { target: { value: 'MEng' } })
        fireEvent.click(screen.getByRole('button', { name: 'Add to background' }))
        fireEvent.click(screen.getByRole('button', { name: 'Save JEV profile' }))
        await waitFor(() => expect(setJevProfile).toHaveBeenCalledWith({
            profile_text: '{"profile":{"background":[{"id":"edu","text":"MEng"},{"id":"","text":""}],"as_of":"2026-11"}}',
            yoe_context: 'MS.',
        }))  // compact in, compact out
        confirm.mockRestore()
    })

    it('the structured view and Advanced edit one profile, and a list keeps its last entry', async () => {
        const profile_text = '{"profile":{"background":[{"id":"edu","text":"MS"}]}}'
        jest.mocked(getSettings).mockResolvedValue({ ...SETTINGS, jev: { ...SETTINGS.jev, profile_text } } as any)
        render(<SettingsPanel />)
        fireEvent.change(await screen.findByLabelText('edu text'), { target: { value: 'MEng' } })
        expect(JSON.parse((screen.getByLabelText('Profile (JSON)') as HTMLTextAreaElement).value).profile.background[0].text).toBe('MEng')
        fireEvent.change(screen.getByLabelText('Profile (JSON)'), { target: { value: '{"profile":{"background":[{"id":"edu","text":"PhD"}]}}' } })
        expect(screen.getByLabelText('edu text')).toHaveValue('PhD')
        expect(screen.queryByRole('button', { name: 'Remove edu' })).toBeNull()  // the shape Add copies
        expect(screen.getAllByLabelText('Education and experience')).toHaveLength(1)
    })

    it('a stored profile that is not a JSON object is edited only under Advanced', async () => {
        jest.mocked(getSettings).mockResolvedValue({ ...SETTINGS, jev: { ...SETTINGS.jev, profile_text: 'plain text' } } as any)
        render(<SettingsPanel />)
        expect(await screen.findByText(/not a JSON object/)).toBeInTheDocument()
        expect(screen.getByLabelText('Profile (JSON)')).toHaveValue('plain text')
        expect(screen.getAllByLabelText('Education and experience')).toHaveLength(1)
    })
})
