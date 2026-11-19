# Resume source (user-provided)

This repo ships only **`*.example` templates** here. Everything else in this directory
is **gitignored** (personal data) — never committed or pushed. Each user supplies their
own.

The worker reads only the JEV packs under your configured `jev_dir` (conventionally
`resume/jev/`, copied from `../jev.example/`; see `docs/SETUP.md` Path C2). The screen
never sees a résumé. The other files here are private material for your AI client and the
`onboard-me` skill:

| File | Purpose |
|------|---------|
| `resume.txt` | Your résumé as plain text. |
| `resume_<label>.txt` | Optional role-targeted versions instead of one `resume.txt` (e.g. `resume_swe.txt`). |
| `personal_profile.txt` | NOT a résumé. Optional about-me context (goals, constraints, preferences). |
| `jev/` | Your JEV keep/skip packs, when you use `--jev`. |

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
