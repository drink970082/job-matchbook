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

> Note: every `*.txt` here is loaded. When you split into targeted versions,
> **delete the old `resume.txt`** or it becomes a third scored version.

Files only need to be clean readable text — the scorer judges fit on content,
not formatting (export from your `.tex`/`.docx` sources however you like).
Files must be UTF-8; a non-UTF-8 file aborts startup, naming the offending file.
The directory is mounted read-only into the worker container at `/app/resume`.

```bash
cp resume.txt.example resume.txt       # single version, or
cp resume.txt.example resume_swe.txt   # one file per targeted version
```

## The personal profile (optional but high-leverage)

`personal_profile.txt` is **not a résumé** — it's short about-you context that shapes
*fit*, and it's what the scorer's **domain verdict** matches a role against. Copy the
template and rewrite it for your search:

```bash
cp personal_profile.txt.example personal_profile.txt
```

It has a light structure the scorer relies on (works for any field — finance, product,
design, engineering, …):

- **STAGE** — your career stage, so "right seniority" means the right thing for you.
- **TARGET (priority order)** — the roles/fields you actually want, described by their
  day-to-day work. A role matching priority 1-3 and backed by your résumé scores as a
  domain `match`; lower tiers are `adjacent`.
- **ANTI-TARGETS** — roles you'd pass the screen for but don't want; they score *down*
  and always beat any TARGET a role also seems to match.
- **POSITIONING / INTERESTS / CAVEATS** — how you frame yourself, genuine interests (the
  one honest lever that raises fit), and any honest downward caveats.

It never adds a skill your résumé lacks (a recruiter sees the résumé, not this) — a real
gap is fix-the-résumé signal. Keep it concise and stable; it's sent on every scoring call.
