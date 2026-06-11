#!/usr/bin/env node
// CLI seeder for the e2e / local throwaway DB, reusing the single source of truth
// in apps/web/e2e/helpers/seed.mjs. @prisma/client resolves from apps/web's
// node_modules (node walks up from the imported module's directory), so this runs
// from any cwd:  node tools/seed_db.mjs [file:/path/to.db]
import { DATABASE_URL } from '../apps/web/e2e/helpers/db-path.mjs'
import { seed } from '../apps/web/e2e/helpers/seed.mjs'

const url = process.argv[2] || DATABASE_URL
seed(url)
    .then(() => console.log('seeded', url))
    .catch((err) => {
        console.error(err)
        process.exit(1)
    })
