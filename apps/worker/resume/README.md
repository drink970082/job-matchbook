# Resume source (user-provided)

This repo ships only a **`resume.txt.example` template**. Copy it to the real
filename and put **your own** content in — the real file is **gitignored**
(personal data), so it never gets committed or pushed. Each user supplies their own.

```bash
cp resume.txt.example resume.txt       # then edit with YOUR resume
```

The real file is mounted read-only into the worker container at `/app/resume`.

| File | Purpose |
|------|---------|
| `resume.txt` | Plain-text version of your resume. Fed to the Claude fit scorer as your résumé, so the model judges fit on content, not markup. (The local Ollama screen sees only the job's hard requirements, never the résumé.) |

It only needs to be clean readable text — the scorer judges fit on content, not
formatting.

Default (override with `--resume`):
- `ats_worker.run` reads `resume/resume.txt`.
