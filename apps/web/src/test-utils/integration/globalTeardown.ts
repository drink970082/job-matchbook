/** Remove the throwaway integration DB created in globalSetup. */
import { readFileSync, rmSync } from 'node:fs'
import { POINTER } from './globalSetup'

export default async function globalTeardown() {
    try {
        const { dir } = JSON.parse(readFileSync(POINTER, 'utf8'))
        rmSync(dir, { recursive: true, force: true })
    } catch {
        // nothing to clean up
    }
    // Remove the pointer too, so a crashed prior run can't leave setEnv aiming at
    // a since-deleted temp path on the next invocation.
    rmSync(POINTER, { force: true })
}
