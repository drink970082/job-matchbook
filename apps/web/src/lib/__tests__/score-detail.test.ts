import { safeParseDetail, parseAssessment, verdictClass, verdictLabel } from '@/lib/score-detail'

// score_detail is worker-written JSON describing an LLM's output, reaching the UI
// through a nullable TEXT column. Every one of these inputs is reachable in the live
// database, so the parser has to survive all of them rather than trusting the shape.

describe('safeParseDetail', () => {
    it.each([
        ['null', null],
        ['undefined', undefined],
        ['empty string', ''],
        ['malformed JSON', '{not json'],
        ['a JSON scalar', '42'],
        ['JSON null', 'null'],
    ])('returns null for %s', (_label, raw) => {
        expect(safeParseDetail(raw as any)).toBeNull()
    })

    it('returns the object for well-formed JSON', () => {
        expect(safeParseDetail('{"score":80}')).toEqual({ score: 80 })
    })

    // An array IS an object to typeof, and passes through. Pinned because both callers
    // then read named fields off it and must get undefined, not a crash.
    it('passes a JSON array through rather than crashing on it', () => {
        expect(safeParseDetail('[1,2]')).toEqual([1, 2])
    })
})

describe('parseAssessment', () => {
    it.each([
        ['null', null],
        ['undefined', undefined],
        ['a string', 'match'],
        ['a number', 5],
    ])('returns null for %s, the pre-S2.1 fallback signal', (_label, a) => {
        expect(parseAssessment(a)).toBeNull()
    })

    it('fills every field for an empty object rather than returning null', () => {
        expect(parseAssessment({})).toEqual({
            seniority: { verdict: '', note: '' },
            domain: { verdict: '', note: '' },
            mustHaves: { met: [], missing: [] },
            niceToHaves: { missing: [] },
            summary: '',
        })
    })

    it('reads a full scorecard', () => {
        expect(
            parseAssessment({
                seniority: { verdict: 'match', note: '5 yrs' },
                domain: { verdict: 'adjacent', note: 'fintech' },
                must_haves: { met: ['python'], missing: ['kafka', 'k8s'] },
                nice_to_haves: { missing: ['rust'] },
                summary: 'close',
            }),
        ).toEqual({
            seniority: { verdict: 'match', note: '5 yrs' },
            domain: { verdict: 'adjacent', note: 'fintech' },
            mustHaves: { met: ['python'], missing: ['kafka', 'k8s'] },
            niceToHaves: { missing: ['rust'] },
            summary: 'close',
        })
    })

    // The coercions exist because none of these are type-guaranteed on the wire.
    it('coerces non-string and non-array members instead of trusting them', () => {
        const a = parseAssessment({
            seniority: { verdict: 7, note: null },
            domain: 'mismatch',
            must_haves: { met: 'python', missing: [1, 2] },
            summary: { nested: true },
        })
        expect(a).toEqual({
            seniority: { verdict: '7', note: '' },
            // A string `domain` has no .verdict/.note, so it degrades to blanks.
            domain: { verdict: '', note: '' },
            // A non-array must_haves.met degrades to [], never a spread string.
            mustHaves: { met: [], missing: ['1', '2'] },
            niceToHaves: { missing: [] },
            summary: '[object Object]',
        })
    })
})

describe('verdict presentation', () => {
    it('greens a match, reds a mismatch, ambers everything in between', () => {
        expect(verdictClass('match')).toContain('emerald')
        expect(verdictClass('mismatch')).toContain('red')
        for (const v of ['too_junior', 'too_senior', 'adjacent', '']) {
            expect(verdictClass(v)).toContain('amber')
        }
    })

    it('labels the underscored verdicts and sentence-cases the rest', () => {
        expect(verdictLabel('too_junior')).toBe('Too junior')
        expect(verdictLabel('too_senior')).toBe('Too senior')
        expect(verdictLabel('adjacent')).toBe('Adjacent')
        expect(verdictLabel('')).toBe('')
    })
})
