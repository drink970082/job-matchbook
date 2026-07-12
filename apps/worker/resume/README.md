# Resume source (user-provided)

This repo ships only a **`resume.txt.example` template**. Real resume files are
**gitignored** (personal data) — never committed or pushed. Each user supplies
their own.

The worker loads **every `*.txt` in this directory** as a resume version
(`--resume-dir`, default `resume/`). The version label is the filename minus a
leading `resume_`:

| File | Label / purpose |
|------|-----------------|
| `resume.txt` | Label `resume` — the classic single-resume layout. |
| `resume_quant_dev.txt` | Label `quant_dev` — a targeted version. |
| `resume_swe.txt` | Label `swe` — another targeted version. |
| `personal_profile.txt` | NOT a resume. Optional about-me context (goals, constraints, preferences) the fit scorer uses to judge whether a job suits you. |

With **one** version, scoring behaves exactly as before. With **two or more**,
the Claude fit scorer sees all of them, scores the best-fitting version, and
reports which one to send (`recommended_resume` — shown in the Telegram alert
and the job detail modal).

> ⚠️ Every `*.txt` here is loaded. When you split into targeted versions,
> **delete the old `resume.txt`** or it becomes a third scored version.

Files only need to be clean readable text — the scorer judges fit on content,
not formatting (export from your `.tex`/`.docx` sources however you like).
The directory is mounted read-only into the worker container at `/app/resume`.

```bash
cp resume.txt.example resume.txt       # single version, or
cp resume.txt.example resume_swe.txt   # one file per targeted version
```
