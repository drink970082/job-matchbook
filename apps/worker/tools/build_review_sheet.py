#!/usr/bin/env python3
"""Build `eval/golden_review.html` — the sheet `eval/review_server.py` serves.

Nothing generated this file before: the server has always served it and collected
answers into `golden_review_answers.json`, but the page itself was hand-built once and
could not be regenerated. This closes that.

Input is two label files from `tools/label_run.py` (one per backend). Rows where the
backends DISAGREE go in the review queue. Rows where they agree are consensus — listed
compactly, plus a deterministic random AUDIT SAMPLE surfaced for review, because two
backends can be confidently wrong the same way and a consensus-only corpus has no way
to notice (row 25206, UPS generic enterprise app support labelled `match`, is the
standing example).

The operator's prior answers appear as a third column, CONTEXT ONLY. They were written
while the profile and title filters were mid-edit — two of them already contradict rules
set later the same day — so they are shown to make confirming or overriding cheap, never
to score anything.

    PYTHONPATH=. python3 tools/build_review_sheet.py \\
        --codex eval/codex_labels_20260802.jsonl \\
        --claude eval/claude_code_labels_20260802.jsonl
    cd /home/halcyon/root/ats && python3 apps/worker/eval/review_server.py
"""
from __future__ import annotations

import argparse
import html
import json
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps/worker"))

DB = ROOT / "db/applications.db"
EVAL = ROOT / "apps/worker/eval"
AUDIT_SEED = 20260802  # fixed: regenerating the sheet must not reshuffle the sample


def read_labels(path: Path) -> dict:
    out = {}
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            out[int(row["id"])] = row
    return out


def classify(codex: dict, claude: dict) -> tuple[list, list]:
    """(disagreements, consensus) over the ids both backends labelled successfully."""
    both = sorted(set(codex) & set(claude))
    dis, con = [], []
    for i in both:
        c, k = codex[i], claude[i]
        if c.get("error") or k.get("error"):
            dis.append(i)          # a failure is worth a human look, not a silent drop
        elif (c.get("seniority"), c.get("domain")) == (k.get("seniority"), k.get("domain")):
            con.append(i)
        else:
            dis.append(i)
    return dis, con


def _verdict_cell(row: dict) -> str:
    if row.get("error"):
        return f'<span class="err">ERROR: {html.escape(str(row["error"])[:120])}</span>'
    return (f'<b>{html.escape(str(row.get("seniority")))}</b> / '
            f'<b>{html.escape(str(row.get("domain")))}</b>'
            f' <span class="sc">({row.get("score")})</span>')


def _prior_cell(prior: dict | None) -> str:
    if not prior:
        return '<span class="none">-</span>'
    if prior.get("exclude") == "reject":
        return '<span class="rej">rejected</span>'
    return (f'{html.escape(str(prior.get("seniority")))} / '
            f'{html.escape(str(prior.get("domain")))}')


def render_row(i, title, company, jd, codex, claude, prior, kind) -> str:
    notes = "".join(
        f'<div class="note"><span class="who">{who}</span> {html.escape(str(n))}</div>'
        for who, n in (("codex", codex.get("domain_note")),
                       ("claude", claude.get("domain_note"))) if n)
    prior_note = ""
    if prior and prior.get("note"):
        prior_note = (f'<div class="note prior"><span class="who">you, earlier</span> '
                      f'{html.escape(str(prior["note"]))}</div>')
    return f"""
<section class="row {kind}" id="row-{i}" data-id="{i}">
  <header>
    <span class="id">#{i}</span>
    <span class="title">{html.escape(title or "")}</span>
    <span class="co">{html.escape(company or "")}</span>
    <span class="kind">{kind}</span>
  </header>
  <table class="verdicts">
    <tr><th>codex</th><th>claude-code</th><th>you, earlier (context only)</th></tr>
    <tr><td>{_verdict_cell(codex)}</td><td>{_verdict_cell(claude)}</td>
        <td>{_prior_cell(prior)}</td></tr>
  </table>
  {notes}{prior_note}
  <div class="answer">
    <label>seniority
      <select data-field="seniority">
        <option value=""></option><option>match</option>
        <option>too_junior</option><option>too_senior</option>
      </select></label>
    <label>domain
      <select data-field="domain">
        <option value=""></option><option>match</option>
        <option>adjacent</option><option>mismatch</option>
      </select></label>
    <label class="rejlbl"><input type="checkbox" data-field="exclude"> drop from corpus</label>
    <input class="notein" data-field="note" placeholder="why (optional)">
    <span class="saved"></span>
  </div>
  <details><summary>JD</summary><pre>{html.escape((jd or "")[:6000])}</pre></details>
</section>"""


CSS = """
:root{--bg:#111417;--fg:#e6e6e6;--dim:#9aa0a6;--line:#2a2f35;--acc:#7fb3ff}
*{box-sizing:border-box}
body{margin:0;padding:1.5rem;background:var(--bg);color:var(--fg);
 font:14px/1.5 ui-sans-serif,system-ui,-apple-system,sans-serif}
h1{font-size:1.2rem;margin:0 0 .3rem}
.lede{color:var(--dim);max-width:70ch;margin:0 0 1.2rem}
.lede b{color:var(--fg)}
.bar{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);
 padding:.6rem 0;margin-bottom:1rem;z-index:5;display:flex;gap:1rem;align-items:center}
.row{border:1px solid var(--line);border-radius:8px;padding:.8rem 1rem;margin:0 0 .9rem}
.row.consensus{opacity:.72}
.row.audit{border-color:#5a4a1f}
header{display:flex;gap:.7rem;align-items:baseline;flex-wrap:wrap;margin-bottom:.5rem}
.id{color:var(--dim);font-variant-numeric:tabular-nums}
.title{font-weight:600}
.co{color:var(--dim)}
.kind{margin-left:auto;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;
 color:var(--dim)}
.verdicts{border-collapse:collapse;margin:.2rem 0 .5rem}
.verdicts th{text-align:left;font-weight:500;color:var(--dim);font-size:.78rem;
 padding:0 1.6rem .1rem 0}
.verdicts td{padding:0 1.6rem .2rem 0;vertical-align:top}
.sc{color:var(--dim)}
.err{color:#ff8b8b}
.rej{color:#ffb454}
.none{color:var(--dim)}
.note{color:var(--dim);font-size:.85rem;margin:.15rem 0}
.note .who{display:inline-block;min-width:5.5rem;color:#6f7b88}
.note.prior{color:#c9a227}
.answer{display:flex;gap:.9rem;align-items:center;flex-wrap:wrap;margin:.6rem 0 .2rem}
label{color:var(--dim);font-size:.85rem}
select,input.notein{background:#181c20;color:var(--fg);border:1px solid var(--line);
 border-radius:5px;padding:.25rem .4rem;font:inherit}
input.notein{min-width:22rem;flex:1}
.saved{color:#5fd08a;font-size:.8rem;min-width:4rem}
details{margin-top:.4rem}
summary{color:var(--acc);cursor:pointer;font-size:.85rem}
pre{white-space:pre-wrap;background:#0c0f11;border:1px solid var(--line);border-radius:6px;
 padding:.7rem;max-height:24rem;overflow:auto;color:#c8ccd0}
"""

JS = """
const answers = {};
async function load(){
  try{ Object.assign(answers, await (await fetch('/answers')).json()); }catch(e){}
  document.querySelectorAll('.row').forEach(row=>{
    const a = answers[row.dataset.id]; if(!a) return;
    row.querySelectorAll('[data-field]').forEach(el=>{
      const v = a[el.dataset.field];
      if(el.type==='checkbox') el.checked = (v==='reject');
      else if(v!=null) el.value = v;
    });
  });
  count();
}
let timer=null;
function save(row){
  const id=row.dataset.id, a={};
  row.querySelectorAll('[data-field]').forEach(el=>{
    if(el.type==='checkbox'){ if(el.checked) a.exclude='reject'; }
    else if(el.value) a[el.dataset.field]=el.value;
  });
  if(Object.keys(a).length) answers[id]=a; else delete answers[id];
  const tag=row.querySelector('.saved'); tag.textContent='saving';
  clearTimeout(timer);
  timer=setTimeout(async()=>{
    const r=await fetch('/answers',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(answers)});
    document.querySelectorAll('.saved').forEach(s=>s.textContent='');
    tag.textContent = r.ok ? 'saved' : 'FAILED';
    count();
  },400);
}
function count(){
  const n=Object.keys(answers).length;
  document.getElementById('count').textContent = n+' answered';
}
document.addEventListener('input',e=>{
  const row=e.target.closest('.row'); if(row) save(row);
});
load();
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--codex", type=Path, required=True)
    ap.add_argument("--claude", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=EVAL / "golden_review.html")
    ap.add_argument("--answers", type=Path, default=EVAL / "golden_review_answers.json")
    ap.add_argument("--audit", type=int, default=25,
                    help="consensus rows to surface for audit (0 = none)")
    args = ap.parse_args()

    codex, claude = read_labels(args.codex), read_labels(args.claude)
    dis, con = classify(codex, claude)
    prior = {}
    if args.answers.exists():
        prior = {int(k): v for k, v in json.loads(args.answers.read_text()).items()}

    rng = random.Random(AUDIT_SEED)
    audit = set(rng.sample(con, min(args.audit, len(con))))

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ids = dis + con
    meta = {r[0]: r[1:] for r in conn.execute(
        f"SELECT id, job_title, company_name, description FROM job_postings "
        f"WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
    conn.close()

    order = ([(i, "disagreement") for i in dis]
             + [(i, "audit") for i in con if i in audit]
             + [(i, "consensus") for i in con if i not in audit])
    body = "".join(
        render_row(i, *(meta.get(i) or ("", "", "")), codex[i], claude[i],
                   prior.get(i), kind)
        for i, kind in order)

    page = f"""<!doctype html><html><head><meta charset="utf-8">
<title>golden review — {len(dis)} to review</title><style>{CSS}</style></head><body>
<h1>Golden set review</h1>
<p class="lede">{len(dis)} <b>disagreements</b> (the queue) &middot;
{len(audit)} <b>audit</b> rows sampled from {len(con)} consensus rows &middot;
{len(con) - len(audit)} consensus rows below them.
Both backends scored these <b>blind</b> — no prior label was in the prompt.
Your earlier answers are shown as <b>context only</b>: they were written while the
profile and filters were mid-edit, so some encode rules that changed. Consensus is not
truth — two backends can be wrong the same way, which is what the audit sample is for.
Answers autosave to <code>golden_review_answers.json</code>.</p>
<div class="bar"><b id="count">0 answered</b><span class="lede" style="margin:0">
edits save automatically</span></div>
{body}
<script>{JS}</script></body></html>"""
    args.out.write_text(page, encoding="utf-8")
    print(f"{len(dis)} disagreements, {len(con)} consensus ({len(audit)} audited) "
          f"-> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
