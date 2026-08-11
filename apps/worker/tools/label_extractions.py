"""Hand-label step 4: graded relevance per posting, plus which extraction arm got it right.

    PYTHONPATH=. python3 tools/label_extractions.py --eval-dir /abs/path/to/apps/worker/eval
    -> http://127.0.0.1:8766/

Code may run from a worktree while the corpora live in the primary tree, because
`eval/` is gitignored and exists only there -- so `--eval-dir` is the one flag that
matters. Everything else has a working default.

WHAT IT ASKS FOR, per the rebuild plan's step 4:

  relevance   3 high priority | 2 worth applying | 1 borderline | 0 not worth it
              Graded, not binary: NDCG@K needs graded relevance.
  extraction  which arm read the posting correctly -- A, B, both, or neither.

TWO THINGS ARE DELIBERATELY BLIND.

  1. Arm A/B is randomised per row (seeded), so a labeller cannot systematically
     favour a model. The queue file records the mapping; answers stay in A/B terms
     and are decoded at analysis time.
  2. The queue does not say why a row is in it. Disagreement rows and agreement-sample
     rows look identical, or the sample stops being a sample.

THE QUEUE is every row where the arms disagree in a way the downstream arithmetic
would read, plus a stratified sample of the rows where they agree. The sample is not
optional: closed-vocabulary extraction should raise agreement, and higher agreement
means a LARGER blind region where both models are wrong together and nobody looks.

Answers autosave to `extract_labels.json` in the eval dir. Writes are atomic (temp
file + os.replace) with one `.bak` generation, because hand-typed labels are
unrecoverable and a truncated write is the failure that matters here. Binds 127.0.0.1
only: the JDs and the labelled corpus do not belong on the LAN.
"""
import argparse
import json
import os
import random
import re
import shutil
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8766
SEED = 0
AGREE_SAMPLE = 45
# Rows where BOTH arms declare `insufficient_context` are kept only this many times. They
# cannot separate the arms -- there is nothing to extract -- and the thinness is a FETCH
# defect, not a model difference: it tracks the fetch source (icims 4/4, browser 12/15,
# custom 16/30) and not the employer, so the stored description is the marketing lede with
# the body missing. A few are kept because D2's empty-group rule still needs cases.
THIN_KEEP = 5


# --------------------------------------------------------------------------- queue

def _load_arm(path):
    """id -> row, skipping the run_header. Error rows are dropped by the caller."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("kind") == "run_header":
            continue
        out[row["id"]] = row
    return out


def _concepts(extraction):
    ids = set()
    for key in ("duties", "required_qualifications"):
        for item in extraction.get(key) or []:
            ids.update((item.get("concept_mapping") or {}).get("concept_ids") or [])
    return ids


def _dominant(extraction):
    """The concept a duty-weighted vote lands on -- what a domain verdict turns on.

    Core duties count double: the plan's arithmetic is not built yet, so this is a
    stand-in for "the concept this posting is mostly about", used ONLY to decide
    whether a row is worth a human's time. It never reaches a label.
    """
    votes = Counter()
    for item in extraction.get("duties") or []:
        weight = 2 if item.get("importance") == "core" else 1
        for cid in (item.get("concept_mapping") or {}).get("concept_ids") or []:
            votes[cid] += weight
    return votes.most_common(1)[0][0] if votes else None


_WORD = re.compile(r"[a-z0-9]+")
SECTIONS = ("duties", "required_qualifications", "nice_to_haves")


def _item_tokens(item):
    """Both halves of an item: what the model called it, and what it quoted.

    The quote carries most of the signal -- two arms that read the same sentence tend to
    quote it near-identically even when they name the duty differently.
    """
    text = " ".join([item.get("label") or item.get("requirement") or "",
                     (item.get("job_evidence") or {}).get("quote") or ""])
    return set(_WORD.findall(text.lower()))


def _similarity(x, y):
    a, b = _item_tokens(x), _item_tokens(y)
    return 2 * len(a & b) / (len(a) + len(b)) if a and b else 0.0


def _item_concepts(item):
    return sorted((item.get("concept_mapping") or {}).get("concept_ids") or [])


def _pair_status(a, b):
    if _item_concepts(a) != _item_concepts(b):
        return "concept_differs"
    if (a.get("importance") or a.get("requirement_type")) != (b.get("importance") or b.get("requirement_type")):
        return "kind_differs"
    return "same"


def align_items(items_a, items_b, threshold=0.4):
    """Pair A's items with B's so the sheet can show what one arm added and the other missed.

    Greedy best-first on token overlap, not positional: the arms order their output
    differently, so item 3 against item 3 would manufacture disagreements that are really
    just a different sequence. Anything under the threshold stays unpaired, which is the
    answer the labeller actually needs -- an item only one arm produced.
    """
    scored = sorted(
        ((_similarity(x, y), i, j)
         for i, x in enumerate(items_a) for j, y in enumerate(items_b)),
        key=lambda t: (-t[0], t[1], t[2]))
    match_a, match_b = {}, {}
    for score, i, j in scored:
        if score < threshold or i in match_a or j in match_b:
            continue
        match_a[i], match_b[j] = j, i

    rows = []
    for i, item in enumerate(items_a):
        if i in match_a:
            other = items_b[match_a[i]]
            rows.append({"a": item, "b": other, "status": _pair_status(item, other)})
        else:
            rows.append({"a": item, "b": None, "status": "only_a"})
    rows.extend({"a": None, "b": item, "status": "only_b"}
                for j, item in enumerate(items_b) if j not in match_b)
    return rows


def align_extractions(a, b):
    return {section: align_items(a.get(section) or [], b.get(section) or [])
            for section in SECTIONS}


def _disagrees(a, b):
    """Disagreement the arithmetic would read, not every cosmetic difference.

    Exact concept-set equality flags 180 of 248 rows -- so broad it is not a filter.
    These three are decision-relevant: what the posting is mostly about, whether the
    two readings overlap at all, and whether one arm gave up on the posting.
    """
    ca, cb = _concepts(a), _concepts(b)
    union = ca | cb
    jaccard = len(ca & cb) / len(union) if union else 1.0
    return (_dominant(a) != _dominant(b)
            or jaccard < 0.5
            or bool(a.get("insufficient_context")) != bool(b.get("insufficient_context")))


def build_queue(eval_dir, agree_sample=AGREE_SAMPLE, seed=SEED, thin_keep=THIN_KEEP):
    opus = _load_arm(eval_dir / "extract_opus.jsonl")
    codex = _load_arm(eval_dir / "extract_codex.jsonl")
    frame = {}
    for line in (eval_dir / "frame_extraction.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if "id" in row:
                frame[row["id"]] = row

    paired, dropped = [], []
    for pid in sorted(set(opus) & set(codex)):
        ex_o, ex_c = opus[pid]["extraction"], codex[pid]["extraction"]
        if "error" in ex_o or "error" in ex_c:
            dropped.append(pid)          # nothing to label; the failure IS the measurement
            continue
        paired.append(pid)

    thin = [pid for pid in paired
            if opus[pid]["extraction"].get("insufficient_context")
            and codex[pid]["extraction"].get("insufficient_context")]
    dropped_thin = thin[thin_keep:]                  # `paired` is sorted, so this is stable
    paired = [pid for pid in paired if pid not in set(dropped_thin)]

    disagree = [pid for pid in paired if _disagrees(opus[pid]["extraction"], codex[pid]["extraction"])]
    agree = [pid for pid in paired if pid not in set(disagree)]

    # Stratified so the sample cannot miss a whole class, and seeded so re-running the
    # builder mid-labelling does not reshuffle the queue under the answers.
    rng = random.Random(seed)
    by_stratum = {}
    for pid in agree:
        by_stratum.setdefault(frame.get(pid, {}).get("stratum", "unknown"), []).append(pid)
    sampled, share = [], agree_sample / len(agree) if agree else 0
    for stratum in sorted(by_stratum):
        pool = sorted(by_stratum[stratum])
        take = min(len(pool), max(2, round(len(pool) * share)))
        sampled.extend(rng.sample(pool, take))

    rows = []
    for pid in disagree + sampled:
        # Blind: which model is A flips per row, seeded off the id so it is stable.
        flip = random.Random(f"{seed}:{pid}").random() < 0.5
        arm_a, arm_b = ("codex", "opus") if flip else ("opus", "codex")
        src = {"opus": opus[pid], "codex": codex[pid]}
        entry = frame.get(pid, {})
        posting = entry.get("posting") or {}
        rows.append({
            "id": pid,
            "stratum": entry.get("stratum", "unknown"),
            "job_title": posting.get("job_title") or src["opus"].get("job_title", ""),
            "company_name": posting.get("company_name") or src["opus"].get("company_name", ""),
            "source": posting.get("source", ""),
            "location": posting.get("location", ""),
            "description": posting.get("description") or "",
            "current": entry.get("current") or {},
            "review_note": entry.get("review_note") or None,
            "arm_a": arm_a,
            "arm_b": arm_b,
            "a": src[arm_a]["extraction"],
            "b": src[arm_b]["extraction"],
            "aligned": align_extractions(src[arm_a]["extraction"], src[arm_b]["extraction"]),
        })
    rng.shuffle(rows)                    # disagreement rows must not cluster at the front

    concepts = {}
    for line in (eval_dir / "extract_opus.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("kind") == "run_header":
            concepts = {c["concept_id"]: c["description"] for c in row.get("concepts") or []}
            break

    return {
        "rows": rows,
        "concepts": concepts,
        "counts": {"paired": len(paired), "dropped_error": len(dropped),
                   "dropped_thin": len(dropped_thin),
                   "disagree": len(disagree), "agree_pool": len(agree),
                   "agree_sampled": len(sampled), "queue": len(rows)},
    }


# -------------------------------------------------------------------------- serving

class _Handler(BaseHTTPRequestHandler):
    queue = {}
    answers_path = None
    backup_path = None

    def log_message(self, fmt, *args):
        if "answers" in (self.path or ""):
            super().log_message(fmt, *args)

    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload, ensure_ascii=False), "application/json")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        if path == "/queue":
            return self._json(200, self.queue)
        if path == "/answers":
            try:
                return self._json(200, json.loads(self.answers_path.read_text(encoding="utf-8")))
            except FileNotFoundError:
                return self._json(200, {})
            except json.JSONDecodeError as exc:
                return self._json(500, {"error": f"answers file is not valid JSON: {exc}"})
        return self._json(404, {"error": "no such endpoint"})

    def do_POST(self):
        if self.path.split("?")[0] != "/answers":
            return self._json(404, {"error": "no such endpoint"})
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return self._json(400, {"error": f"bad JSON: {exc}"})
        if not isinstance(data, dict):
            return self._json(400, {"error": "expected an object keyed by row id"})
        if self.answers_path.exists():
            shutil.copy2(self.answers_path, self.backup_path)
        tmp = self.answers_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.answers_path)
        return self._json(200, {"ok": True, "rows": len(data)})


PAGE = r"""<!doctype html>
<meta charset="utf-8"><title>Extraction labelling</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#fff;--fg:#111;--dim:#666;--line:#dcdcdc;--card:#f7f7f7;--hi:#fff3c4;--ok:#0a7f3f;--warn:#b23;--acc:#2b6cb0;--acch:#e3eefc}
@media (prefers-color-scheme:dark){:root{--bg:#15171a;--fg:#e8e8e8;--dim:#9aa0a6;--line:#31353b;--card:#1d2024;--hi:#4a3d12;--ok:#5fd08a;--warn:#ff7b7b;--acc:#6fa8e6;--acch:#1c2b3d}}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--fg)}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:8px 14px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
#bar{flex:1;min-width:120px;height:6px;background:var(--card);border-radius:3px;overflow:hidden}
#bar>i{display:block;height:100%;background:var(--ok);width:0}
.chip{font-size:12px;color:var(--dim);border:1px solid var(--line);border-radius:10px;padding:1px 8px;white-space:nowrap}
main{display:grid;grid-template-columns:minmax(320px,1fr) minmax(420px,1.2fr);gap:14px;padding:14px;align-items:start}
@media (max-width:980px){main{grid-template-columns:1fr}}
section{border:1px solid var(--line);border-radius:8px;background:var(--card);padding:12px;min-width:0}
h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--dim);margin:0 0 8px}
h3{font-size:15px;margin:0 0 2px}
#jd{white-space:pre-wrap;max-height:calc(100vh - 250px);overflow:auto;font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;border-top:1px solid var(--line);padding-top:8px;margin-top:8px}
.arms{display:grid;grid-template-columns:1fr 1fr;gap:6px 10px;align-items:stretch}
.arms>.head{grid-column:1/-1;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--dim);border-top:1px solid var(--line);padding-top:8px;margin-top:4px}
.arms>.armname{font-weight:600}
.item{margin:0;padding:6px 8px;border-left:3px solid var(--line);border-radius:0 4px 4px 0;min-width:0;background:transparent}
.item.only{border-left-color:var(--warn);background:var(--hi)}
.item.concept{border-left-color:var(--acc);background:var(--acch)}
.item.gap{border-left-color:transparent;background:repeating-linear-gradient(135deg,transparent,transparent 5px,var(--line) 5px,var(--line) 6px);opacity:.55}
.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:11.5px;color:var(--dim);margin:2px 0 8px}
.legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px;vertical-align:baseline}
.lab{font-weight:600}
.cid{font-size:11px;color:var(--dim)}
.q{font:11.5px/1.45 ui-monospace,Menlo,monospace;color:var(--dim);display:block;margin-top:2px}
.q.bad{color:var(--warn)}
footer{position:sticky;bottom:0;background:var(--bg);border-top:1px solid var(--line);padding:10px 14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
button{font:inherit;padding:5px 11px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);cursor:pointer}
button.on{background:var(--fg);color:var(--bg);border-color:var(--fg)}
button:disabled{opacity:.4;cursor:default}
kbd{font:11px ui-monospace,Menlo,monospace;color:var(--dim);border:1px solid var(--line);border-radius:3px;padding:0 3px}
#note{flex:1;min-width:160px;font:inherit;padding:5px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
#save{font-size:12px;color:var(--dim);min-width:64px;text-align:right}
.muted{color:var(--dim)}
.none{color:var(--dim);font-style:italic}
</style>

<header>
  <b id="pos">loading</b>
  <div id="bar"><i></i></div>
  <span class="chip" id="left"></span>
  <span class="chip" id="stratum"></span>
  <span class="chip" id="cur"></span>
  <span id="save"></span>
</header>

<main>
  <section>
    <h2>Posting</h2>
    <h3 id="title"></h3>
    <div class="muted" id="company"></div>
    <div id="prior"></div>
    <div id="jd"></div>
  </section>
  <section>
    <h2>Extractions</h2>
    <div class="legend">
      <span><i style="background:var(--hi);border:1px solid var(--warn)"></i>only one arm found it</span>
      <span><i style="background:var(--acch);border:1px solid var(--acc)"></i>both found it, mapped to different concepts</span>
      <span><i style="background:var(--card);border:1px solid var(--line)"></i>both agree</span>
      <span>rows are paired across the two arms by quote overlap</span>
    </div>
    <div class="arms" id="arms"></div>
  </section>
</main>

<footer>
  <span class="muted">Worth applying?</span>
  <button data-rel="3">3 high <kbd>3</kbd></button>
  <button data-rel="2">2 worth it <kbd>2</kbd></button>
  <button data-rel="1">1 borderline <kbd>1</kbd></button>
  <button data-rel="0">0 no <kbd>0</kbd></button>
  <span class="muted" style="margin-left:10px">Read it right?</span>
  <button data-ext="a">A <kbd>a</kbd></button>
  <button data-ext="b">B <kbd>b</kbd></button>
  <button data-ext="both">both <kbd>s</kbd></button>
  <button data-ext="neither">neither <kbd>d</kbd></button>
  <input id="note" placeholder="note (optional) - press / to focus, Esc to leave">
  <button id="prev">back <kbd>k</kbd></button>
  <button id="next">next <kbd>j</kbd></button>
</footer>

<script>
const $ = s => document.querySelector(s);
let Q = null, A = {}, i = 0, timer = null;

const esc = s => (s == null ? "" : String(s)).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const cur = () => Q.rows[i];
// Reading must not create the record, or paging through the queue fills the answers
// file with empty objects and "rows touched" stops meaning anything.
const ans = () => A[cur().id] || {};
const answ = () => A[cur().id] || (A[cur().id] = {});

// Duties carry `label`/`importance`; qualifications carry `requirement`/
// `requirement_type` and no concept mapping at all.
function cell(it, cls){
  if (!it) return `<div class="item gap"></div>`;
  const cids = (it.concept_mapping||{}).concept_ids || [];
  const ev = it.job_evidence || {};
  return `<div class="item ${cls}">`
       +  `<span class="lab">${esc(it.label || it.requirement)}</span>`
       +  (it.importance || it.requirement_type ? ` <span class="cid">(${esc(it.importance || it.requirement_type)})</span>` : "")
       +  (cids.length ? `<div class="cid">${esc(cids.join(", "))}</div>`
                       : (it.label ? `<div class="cid">unmapped</div>` : ""))
       +  (ev.quote ? `<span class="q">"${esc(ev.quote)}"</span>` : "")
       +  `</div>`;
}

function armHeader(ex){
  let html = "";
  if (ex.error) return `<div class="item only"><span class="lab">extraction failed: ${esc(ex.error)}</span></div>`;
  if (ex.insufficient_context) html += `<div class="item only"><span class="lab">insufficient context</span></div>`;
  // Quote verification is aggregate, not per item -- the extractor counts, it does not
  // mark which quote failed. Surfacing the count is the honest version of that.
  const e = ex.evidence || {};
  if (e.job_quote_failures)
    html += `<div class="item only"><span class="lab">${e.job_quote_failures} job quote(s) not found in the posting</span>`
         +  (e.material_job_quote_failure ? ` <span class="cid">(material)</span>` : "") + `</div>`;
  html += `<div class="muted" style="padding:2px 8px">${esc(ex.summary || "")}</div>`;
  return html;
}

function renderArms(r){
  const heads = {duties:"Duties", required_qualifications:"Required", nice_to_haves:"Nice to have"};
  let html = `<div class="armname">A</div><div class="armname">B</div>`
           + `<div>${armHeader(r.a)}</div><div>${armHeader(r.b)}</div>`;
  for (const key of ["duties","required_qualifications","nice_to_haves"]){
    const rows = (r.aligned || {})[key] || [];
    if (!rows.length) continue;
    const only = rows.filter(x => x.status === "only_a" || x.status === "only_b").length;
    const differs = rows.filter(x => x.status === "concept_differs" || x.status === "kind_differs").length;
    const bits = [];
    if (only) bits.push(`${only} found by one arm only`);
    if (differs) bits.push(`${differs} mapped differently`);
    html += `<div class="head">${heads[key]} <span style="text-transform:none;letter-spacing:0">`
         +  (bits.length ? `- ${bits.join(", ")}` : `- both arms agree on all ${rows.length}`)
         +  `</span></div>`;
    // One grid row per PAIR, so a missing counterpart is a visible gap opposite the
    // item that has no match -- not an off-by-one shift down the whole column.
    for (const x of rows){
      const cls = x.status === "only_a" || x.status === "only_b" ? "only"
                : x.status === "concept_differs" ? "concept" : "";
      html += cell(x.a, cls) + cell(x.b, cls);
    }
  }
  return html;
}

function render(){
  const r = cur(), a = ans();
  $("#pos").textContent = `${i+1} / ${Q.rows.length}`;
  const done = Object.values(A).filter(x => x && x.relevance !== undefined).length;
  $("#bar>i").style.width = (100*done/Q.rows.length) + "%";
  $("#left").textContent = `${Q.rows.length - done} unlabelled`;
  $("#stratum").textContent = r.stratum;
  $("#cur").textContent = r.current && r.current.score !== undefined
    ? `today: ${r.current.score} ${r.current.domain||""}/${r.current.seniority||""}` : "today: unscored";
  $("#title").textContent = r.job_title || "(no title)";
  $("#company").textContent = [r.company_name, r.location, r.source, `id ${r.id}`].filter(Boolean).join("  -  ");
  $("#prior").innerHTML = r.review_note
    ? `<div class="item" style="margin-top:8px"><span class="cid">earlier note - context, not truth</span><br>${esc(r.review_note.note || JSON.stringify(r.review_note))}</div>` : "";
  $("#jd").textContent = r.description || "(no description stored)";
  $("#jd").scrollTop = 0;
  $("#arms").innerHTML = renderArms(r);
  for (const b of document.querySelectorAll("[data-rel]")) b.classList.toggle("on", String(a.relevance) === b.dataset.rel);
  for (const b of document.querySelectorAll("[data-ext]")) b.classList.toggle("on", a.extraction === b.dataset.ext);
  $("#note").value = a.note || "";
  $("#prev").disabled = i === 0;
  $("#next").disabled = i === Q.rows.length - 1;
}

function save(){
  $("#save").textContent = "saving...";
  clearTimeout(timer);
  timer = setTimeout(async () => {
    const res = await fetch("/answers", {method:"POST", body: JSON.stringify(A)}).catch(() => null);
    $("#save").textContent = res && res.ok ? "saved" : "SAVE FAILED";
  }, 250);
}

function go(step){ i = Math.min(Q.rows.length - 1, Math.max(0, i + step)); render(); }

function set(field, value){
  const a = answ();
  a[field] = value;
  render();
  save();
  // Advancing on a relevance answer is what makes 150 rows tolerable; it only fires
  // once both questions are answered, so it never skips past a half-filled row.
  if (a.relevance !== undefined && a.extraction) setTimeout(() => go(1), 90);
}

document.addEventListener("click", e => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.rel !== undefined) set("relevance", Number(b.dataset.rel));
  else if (b.dataset.ext) set("extraction", b.dataset.ext);
  else if (b.id === "next") go(1);
  else if (b.id === "prev") go(-1);
});

$("#note").addEventListener("input", () => { answ().note = $("#note").value; save(); });
$("#note").addEventListener("keydown", e => { if (e.key === "Escape") $("#note").blur(); e.stopPropagation(); });

document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "/") { e.preventDefault(); $("#note").focus(); return; }
  if ("0123".includes(e.key)) return set("relevance", Number(e.key));
  if (e.key === "a" || e.key === "b") return set("extraction", e.key);
  if (e.key === "s") return set("extraction", "both");
  if (e.key === "d") return set("extraction", "neither");
  if (e.key === "j" || e.key === "ArrowRight") return go(1);
  if (e.key === "k" || e.key === "ArrowLeft") return go(-1);
});

(async () => {
  Q = await (await fetch("/queue")).json();
  A = await (await fetch("/answers")).json();
  // Resume where the work stopped, not where the queue starts.
  const first = Q.rows.findIndex(r => !(A[r.id] && A[r.id].relevance !== undefined));
  i = first === -1 ? 0 : first;
  render();
})();
</script>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    here_eval = Path(__file__).resolve().parent.parent / "eval"
    ap.add_argument("--eval-dir", type=Path, default=here_eval,
                    help="where the arms, frame and answers live (default: %(default)s)")
    ap.add_argument("--answers", type=Path, default=None,
                    help="answers file (default: <eval-dir>/extract_labels.json)")
    ap.add_argument("--agree-sample", type=int, default=AGREE_SAMPLE,
                    help="rows drawn from the agreeing pool (default: %(default)s)")
    ap.add_argument("--thin-keep", type=int, default=THIN_KEEP,
                    help="cap on rows where BOTH arms say insufficient_context "
                         "(default: %(default)s)")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--dump-queue", action="store_true",
                    help="write the queue to <eval-dir>/extract_label_queue.json and exit")
    args = ap.parse_args()

    queue = build_queue(args.eval_dir, args.agree_sample, args.seed, args.thin_keep)
    counts = queue["counts"]
    print(f"paired {counts['paired']} rows ({counts['dropped_error']} dropped for an extraction "
          f"error, {counts['dropped_thin']} for having no description to extract from)")
    print(f"  {counts['disagree']} disagree + {counts['agree_sampled']} sampled "
          f"from {counts['agree_pool']} agreeing = {counts['queue']} to label")

    if args.dump_queue:
        out = args.eval_dir / "extract_label_queue.json"
        out.write_text(json.dumps(queue, ensure_ascii=False, indent=1), encoding="utf-8")
        return print(f"wrote {out}")

    answers = args.answers or (args.eval_dir / "extract_labels.json")
    _Handler.queue = queue
    _Handler.answers_path = answers
    _Handler.backup_path = answers.with_suffix(".json.bak")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    print(f"\nlabel sheet: http://127.0.0.1:{args.port}/")
    print(f"answers:     {answers}")
    print("keys: 0-3 relevance | a b s d extraction | j k move | / note")
    print("bound to 127.0.0.1 only; ctrl-c to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
