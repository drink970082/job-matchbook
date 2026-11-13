import json
from pathlib import Path
import subprocess
import sys
import pytest
from ats_worker.roster_collection import collect, sha


def scope(*sources):
    return {"version": "jev-roster-scope-v1", "boards": [{"source": s, "slug": "demo", "name": "Example"} for s in sources],
            "filters": {"title_filter": ["engineer"], "title_exclude": ["senior"], "max_age_days": 30},
            "candidate": {"locations": ["United States"], "exclude_internships": True}, "feed_scope": "excluded"}


def job(id="1", title="Engineer", content="Build systems", location="New York, United States"):
    return {"id": id, "title": title, "content": content, "location": {"name": location}, "first_published": "2026-11-01"}


def run(spec, fetch):
    return collect(spec, fetch_json=fetch, now="2026-11-13T12:00:00Z", window_start="2026-11-13T00:00:00Z", window_end="2026-11-14T00:00:00Z")


def test_complete_response_is_not_daily_coverage_and_reconciles_exclusions():
    raw = {"jobs": [job(), job(), job("2", "Analyst"), job("3", "Senior Engineer"), job("4", "Engineer Intern"), job("5", location="London, United Kingdom"), job("6", content="")]}
    result = run(scope("greenhouse"), lambda board: raw)
    assert result["scope_capture_complete"] is True and result["daily_window_complete"] is False
    assert result["counts"] == {"expected_boards": 1, "captured_boards": 1, "raw": 7, "parsed": 7, "retained": 1, "excluded": 6}
    assert result["raw_payloads"]["greenhouse/demo"] == raw
    reasons = [r["exclusion_reasons"] for r in result["rows"]]
    assert "duplicate_identity" in reasons[1] and result["rows"][1]["duplicate_of"] == 0
    for i, reason in enumerate(("title_not_in_keep_list", "title_excluded", "deterministic_internships", "deterministic_location", "missing_description"), 2):
        assert reason in reasons[i]
    assert result["rows"][0]["source_sha256"] == sha(result["rows"][0]["posting"])


def test_failure_and_unsupported_never_claim_complete():
    def fetch(board):
        if board["source"] == "greenhouse":
            raise RuntimeError("SECRET")
        return {"jobs": []}
    result = run(scope("greenhouse", "ashby", "custom"), fetch)
    assert [b["status"] for b in result["boards"]] == ["failed", "captured", "unsupported"]
    assert result["scope_capture_complete"] is False and "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("payload", [{}, {"jobs": None}, {"jobs": [{}]}])
def test_malformed_payload_preserved(payload):
    result = run(scope("greenhouse"), lambda board: payload)
    assert result["boards"][0]["status"] == "failed"
    assert result["raw_payloads"]["greenhouse/demo"] == payload


def test_other_native_sources_and_age():
    def fetch(board):
        if board["source"] == "lever":
            return [{"id": "l", "text": "Engineer", "descriptionPlain": "Build", "createdAt": 1}]
        return {"jobs": [{"id": "a", "title": "Engineer", "descriptionPlain": "Build", "publishedAt": "2020-01-01"}]}
    result = run(scope("lever", "ashby"), fetch)
    assert result["scope_capture_complete"] is True
    assert all("posting_too_old" in row["exclusion_reasons"] for row in result["rows"])


def test_invalid_scope_window_prevents_fetch():
    spec = scope("greenhouse"); spec["boards"][0]["slug"] = "../secret"
    with pytest.raises(ValueError):
        run(spec, lambda board: pytest.fail("must not fetch"))
    with pytest.raises(ValueError):
        collect(scope("greenhouse"), fetch_json=lambda board: pytest.fail("must not fetch"), now="2026-11-15T00:00:00Z", window_start="2026-11-13T00:00:00Z", window_end="2026-11-14T00:00:00Z")


def test_fixture_cli_no_network_and_no_clobber(tmp_path):
    spec, fixture, output = (tmp_path / n for n in ("scope.json", "fixture.json", "out.json"))
    spec.write_text(json.dumps(scope("greenhouse")))
    fixture.write_text(json.dumps({"greenhouse/demo": {"jobs": [job()]}}))
    cmd = [sys.executable, str(Path(__file__).parents[1] / "tools/jev_collect_roster.py"), "--scope", str(spec), "--fixture", str(fixture), "--output", str(output), "--now", "2026-11-13T12:00:00Z", "--window-start", "2026-11-13T00:00:00Z", "--window-end", "2026-11-14T00:00:00Z"]
    first = subprocess.run(cmd, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert json.loads(output.read_text())["model_calls"] == 0
    assert json.loads(first.stdout)["daily_window_complete"] is False
    assert subprocess.run(cmd, capture_output=True).returncode != 0


def test_existing_output_blocks_even_live_initialization(tmp_path):
    spec = tmp_path / "scope.json"; output = tmp_path / "sealed.json"
    spec.write_text(json.dumps(scope("greenhouse"))); output.write_text("sealed")
    cmd = [sys.executable, str(Path(__file__).parents[1] / "tools/jev_collect_roster.py"), "--scope", str(spec), "--live", "--output", str(output), "--window-start", "2026-11-13T00:00:00Z", "--window-end", "2026-11-14T00:00:00Z"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode != 0 and "FileExistsError" in result.stderr
    assert output.read_text() == "sealed"
