"""Tailor the master resume to a job, iterating until it fits on ONE page.

WHY a feedback loop: a tailored resume that spills onto a second page is a
recruiter red flag, but the LLM cannot reliably hit one page in a single shot.
So we compile with tectonic, count pages with pypdf, and if it is too long we
hand the page count back to Claude and ask it to condense — never to fabricate.

The expensive/external pieces are injected so this whole loop is unit-testable
with zero network/subprocess/PDF dependencies:
  - claude(prompt) -> tex_string
  - compile_pdf(tex, out_dir) -> pdf_path
  - count_pages(pdf_path) -> int
Real adapters (make_claude / tectonic_compile / pypdf_count) live at the bottom
and import anthropic/subprocess/pypdf LAZILY so importing this module — and thus
collecting the tests — never requires those packages.
"""
from __future__ import annotations

import tempfile

from ats_worker.prompts import BASE_PROMPT, FABRICATION_GUARD, FEEDBACK_PROMPT


def tailor_resume(
    master_tex: str,
    jd: str,
    missing_keywords,
    *,
    claude,
    compile_pdf,
    count_pages,
    max_rounds: int = 3,
    out_dir: str | None = None,
) -> dict:
    """Run the tailor→compile→measure loop.

    Returns {"tex": str, "pdf_path": str, "pages": int, "ok": bool}. `ok` is
    True iff the final document is exactly one page. Makes at most `max_rounds`
    Claude calls; stops early as soon as it reaches one page.
    """
    work_dir = out_dir or tempfile.mkdtemp(prefix="tailor-")
    missing = ", ".join(missing_keywords) if missing_keywords else "(none)"

    prompt = BASE_PROMPT.format(
        guard=FABRICATION_GUARD,
        missing=missing,
        jd=jd,
        master=master_tex,
    )

    tex = ""
    pdf_path = ""
    pages = 0
    for round_no in range(max_rounds):
        if round_no > 0:
            prompt = FEEDBACK_PROMPT.format(
                pages=pages,
                guard=FABRICATION_GUARD,
                previous=tex,
            )
        tex = claude(prompt)
        pdf_path = compile_pdf(tex, work_dir)
        pages = count_pages(pdf_path)
        if pages == 1:
            break

    return {"tex": tex, "pdf_path": pdf_path, "pages": pages, "ok": pages == 1}


# --- real adapters (exercised only in Docker; never imported at module load) --

def make_claude(api_key: str, model: str, *, max_tokens: int = 8000):
    """Build a `claude(prompt) -> tex` callable backed by the Anthropic SDK.

    `import anthropic` is deferred into the closure so this module imports fine
    in the test environment where the SDK is not installed.
    """
    import anthropic  # lazy: only needed at runtime in Docker

    client = anthropic.Anthropic(api_key=api_key)

    def claude(prompt: str) -> str:
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in msg.content if getattr(block, "type", None) == "text"
        )

    return claude


def tectonic_compile(tex: str, out_dir: str) -> str:
    """Compile `tex` to a PDF via the `tectonic` CLI; return the PDF path."""
    import os
    import subprocess  # lazy

    os.makedirs(out_dir, exist_ok=True)
    tex_path = os.path.join(out_dir, "resume.tex")
    with open(tex_path, "w", encoding="utf-8") as fh:
        fh.write(tex)
    subprocess.run(
        ["tectonic", "--keep-logs", "--outdir", out_dir, tex_path],
        check=True,
        capture_output=True,
    )
    return os.path.join(out_dir, "resume.pdf")


def pypdf_count(path: str) -> int:
    """Count pages in a PDF using pypdf."""
    import pypdf  # lazy

    return len(pypdf.PdfReader(path).pages)
