"""Second, independent labeller for the score golden set — codex, with a CONFIDENCE.

WHY a second labeller: the 119 rows need human verdicts, and a human reviewing 119 JDs is
a 2-3 hour sitting. Two independent labellers plus a confidence signal turns that into
"review only where they disagree or where either is unsure", which is a much smaller set —
and it lands on exactly the rows worth a human, because the `near` band is where labellers
diverge.

WHAT THIS IS NOT: a way to skip the human. Rows where both labellers agree become golden
labels shaped by models, so `make eval-score` then partly measures a model against
model-flavoured labels. That is the circularity the human set exists to escape, accepted
here deliberately and bounded by operator review of the divergent rows. It does NOT catch
rows where both labellers are confidently wrong the same way.

WHY NOT reuse the stored Sol verdicts in `golden_expanded.jsonl`: they exist and are free,
but they are single draws from the PRODUCTION scoring prompt, sol's own flip-rate is 22%,
and they carry no confidence. A fresh call with a labelling prompt is what makes the
review-subset selectable.

One call per posting. NOT batched: batching bleeds domain verdicts across postings at
every size > 1 (measured 2026-07-17), and a corpus label is exactly the thing that must
not be contaminated by its neighbours.
"""
import json
import os
import subprocess
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]   # tools -> worker -> apps -> repo root
EVAL = Path(__file__).resolve().parents[1] / "eval"
FRAME = EVAL / "golden_expanded.jsonl"
GOLDEN = EVAL / "golden.jsonl"
OUT = EVAL / "codex_labels.jsonl"
PROFILE = ROOT / "apps/worker/resume/personal_profile.txt"
DB = f"file:{ROOT}/db/applications.db?mode=ro"
MODEL = os.environ.get("CODEX_LABEL_MODEL", "gpt-5.6-sol")

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["seniority", "domain", "confidence", "why"],
    "properties": {
        "seniority": {"type": "string", "enum": ["match", "too_junior", "too_senior"]},
        "domain": {"type": "string", "enum": ["match", "adjacent", "mismatch"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "why": {"type": "string"},
    },
}

# The DOMAIN rule is lifted VERBATIM from the production rubric (ats_worker/prompts/
# score.txt, the `domain` bullet), not paraphrased. A first version of this file wrote its
# own summary of it and produced a labeller that called 37 of 50 rows `match` where the
# SAME model family scoring the SAME postings through score.txt called them `adjacent`.
# The paraphrase silently dropped check (3) BACKGROUND, which is what keeps "a target-fit
# the resume does not back" out of `match`. Corpus labels must be calibrated to the rubric
# the gate actually uses, or the gate measures the gap between two PROMPTS rather than
# between two models.
DOMAIN_RULE = """This is a FIELD-level question - a specific missing skill does not belong here.
Run THREE checks against the PERSONAL PROFILE and the RESUME, and record each in `why`:
  (1) ANTI - does the role's work fall under ANTI-TARGETS? An ANTI-TARGETS entry ALWAYS
      wins over any TARGET entry the role also appears to match.
  (2) TARGET - which TARGET priority does the role's work fall under, if any? Decide from
      the role's ACTUAL DAY-TO-DAY WORK as the JOB describes it, NOT its title: a
      "Researcher"/"Analyst" title whose stated work includes designing and building
      systems IS an engineering seat; an "Engineer" title whose stated work is producing
      research, signals, or alpha is NOT.
  (3) BACKGROUND - does the RESUME evidence work in this role's field (the same kind of
      work, not a shared language or tool)? Wanting the role is not having done it; the
      PROFILE is not evidence of background.
Then:
  mismatch  if (1) is yes, OR the work matches no TARGET priority AND (3) is no
  match     if (1) is no AND the work is TARGET priority 1-3 AND (3) is yes
  adjacent  otherwise - a lower-priority target (4-5), a target-fit the resume does not
            back, or a background-fit that is no stated target"""

PROMPT = """You are labelling a corpus for a job-matching evaluation. Judge this posting
against the candidate profile and resume below, and return two verdicts plus a confidence.

SENIORITY - one of match / too_junior / too_senior, measured ONLY against a level the JOB
explicitly states: a stated MINIMUM number of years ("2+ years", "minimum 2 years") is
such a bar, but a range starting at 0-1 ("0-2 years", "1-3 years") or a cap ("up to N") is
entry/early-career and is NOT; a rank like senior/lead/staff/principal IS. If the role
states no such bar, the verdict is `match`. Implied ownership or autonomy is NOT seniority.

THE VERDICT DESCRIBES THE CANDIDATE, NOT THE JOB. This candidate is a new grad, so a role
stating 5+ years or a Senior/Staff rank makes the CANDIDATE `too_junior` for it - NOT
`too_senior`. `too_senior` is the opposite and rare case: the ROLE sits below this
candidate's level (an internship, or a part-time student assistantship).

DOMAIN - one of match / adjacent / mismatch.
{domain_rule}

CONFIDENCE - be honest, this routes human review:
  high    the JD states what is needed and none of the three checks is close
  medium  a reasonable reading, but another careful reader could differ
  low     genuinely ambiguous, thin JD, or a check sits on a boundary

=== PERSONAL PROFILE ===
{profile}

=== RESUME ===
{resume}

=== POSTING ===
Company: {company}
Title: {title}
Location: {location}

{description}
"""


def label_one(profile: str, resume: str, row: sqlite3.Row) -> dict | None:
    prompt = PROMPT.format(
        domain_rule=DOMAIN_RULE, profile=profile, resume=resume,
        company=row["company_name"], title=row["job_title"],
        location=row["location"] or "not stated",
        description=(row["description"] or "")[:12000])
    schema_path = EVAL / ".codex_label_schema.json"
    schema_path.write_text(json.dumps(SCHEMA))
    try:
        p = subprocess.run(
            ["codex", "exec", "--model", MODEL, "--sandbox", "read-only",
             "--skip-git-repo-check", "--ephemeral",
             "--output-schema", str(schema_path), "-"],
            input=prompt, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return None
    if p.returncode != 0:
        return None
    # codex prints the schema-constrained object as the last JSON object on stdout
    for line in reversed(p.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                d = json.loads(line)
                if "seniority" in d and "domain" in d:
                    return d
            except json.JSONDecodeError:
                continue
    return None


def main() -> int:
    profile = PROFILE.read_text()
    # check (3) BACKGROUND needs the RESUME: the rubric is explicit that "the PROFILE is
    # not evidence of background".
    resume = "\n\n".join(p.read_text() for p in sorted(
        (ROOT / "apps/worker/resume").glob("resume_*.txt")))
    done = {json.loads(l)["id"] for l in OUT.read_text().splitlines()
            if l.strip()} if OUT.exists() else set()
    labelled = {json.loads(l)["id"] for l in GOLDEN.read_text().splitlines()
                if l.strip() and "id" in json.loads(l)} if GOLDEN.exists() else set()
    frame = [json.loads(l) for l in FRAME.read_text().splitlines() if l.strip()]
    todo = [r for r in frame
            if r["band"] in ("near", "keep") and r["id"] not in done
            and r["id"] not in labelled]
    todo.sort(key=lambda r: (r["band"] != "near", r["id"]))
    if "--limit" in sys.argv:
        todo = todo[:int(sys.argv[sys.argv.index("--limit") + 1])]

    conn = sqlite3.connect(DB, uri=True)
    conn.row_factory = sqlite3.Row
    print(f"{len(done)} already done · {len(todo)} to label on {MODEL}", file=sys.stderr)
    ok = fail = 0
    with OUT.open("a") as fh:
        for n, r in enumerate(todo, 1):
            row = conn.execute(
                "SELECT job_title, company_name, location, description "
                "FROM job_postings WHERE id=?", (r["id"],)).fetchone()
            if row is None:
                continue
            got = label_one(profile, resume, row)
            if got is None:
                print(f"[{n}/{len(todo)}] id={r['id']} FAILED", file=sys.stderr)
                fail += 1
                continue
            fh.write(json.dumps({"id": r["id"], "band": r["band"], **got}) + "\n")
            fh.flush()   # resumable: every label is on disk before the next call
            ok += 1
            print(f"[{n}/{len(todo)}] id={r['id']} {got['seniority']}/{got['domain']} "
                  f"({got['confidence']})", file=sys.stderr)
    print(f"\nlabelled {ok}, failed {fail} -> {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
