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
}
