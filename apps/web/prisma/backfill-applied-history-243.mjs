#!/usr/bin/env node
// One-off data backfill for #243: every application gets its initial Applied
// status_history row, and applications.status is recomputed as the status of the latest
// history row by timestamp (ties by id), the rule the web now applies on every write.
// - An application with no Applied row gets one at the start of date_applied (UTC; now
//   if date_applied is not YYYY-MM-DD), or 1 ms before its earliest existing row if that
//   is earlier, so it always sorts first.
// - An application with no history at all and a non-Applied status also gets a row with
//   that status on the same timestamp (the later id makes it current).
// Data only, no DDL. Idempotent: a second run reports all zeros. Back up db/ first.
//   cp -a db db.bak-$(date +%F)
//   node apps/web/prisma/backfill-applied-history-243.mjs file:/abs/path/applications.db
import { PrismaClient } from '@prisma/client'

const url = process.argv[2] || process.env.DATABASE_URL
if (!url) throw new Error('usage: backfill-applied-history-243.mjs <DATABASE_URL>')
const prisma = new PrismaClient({ datasourceUrl: url })

const result = await prisma.$transaction(async (tx) => {
    let applied = 0, status = 0, recomputed = 0
    const apps = await tx.applications.findMany({ select: { id: true, date_applied: true, status: true, actor: true,
        status_history: { select: { status: true, timestamp: true }, orderBy: [{ timestamp: 'asc' }, { id: 'asc' }] } } })
    for (const app of apps) {
        const history = app.status_history
        if (history.some((h) => h.status === 'Applied')) continue
        // A date_applied that does not start YYYY-MM-DD falls back to now (then before the
        // earliest existing row, below).
        let timestamp = /^\d{4}-\d{2}-\d{2}(T|$)/.test(app.date_applied)
            ? `${app.date_applied.slice(0, 10)}T00:00:00.000Z` : new Date().toISOString()
        const earliest = history[0]?.timestamp
        if (earliest !== undefined && earliest <= timestamp) {
            const ms = Date.parse(earliest)
            if (!Number.isNaN(ms)) timestamp = new Date(ms - 1).toISOString()
        }
        await tx.status_history.create({ data: { application_id: app.id, status: 'Applied', timestamp, actor: app.actor } })
        applied++
        if (history.length === 0 && app.status !== 'Applied') {
            await tx.status_history.create({ data: { application_id: app.id, status: app.status, timestamp, actor: app.actor } })
            status++
        }
    }
    for (const app of await tx.applications.findMany({ select: { id: true, status: true } })) {
        const latest = await tx.status_history.findFirst({
            where: { application_id: app.id }, orderBy: [{ timestamp: 'desc' }, { id: 'desc' }] })
        const next = latest?.status ?? 'Applied'
        if (next !== app.status) {
            await tx.applications.update({ where: { id: app.id }, data: { status: next } })
            recomputed++
        }
    }
    return { applied_rows_added: applied, status_rows_added: status, statuses_recomputed: recomputed }
}, { timeout: 120_000 })
console.log(JSON.stringify(result))
await prisma.$disconnect()
