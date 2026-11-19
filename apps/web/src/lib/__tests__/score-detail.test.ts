import { safeParseDetail } from '@/lib/score-detail'

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
