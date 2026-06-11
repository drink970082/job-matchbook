#!/usr/bin/env node
// Fail if apps/worker/tests/fixtures/schema.sql drifts from the Prisma schema.
// Prisma owns the real schema (no migrations); the fixture is a hand-kept copy
// the worker tests bootstrap from. Parse-only (no DB), mirrors the pytest guard
// tests/test_schema_sync.py so `make check-schema` works without Python.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
// Strip // comments first: some contain { } that would break brace-matching.
const prismaText = readFileSync(join(root, 'apps/web/prisma/schema.prisma'), 'utf8').replace(/\/\/.*/g, '')
const sqlText = readFileSync(join(root, 'apps/worker/tests/fixtures/schema.sql'), 'utf8')

const models = {}
for (const m of prismaText.matchAll(/model\s+(\w+)\s*\{([\s\S]*?)\}/g)) models[m[1]] = m[2]
const modelNames = new Set(Object.keys(models))

const prismaFields = {}
for (const [name, body] of Object.entries(models)) {
    const fields = new Set()
    for (const raw of body.split('\n')) {
        const line = raw.trim()
        if (!line || line.startsWith('@@')) continue
        const parts = line.split(/\s+/)
        if (parts.length < 2) continue
        const type = parts[1].replace(/[?[\]]/g, '')
        if (modelNames.has(type)) continue // relation field, not a column
        fields.add(parts[0])
    }
    prismaFields[name] = fields
}

const sqlCols = {}
for (const m of sqlText.matchAll(/CREATE TABLE "(\w+)"\s*\(([\s\S]*?)\n\);/g)) {
    const cols = new Set()
    for (const raw of m[2].split('\n')) {
        const line = raw.trim()
        const cm = line.match(/^"(\w+)"/)
        if (cm && !line.startsWith('CONSTRAINT')) cols.add(cm[1])
    }
    sqlCols[m[1]] = cols
}

let drift = false
const fail = (msg) => { console.error('DRIFT: ' + msg); drift = true }
for (const [model, fields] of Object.entries(prismaFields)) {
    const cols = sqlCols[model]
    if (!cols) { fail(`schema.sql is missing table "${model}"`); continue }
    for (const f of fields) if (!cols.has(f)) fail(`"${model}" is missing column "${f}"`)
    for (const c of cols) if (!fields.has(c)) fail(`"${model}" has column "${c}" not in Prisma`)
}

if (drift) {
    console.error('\nschema.sql is OUT OF SYNC with apps/web/prisma/schema.prisma')
    process.exit(1)
}
console.log('schema.sql is in sync with apps/web/prisma/schema.prisma')
