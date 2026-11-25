import {
    bestApplication, matchTier, normalizeCompany, normalizeTitle, rankPostings, sameCompany, titleSimilarity, urlIdentity,
} from '@/lib/application-match'

const app = (company_name: string, job_title: string, application_url: string | null = null) => ({ id: 1, company_name, job_title, application_url })
const post = (id: number, company_name: string, job_title: string, job_url = `https://jobs.example.com/${id}`) => ({ id, company_name, job_title, job_url })

test.each([
    ['Acme Inc', 'acme'], ['ACME, Inc.', 'acme'], ['Acme L.P.', 'acme'], ['The Acme Group', 'acme'], ['Acme Incorporated', 'acme'], ['Acme Company Limited', 'acme'], ['Acme Corporation', 'acme'], ['Acme Bank & Co.', 'acme bank'], ['Acme Bank and Company', 'acme bank'], ['Acme Holdings, LLC', 'acme'],
    ['Smith & Sons', 'smith and sons'], ['D.E. Shaw', 'de shaw'], ['D. E. Shaw', 'de shaw'], ['DE Shaw', 'de shaw'],
    ["O'Neil Corp", 'oneil'], ['Group One', 'group one'], ['Co Star', 'co star'], ['The Group', 'group'], ['', ''],
])('company %s -> %s', (raw, want) => expect(normalizeCompany(raw)).toBe(want))

test.each([
    ['Point72', 'Point72 Asset Management', true], ['ACME', 'Acme Inc', true], ['Acme', 'Acmetrics', false],
    ['Globex', 'Initech', false], ['', 'Acme', false], ['Point7', 'Point72', false],
])('same company: %s / %s -> %s', (a, b, want) => {
    expect(sameCompany(a, b)).toBe(want)
    expect(sameCompany(b, a)).toBe(want)
})

test.each([
    ['Software Engineer – Backend', 'software engineer - backend', true], ['Software Engineer,  Backend', 'Software Engineer (Backend)', true],
    ['Engineer (C++)', 'Engineer (Python)', false], ['Engineer (C++)', 'Engineer (C#)', false], ['Engineer (C++)', 'Engineer (C)', false],
    ['Engineer, 2026', 'Engineer, 2027', false], ['Dev \u0915\u093f', 'Dev \u0915\u0940', false], // differ in a combining mark only
    ["Master's Intern", 'Master’s Intern', true],
])('title %s / %s equal: %s', (a, b, want) => expect(normalizeTitle(a) === normalizeTitle(b)).toBe(want))

test.each([
    ['https://Boards.Greenhouse.io/acme/jobs/1/?gh_src=abc123#app', 'http://boards.greenhouse.io/acme/jobs/1', true],
    ['https://jobs.lever.co/acme/1?utm_source=li1', 'https://jobs.lever.co/acme/1', true],
    // The posting id lives in the query on many boards: without it every posting is one URL.
    ['https://acme.com/careers?gh_jid=1', 'https://acme.com/careers?gh_jid=2', false],
    ['https://acme.com/careers?gh_jid=1&utm_medium=x', 'https://acme.com/careers?gh_jid=1', true],
    ['https://acme.com/careers', 'https://acme.com/careers?gh_jid=1', false],
    ['https://acme.com/careers?refId=1', 'https://acme.com/careers?refId=2', false],
    ['https://acme.com/#/jobs/1', 'https://acme.com/#/jobs/2', false],
    ['https://acme.com/careers', 'https://acme.com/careers#job-2', false],
    ['https://acme.com/Jobs/1', 'https://acme.com/jobs/1', false],
])('url %s / %s same: %s', (a, b, want) => expect(urlIdentity(a) === urlIdentity(b)).toBe(want))

test('a URL that is missing or not http never identifies a posting', () => {
    for (const u of [null, undefined, '', 'acme.com/jobs/1', 'javascript:1']) expect(urlIdentity(u)).toBeNull()
    expect(matchTier(app('Acme', 'Engineer', ''), post(1, 'Globex', 'Engineer', ''))).toBeNull()
})

test('tier 1: the same posting URL, whatever the names say', () => {
    expect(matchTier(app('Acme', 'SWE', 'https://jobs.lever.co/acme/1?lever-source=x'), post(1, 'Acme Robotics', 'Engineer', 'https://jobs.lever.co/acme/1/'))).toBe(1)
})

test('tier 2: same company and title, normalized; a date never enters it', () => {
    expect(matchTier(app('ACME', 'software engineer'), post(1, 'Acme Inc', 'Software Engineer'))).toBe(2)
})

test('tier 3: same company, another title, including a 0.8-similarity pair', () => {
    const a = app('Acme', 'Graduate Software Engineer')
    const p = post(1, 'Acme', 'Java Software Engineer')
    expect(titleSimilarity('Senior Software Engineer, Payments Platform', 'Senior Software Engineer, Risk Platform')).toBeCloseTo(0.8)
    expect(matchTier(a, p)).toBe(3)
    expect(matchTier(app('Acme', 'Senior Software Engineer, Payments Platform'), post(1, 'Acme', 'Senior Software Engineer, Risk Platform'))).toBe(3)
    expect(bestApplication(p, [a])).toBeNull()               // never a suggestion
    expect(matchTier(app('Acme', '???'), post(1, 'Acme', '!!!'))).toBe(3)   // two empty titles are not equal
})

test('no tier: another company', () => {
    expect(matchTier(app('Acme', 'Engineer'), post(1, 'Globex', 'Engineer'))).toBeNull()
})

test('rankPostings: tier, then title similarity, then newest', () => {
    const a = app('Acme', 'Backend Engineer', 'https://jobs.example.com/5')
    const ranked = rankPostings(a, [post(1, 'Acme', 'Accountant'), post(2, 'Acme', 'Frontend Engineer'), post(3, 'Acme', 'Backend Engineer'),
        post(4, 'Globex', 'Backend Engineer'), post(5, 'Acme', 'Other'), post(6, 'Acme', 'Accountant')])
    expect(ranked.map((p) => [p.id, p.tier])).toEqual([[5, 1], [3, 2], [2, 3], [6, 3], [1, 3]])
})

test('bestApplication prefers the lower tier, then the newer application', () => {
    const p = post(1, 'Acme', 'Engineer', 'https://jobs.lever.co/acme/1')
    const apps = [{ ...app('Acme', 'Engineer'), id: 1 }, { ...app('Acme', 'SWE', 'https://jobs.lever.co/acme/1'), id: 2 }, { ...app('Acme', 'Engineer'), id: 3 }]
    expect(bestApplication(p, apps)).toMatchObject({ id: 2, tier: 1 })
    expect(bestApplication(p, [apps[0], apps[2]])).toMatchObject({ id: 3, tier: 2 })
})
