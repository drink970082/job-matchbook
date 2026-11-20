#!/usr/bin/env node
// One-off data migration for #230: closure is source state, so a row the old run_expire
// parked as pipeline_status='expired' becomes source_state='closed' with lifecycle 'new'
// (the only live state the expire stage still selects). Closed rows stay out of the
// screen, JEV and "Postings for you". Data only, no DDL. Idempotent. Back up db/ first,
// and run `make db-push` for the new source_absent_count column before the new worker.
//   node apps/web/prisma/migrate-expired-230.mjs file:/abs/path/applications.db
import { PrismaClient } from '@prisma/client'

const url = process.argv[2] || process.env.DATABASE_URL
if (!url) throw new Error('usage: migrate-expired-230.mjs <DATABASE_URL>')
const prisma = new PrismaClient({ datasourceUrl: url })

const migrated = await prisma.$executeRaw`UPDATE job_postings
    SET source_state = 'closed', pipeline_status = 'new',
        source_last_check_outcome = 'confirmed_closed'
    WHERE pipeline_status = 'expired'`
console.log(JSON.stringify({ migrated }))
await prisma.$disconnect()
