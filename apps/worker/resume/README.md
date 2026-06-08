# Resume sources (user-provided)

This repo ships only **`*.example` templates**. Copy them to the real filenames
and put **your own** content in — the real files are **gitignored** (personal
data), so they never get committed or pushed. Each user supplies their own.

```bash
cp master.tex.example master.tex      # then edit with YOUR resume
cp resume.txt.example resume.txt       # (or generate it from master.tex — see below)
```

Both real files are mounted read-only into the worker container at `/app/resume`.

| File | Purpose |
|------|---------|
| `master.tex` | Your single-page LaTeX master resume. Claude tailors a copy per high-scoring job (only reordering/rephrasing — never fabricating), then `tectonic` compiles it to PDF. |
| `resume.txt` | Plain-text version of the same resume. Fed to the local Ollama scorer instead of the LaTeX, to save tokens and avoid markup noise. |

You don't have to hand-maintain both: keep `master.tex` as the source of truth
and derive `resume.txt` from it (strip the LaTeX to plain text). It only needs
to be clean readable text — the scorer judges fit on content, not formatting.

Defaults (override with `--resume` / `--master-tex`):
- `ats_worker.run` reads `resume/resume.txt` and `resume/master.tex`.

Keep `master.tex` genuinely one page on its own — the tailor loop condenses, but
starting from a 2-page master makes the single-page guarantee harder.
