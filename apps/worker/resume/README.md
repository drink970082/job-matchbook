# Resume sources (user-provided)

Drop your two master resume files here. They are gitignored (personal data) and
mounted read-only into the worker container at `/app/resume`.

| File | Purpose |
|------|---------|
| `master.tex` | Your single-page LaTeX master resume. Claude tailors a copy per high-scoring job (only reordering/rephrasing — never fabricating), then `tectonic` compiles it to PDF. |
| `resume.txt` | Plain-text version of the same resume. Fed to the local Ollama scorer instead of the LaTeX, to save tokens and avoid markup noise. |

Defaults (override with `--resume` / `--master-tex`):
- `ats_worker.run` reads `resume/resume.txt` and `resume/master.tex`.

Keep `master.tex` genuinely one page on its own — the tailor loop condenses, but
starting from a 2-page master makes the single-page guarantee harder.
