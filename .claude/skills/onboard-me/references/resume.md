# Résumé ingestion — fallbacks and the multi-version rule

## When the file won't render

- **PDF that won't render** (scanned / image-only, or no rasterizer available) — ask
  them to paste the text or export a `.txt`. Don't dead-end on it.
- **`.docx` you'd rather not unzip** — asking them to export a PDF or paste the text
  is a fine answer. Never add a parsing dependency for this.

Either way, a résumé you couldn't read is a question for the user, not a reason to
guess at content or to write a placeholder file.

## Multi-version naming (from `apps/worker/resume/README.md`)

**Every `*.txt` in `apps/worker/resume/` is loaded as a résumé version.** So:

- One résumé → `resume.txt`, nothing else.
- Role-targeted versions → name them `resume_<label>.txt` **and delete the generic
  `resume.txt`**, or the generic one gets scored alongside the targeted ones.

These files are gitignored personal data — never commit them.
