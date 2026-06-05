import { NextRequest, NextResponse } from 'next/server'
import { promises as fs } from 'fs'
import path from 'path'
import { prisma } from '@/lib/db'

// Tailored resume PDFs live on a shared volume that the worker writes to and the
// web app reads from. In production that volume is mounted at RESUME_DIR; locally
// we default to ../resumes relative to the app so dev can serve seeded files.
// job_postings.resume_path may be absolute or relative to this base dir.
const RESUME_DIR = process.env.RESUME_DIR || path.resolve(process.cwd(), '..', 'resumes')

export async function GET(
    _req: NextRequest,
    { params }: { params: { id: string } }
) {
    const id = Number(params.id)
    if (!Number.isInteger(id)) {
        return new NextResponse('Not found', { status: 404 })
    }

    const posting = await prisma.job_postings.findUnique({
        where: { id },
        select: { resume_path: true },
    })

    if (!posting || !posting.resume_path) {
        return new NextResponse('Not found', { status: 404 })
    }

    // Resolve the requested path against the base dir and ensure the result stays
    // inside it, to prevent path traversal (e.g. resume_path = "../../etc/passwd").
    const baseDir = path.resolve(RESUME_DIR)
    const resolved = path.resolve(baseDir, posting.resume_path)
    if (resolved !== baseDir && !resolved.startsWith(baseDir + path.sep)) {
        return new NextResponse('Forbidden', { status: 403 })
    }

    try {
        const file = await fs.readFile(resolved)
        return new NextResponse(new Uint8Array(file), {
            status: 200,
            headers: {
                'Content-Type': 'application/pdf',
                'Content-Disposition': `inline; filename="resume-${id}.pdf"`,
                'Cache-Control': 'private, max-age=0, must-revalidate',
            },
        })
    } catch {
        return new NextResponse('Not found', { status: 404 })
    }
}
