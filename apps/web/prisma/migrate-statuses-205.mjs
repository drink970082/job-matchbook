#!/usr/bin/env node
// One-off data migration for #205: the 14 application statuses collapse to 7.
// Rewrites applications.status and status_history.status through the shared map, then
// drops history rows that repeat the previous row's status for the same application
// (1st round -> 2nd round becomes Interviewing -> Interviewing). Data only, no DDL.
// Idempotent. Back up db/ first.
//   node apps/web/prisma/migrate-statuses-205.mjs file:/abs/path/applications.db
import { readFileSync } from 'node:fs'
import { PrismaClient } from '@prisma/client'

const url = process.argv[2] || process.env.DATABASE_URL
if (!url) throw new Error('usage: migrate-statuses-205.mjs <DATABASE_URL>')
const map = JSON.parse(readFileSync(new URL('../src/lib/legacy-statuses.json', import.meta.url), 'utf8'))
const prisma = new PrismaClient({ datasourceUrl: url })

const result = await prisma.$transaction(async (tx) => {
    let apps = 0, history = 0
    for (const [from, to] of Object.entries(map)) {
        apps += await tx.$executeRaw`UPDATE applications SET status = ${to} WHERE status = ${from}`
        history += await tx.$executeRaw`UPDATE status_history SET status = ${to} WHERE status = ${from}`
    }
    const rows = await tx.$queryRaw`SELECT id, application_id, status FROM status_history ORDER BY application_id, timestamp, id`
    const dupes = rows.filter((r, i) => i > 0 && rows[i - 1].application_id === r.application_id && rows[i - 1].status === r.status)
    for (const r of dupes) await tx.$executeRaw`DELETE FROM status_history WHERE id = ${r.id}`
    return { applications: apps, status_history: history, duplicates_dropped: dupes.length }
})
console.log(JSON.stringify(result))
await prisma.$disconnect()
