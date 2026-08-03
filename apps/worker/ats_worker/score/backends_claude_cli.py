"""Claude Code CLI fit-scoring backend — the subscription twin of
`make_codex_scorer`, and the backend `SCORE_BACKEND=claude` selects.

Distinct from `backends_claude.make_claude_scorer`, which drives the Anthropic SDK with
`ANTHROPIC_API_KEY` and bills metered dollars (that one is `SCORE_BACKEND=claude-api`).
Before this module existed, `score.usage` read the **Claude Code subscription** for
backend name "claude" while the only Claude scorer spent the metered key — the quota bar
described a budget nothing touched. See `usage.py`'s module docstring.
"""
from __future__ import annotations

import json
import subprocess
import tempfile

from ._batch import align_results, batch_schema
from .errors import ScoreError
from .prompts import _job_block, _scorer_system_sections


# --- real adapter (never exercised at module load; tests mock subprocess) ---

def _result_event(payload) -> dict:
    """Pull the terminal `type == "result"` event out of `--output-format json`.

    The CLI emits a JSON **array** of session events (init, assistant turns, tool
    results, a rate_limit_event, then the result), NOT a single object — measured
    against Claude Code 2.1.220 on 2026-08-02. Taking `payload[-1]` would work today and
    break the first time a trailing event is added, so match on the type.
    """
    if not isinstance(payload, list):
        raise ScoreError(f"claude returned {type(payload).__name__}, expected an event array")
    for event in reversed(payload):
        if isinstance(event, dict) and event.get("type") == "result":
            return event
    raise ScoreError("claude emitted no result event")


def make_claude_cli_scorer(model: str, *, profile: str = "", timeout: int = 600,
                           claude_bin: str = "claude"):
    """Build a `fit(postings, resumes) -> list[dict]` callable backed by the Claude Code CLI.

    Same prompt sections and the same `{"results":[{"job_ref":...}]}` schema as
    `make_codex_scorer` (both call `_batch.batch_schema`), so the two backends stay
    comparable and a disagreement between them means the MODELS disagree rather than the
    adapters parsing differently. Batch size is 1 in practice — batching is closed on
    correctness grounds, see `DEFAULT_BATCH_SIZE` in run.py.

    STRUCTURED OUTPUT IS ENFORCED, NOT PROMPTED. `--json-schema` is Claude Code's
    equivalent of `codex exec --output-schema`: the CLI exposes a `StructuredOutput` tool
    constrained to the schema, and the terminal result event carries the validated object
    on `structured_output` (already parsed) as well as a JSON string on `result`. We read
    `structured_output` and fall back to parsing `result`. There is deliberately no
    prompt-and-parse path: a half-parsed verdict is worse than a failed one.

    TOOL-LESS BY CONSTRUCTION — and the flag that does it is `--tools ""`, NOT
    `--allowedTools ""`. This was measured, not assumed (2026-08-02): with
    `--allowedTools ""` the session still came up holding Bash, Read, Write, WebFetch,
    Task and two MCP servers in `permissionMode: "auto"`, because `--allowedTools` is a
    permission allowlist over a tool set that is still loaded. `--tools ""` removes the
    built-in set outright, leaving only `StructuredOutput`. That distinction is a
    SECURITY boundary, not a tuning knob: a JD is untrusted text scraped off the
    internet, and a scoring agent holding Bash/Read could be asked by a malicious posting
    to read `~/.claude/.credentials.json` or `.env` and echo it into `summary`, which we
    persist and push to Telegram. The same reasoning as `make_codex_scorer`'s
    `--disable shell_tool`; only the flag differs.

    ISOLATION, and it is also the cost lever. `--strict-mcp-config` (no MCP servers),
    `--setting-sources ""` (no user/project/local settings, so no CLAUDE.md, plugins or
    hooks), `--disable-slash-commands` (no skills) and a `TemporaryDirectory` cwd keep
    the JD and résumé the only inputs — no repo context leaks into a score. Measured
    side effect on an identical trivial prompt: harness overhead fell from **38,643 to
    9,193** cached input tokens/call and the CLI's own cost estimate from $0.233 to
    $0.057. The remaining ~9.2k is Claude Code's base system prompt; each `claude -p` is
    a fresh session, so that prefix is re-written every call and never read back.

    NEVER PASS `--bare`. It looks like the right minimal-mode flag and is a billing trap:
    "Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper via --settings (OAuth
    and keychain are never read)" — it would silently move this backend off the
    subscription and onto metered API billing, the exact shape of the `CODEX_API_KEY`
    trap documented in `make_codex_scorer`.

    `--no-session-persistence` keeps a 287-row labeling pass from littering session
    files, mirroring codex's `--ephemeral`. Auth is the operator's `claude` login state.

    A non-zero exit, an `is_error` result, or an unparseable payload ALWAYS raises
    ScoreError rather than yielding a zero — a broken backend must fail one posting
    loudly, not silently score the whole queue 0.
    """
    def fit(postings: list[dict], resumes: dict) -> list[dict]:
        # Same job block as codex/Claude-SDK: no truncation, no Location line (D5 —
        # geography must not move a fit score), tagged with job_ref for realignment.
        blocks = [f"=== JOB job_ref={posting['id']} ===\n"
                  + _job_block(posting, 0, include_location=False)
                  for posting in postings]
        prompt = "\n\n".join([*_scorer_system_sections(resumes, profile), *blocks])
        data = claude_json(prompt, batch_schema(list(resumes)), model=model,
                           timeout=timeout, claude_bin=claude_bin)
        return align_results(data, postings, backend="claude")

    return fit


def claude_json(prompt: str, schema: dict, *, model: str, timeout: int = 600,
                claude_bin: str = "claude"):
    """One tool-less `claude -p` under a JSON schema -> the parsed object.

    Split out of `fit` on 2026-08-03 so the shadow EXTRACTION call
    (`score/extract.py`) reaches this invocation instead of copying it. The flags are a
    security and isolation boundary, not tuning — `--tools ""` (NOT `--allowedTools ""`)
    removes capability from an agent about to read untrusted scraped text, and the
    isolation flags are also the measured cost lever. All of it is argued in
    `make_claude_cli_scorer`'s docstring.
    """
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [claude_bin, "-p", "--model", model, "--output-format", "json",
               # Capability removal, not permission denial. See the docstring —
               # `--allowedTools ""` was measured to leave the tools loaded.
               "--tools", "",
               "--strict-mcp-config", "--setting-sources", "",
               "--disable-slash-commands", "--no-session-persistence",
               "--json-schema", json.dumps(schema)]
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True,
                                  text=True, timeout=timeout, cwd=tmp)
        except subprocess.TimeoutExpired as exc:
            raise ScoreError(f"claude -p timed out after {timeout}s") from exc
        except FileNotFoundError as exc:
            raise ScoreError(f"claude binary not found: {claude_bin!r}") from exc
    if proc.returncode != 0:
        tail = (proc.stdout or proc.stderr or "").strip()[-400:]
        raise ScoreError(f"claude -p failed (exit {proc.returncode}): {tail}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ScoreError(f"claude returned non-JSON output: {exc}") from exc

    result = _result_event(payload)
    # `is_error` is the CLI's own success flag and is independent of the exit code:
    # an API error mid-session can still exit 0. Check both.
    if result.get("is_error") or result.get("subtype") != "success":
        detail = result.get("api_error_status") or result.get("subtype")
        raise ScoreError(f"claude -p returned an error result: {detail!r}")

    data = result.get("structured_output")
    if data is None:  # schema satisfied but delivered only as text
        try:
            data = json.loads(result.get("result") or "")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ScoreError(f"claude result carried no parseable score: {exc}") from exc
    return data
