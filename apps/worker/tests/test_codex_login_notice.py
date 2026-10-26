"""Authentication telemetry must distinguish login rejection from provider outages."""
import json
import urllib.error
from ats_worker.score import usage


def test_missing_login_publishes_notice(tmp_path, monkeypatch):
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'missing'))
    destination = tmp_path / 'usage.json'
    assert usage.capture_usage(str(destination), 'codex')
    assert json.loads(destination.read_text())['auth_required'] is True


def test_rejected_login_preserves_quota_and_recovers(tmp_path, monkeypatch):
    home = tmp_path / 'codex'
    home.mkdir()
    (home / 'auth.json').write_text(json.dumps({'tokens': {'access_token': 'fake', 'account_id': 'fake'}}))
    monkeypatch.setenv('CODEX_HOME', str(home))
    destination = tmp_path / 'usage.json'
    previous = {'backend': 'codex', 'limits': [{'used_percent': 42}], 'plan_type': 'plus'}
    destination.write_text(json.dumps(previous))
    def reject(*args, **kwargs):
        raise urllib.error.HTTPError(usage.CODEX_USAGE_URL, 401, 'Unauthorized', {}, None)
    monkeypatch.setattr(usage.urllib.request, 'urlopen', reject)
    assert usage.capture_usage(str(destination), 'codex')
    snapshot = json.loads(destination.read_text())
    assert snapshot['auth_required'] is True
    assert snapshot['limits'] == previous['limits']
    monkeypatch.setattr(usage, '_get_json', lambda *args: {
        'rate_limit': {'primary_window': {'used_percent': 43}}})
    assert usage.capture_usage(str(destination), 'codex')
    assert not json.loads(destination.read_text()).get('auth_required')


def test_forbidden_does_not_claim_login_expired(tmp_path, monkeypatch):
    destination = tmp_path / 'usage.json'
    previous = {'backend': 'codex', 'limits': []}
    destination.write_text(json.dumps(previous))
    def forbidden(*args, **kwargs):
        raise urllib.error.HTTPError(usage.CODEX_USAGE_URL, 403, 'Forbidden', {}, None)
    monkeypatch.setattr(usage.urllib.request, 'urlopen', forbidden)
    monkeypatch.setattr(usage, '_ATTEMPTS', 1)
    monkeypatch.setattr(usage, '_codex_auth', lambda: ('fake', 'fake'))
    assert not usage.capture_usage(str(destination), 'codex')
    assert json.loads(destination.read_text()) == previous
