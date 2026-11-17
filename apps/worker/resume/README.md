# Resume source (user-provided)

This repo ships only a **`resume.txt.example` template**. Real resume files are
**gitignored** (personal data) — never committed or pushed. Each user supplies
their own.

Nothing in the worker reads these files: the screen never sees a résumé. They are
private candidate inputs for onboarding and profile tooling. The version label is the
filename minus a leading `resume_`:

| File | Label / purpose |
|------|-----------------|
| `resume.txt` | Label `resume` — the classic single-resume layout. |
| `resume_quant_dev.txt` | Label `quant_dev` — a targeted version. |
| `resume_swe.txt` | Label `swe` — another targeted version. |
| `personal_profile.txt` | NOT a resume. Optional about-me context (goals, constraints, preferences). |


Files only need to be clean readable UTF-8 text (export from your `.tex`/`.docx`
sources however you like).

```bash
cp resume.txt.example resume.txt       # single version, or
cp resume.txt.example resume_swe.txt   # one file per targeted version
```

## The personal profile (optional)

`personal_profile.txt` is **not a résumé** — it's short about-you context: career stage,
target roles in priority order, roles to avoid, positioning, and honest caveats. Copy
the template and rewrite it for your search:

```bash
cp personal_profile.txt.example personal_profile.txt
```

It never adds a skill your résumé lacks; a real gap is fix-the-résumé signal.
