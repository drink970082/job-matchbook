/** Remove the throwaway integration DB created in globalSetup. */
import { rmSync } from 'node:fs'
import { IT_DB_DIR } from './globalSetup'

export default async function globalTeardown() {
    const dir = process.env[IT_DB_DIR]
    if (dir) rmSync(dir, { recursive: true, force: true })
}
