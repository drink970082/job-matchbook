"""Codex fit-scoring backend — the injected `fit_fn` `pipeline.run_score` calls
after a posting clears the SCREEN. See `ats_worker.score` for the SCREEN/SCORE
composition this backend plugs into.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile

from .errors import ScoreError
from .prompts import _job_block, _scorer_system_sections, _score_schema
from .usage import _rollout_mtime_ceiling, _capture_usage


# --- real adapter (exercised only in Docker; never imported at module load) ---

def _batch_schema(labels: list) -> dict:
    """The schema actually handed to `codex exec --output-schema` — the bare
    _score_schema never is. Module level so the strict-mode guard can check the real
    payload; it captures nothing from make_codex_scorer.

    Deep-copy _score_schema's output so its module-level cache (_SCORE_SCHEMA) is never
    mutated, then wrap N per-posting elements in a {"results":[...]} envelope tagged
    with the job_ref that makes realignment possible.
    """
    element = json.loads(json.dumps(_score_schema(labels)))
    element["properties"]["job_ref"] = {"type": "integer"}
    element["required"].append("job_ref")
    return {
        "type": "object",
        "properties": {"results": {"type": "array", "items": element}},
        "required": ["results"],
        "additionalProperties": False,
    }


def make_codex_scorer(model: str, *, profile: str = "", reasoning_effort: str = "low",
                      verbosity: str = "low", timeout: int = 600, codex_bin: str = "codex",
                      usage_path: str | None = None):
    """Build a `fit(postings, resumes) -> list[dict]` callable backed by the Codex CLI.

    The ChatGPT-subscription twin of make_claude_scorer: flat-rate instead of metered.
    Same prompt sections and same per-element JSON schema (`_score_schema`, fed to
    `--output-schema`, which enforces it the way Claude's structured outputs do), so
    scores stay comparable across backends and the verdict-accuracy harness
    (tools/score_eval.py) can judge one against the other.

    BATCH-FIRST, ONE `codex exec` PER CALL: the ChatGPT-subscription quota is
    MESSAGE-bound, not token-bound, so batching all N postings into a single exec
    (rather than one exec per posting) is the actual quota win — see B1 in
    docs/superpowers/sdd. Each JD gets its own `=== JOB job_ref=<id> ===` block
    (`posting["id"]`), and the schema demands the same `job_ref` tag come back on
    every element (`{"results":[{"job_ref":...,...}, ...]}`). Results are realigned
    to INPUT ORDER by that tag rather than trusted positionally, because an LLM is
    not guaranteed to preserve list order across N items. A missing, duplicate, or
    unknown `job_ref` raises ScoreError for the WHOLE BATCH — silently misattributing
    a score to the wrong job is worse than failing loudly (a later task retries as
    singles on this failure; not this one's concern).

    NO DETERMINISM: codex exec exposes no seed/temperature (its only model knobs are
    model_reasoning_effort and model_verbosity), so the score noise cannot be turned off
    here — tools/score_eval.py is what says whether the verdicts actually
    agree / stay stable.

    WHY effort=low + verbosity=low, and why BOTH are pinned rather than left default
    (measured 2026-07-16, not guessed):
      · effort buys nothing on this task shape — reasoning tokens were non-monotonic
        across levels (low 44, medium 71, high 61, xhigh 54, max 67): the model won't
        spend reasoning on a judgment it finds easy, so `high` cost latency for no gain.
      · effort MUST still be pinned: the default is server-controlled (models_cache.json
        is fetched with an etag) and was observed flipping low->medium->low within
        minutes. An unpinned default can change behavior mid-batch with no CLI upgrade.
      · verbosity is a NO-OP under --output-schema (the schema fully constrains the final
        message; verbosity=high emitted byte-identical JSON). Pinned only so a future
        reader doesn't "discover" it as a tuning knob.

    TOOL-LESS BY CONSTRUCTION (`--disable shell_tool` + `web_search="disabled"`), which
    is a SECURITY boundary, not a tuning choice: a JD is untrusted text scraped off the
    internet, and plain `codex exec` is an agent holding a shell — `--sandbox read-only`
    blocks writes but permits reads ANYWHERE, so a malicious posting could otherwise ask
    the model to read ~/.codex/auth.json or .env and echo it into `summary`, which we
    persist and push to Telegram. Dropping the tools removes the capability instead of
    trusting the model to decline (it did decline when probed — but that's compliance,
    not a guarantee). Measured bonus: it also cut ~3.1k input tokens/call (12,755 ->
    9,659 on an identical prompt), which is real relief on the message budget that
    actually bounds a 640-row batch (weekly-metered — see make_codex_scorer's usage
    capture and docs/SPEC.md §11). NOTE: the official docs claim there's no way to
    disable exec; they're wrong as of 0.144.4 (verified behaviorally). `web_search`
    defaults to ON ("cached") — off here: scoring is a closed-book judgment over the JD
    and résumé, and a live lookup would add latency and one more source of variance.

    One ephemeral agent turn per call: --ephemeral keeps a 640-row pass from littering
    session files, and -C <tmpdir> + --skip-git-repo-check keep the JD the only input
    (no repo context leaks into a score). Auth is the operator's `codex login` state,
    NOT an env key — but beware CODEX_API_KEY, which OVERRIDES ChatGPT auth and would
    silently move this onto metered API billing (OPENAI_API_KEY is ignored, so it's
    harmless).

    A non-zero exit ALWAYS raises ScoreError rather than yielding a zero, so a broken
    24h cron fails one posting loudly instead of silently scoring the whole queue 0.
    (Motivating incident: ~/.codex/auth.json was observed vanishing right after a failed
    auth run on 2026-07-16, forcing a re-login. Codex is NOT documented to purge it and
    the mechanism was never confirmed — but "score 0 on a dead backend" is unacceptable
    regardless of what removed the file.)
    """
    def fit(postings: list[dict], resumes: dict) -> list[dict]:
        # Same job block as Claude: no truncation, no Location line (D5). Each block
        # is tagged with job_ref=<posting id> so the model's answer can be realigned.
        blocks = [f"=== JOB job_ref={posting['id']} ===\n"
                  + _job_block(posting, 0, include_location=False)
                  for posting in postings]
        prompt = "\n\n".join([*_scorer_system_sections(resumes, profile), *blocks])
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = os.path.join(tmp, "schema.json")
            out_path = os.path.join(tmp, "out.json")
            with open(schema_path, "w", encoding="utf-8") as fh:
                json.dump(_batch_schema(list(resumes)), fh)
            cmd = [codex_bin, "exec", "--model", model,
                   # Strip BOTH tools: scoring is pure judgment, and a JD is untrusted
                   # scraped text. See the docstring — this is a security boundary, not
                   # a tuning knob.
                   "--disable", "shell_tool",
                   "-c", 'web_search="disabled"',
                   "-c", f"model_reasoning_effort={reasoning_effort}",
                   "-c", f"model_verbosity={verbosity}",
                   "--output-schema", schema_path, "--output-last-message", out_path,
                   # --ephemeral suppresses the session rollout — but the rollout is
                   # the ONLY place codex records rate_limits (used for the quota bar;
                   # --json stdout does NOT carry it). So when capturing usage we drop
                   # --ephemeral, read the rollout, then delete it (see _capture_usage).
                   # The eval/test path (no usage_path) keeps --ephemeral, so its call
                   # and verdicts are byte-for-byte unchanged.
                   "--sandbox", "read-only", "--skip-git-repo-check",
                   *([] if usage_path else ["--ephemeral"]),
                   "--color", "never", "-C", tmp, "-"]
            # Mark the newest existing rollout so _capture_usage can find the one
            # THIS call writes (only when capturing — the walk is not free).
            usage_since = _rollout_mtime_ceiling() if usage_path else 0.0
            try:
                try:
                    proc = subprocess.run(cmd, input=prompt, capture_output=True,
                                          text=True, timeout=timeout)
                except subprocess.TimeoutExpired as exc:
                    raise ScoreError(f"codex exec timed out after {timeout}s") from exc
                except FileNotFoundError as exc:
                    raise ScoreError(f"codex binary not found: {codex_bin!r}") from exc
                if proc.returncode != 0:
                    tail = (proc.stdout or proc.stderr or "").strip()[-400:]
                    raise ScoreError(f"codex exec failed (exit {proc.returncode}): {tail}")
                try:
                    with open(out_path, encoding="utf-8") as fh:
                        data = json.load(fh)
                except (OSError, json.JSONDecodeError) as exc:
                    raise ScoreError(f"codex returned non-JSON score: {exc}") from exc
            finally:
                # Runs on success AND failure: since capturing drops --ephemeral, the
                # rollout (full résumé+profile+JD prompt) must be reaped even when the
                # exec raises — otherwise a failed call leaves that prompt on disk.
                if usage_path:
                    _capture_usage(usage_path, usage_since)
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ScoreError(f"codex batch response missing 'results' array: {data!r}")

        # Alignment guard: realign by job_ref rather than trusting list position, and
        # fail the WHOLE batch loudly on any missing/duplicate/unknown ref rather than
        # risk silently pairing a score with the wrong job.
        ids = [posting["id"] for posting in postings]
        id_set = set(ids)
        by_ref: dict = {}
        for result in data["results"]:
            if not isinstance(result, dict):
                raise ScoreError(f"codex batch result was not a JSON object: {result!r}")
            ref = result.get("job_ref")
            if ref not in id_set:
                raise ScoreError(f"codex returned unknown job_ref {ref!r}")
            if ref in by_ref:
                raise ScoreError(f"codex returned duplicate job_ref {ref!r}")
            by_ref[ref] = result
        missing = [i for i in ids if i not in by_ref]
        if missing:
            raise ScoreError(f"codex omitted job_ref {missing[0]}")
        return [by_ref[i] for i in ids]

    return fit
