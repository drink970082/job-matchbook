"""HTTP client for the web app's key-scoped write API (/api/v1, SPEC §7.2).

The MCP server never opens a writable database handle: every write goes through web,
so the validation in the apps/web/src/lib/*-actions.ts Server Actions exists once.
"""

from __future__ import annotations

import os
from typing import Any

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:3000"


class WriteAPIError(Exception):
    """A write the operator or the model can act on; the message is safe to show."""


class ATSWriteClient:
    def __init__(self, base_url: str, key: str, session: Any = None, timeout: float = 10.0):
        self._base = base_url.rstrip("/")
        self._key = key
        self._session = session or requests.Session()
        self._timeout = timeout

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        try:
            resp = self._session.request(
                method, self._base + path, json=body, timeout=self._timeout,
                headers={"Authorization": f"Bearer {self._key}"},
            )
        except requests.RequestException:
            raise WriteAPIError(f"ATS web is unreachable at {self._base}; is the ats-web container running?") from None
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if resp.status_code == 200:
            return payload.get("data")
        if resp.status_code == 503:
            raise WriteAPIError("ATS write API is disabled: no key is configured on the web side")
        if resp.status_code in (401, 403):
            raise WriteAPIError("ATS write API rejected this server's key (needs a read_write key)")
        # Web returns the action's own text; a driver failure can be long, so bound it.
        raise WriteAPIError(str(payload.get("error") or f"ATS write failed (HTTP {resp.status_code})")[:300])


def write_client_from_env(env: dict[str, str] | None = None) -> ATSWriteClient | None:
    """ATS_API_KEY enables writes; without it the server stays read-only."""
    env = os.environ if env is None else env
    key = env.get("ATS_API_KEY", "").strip()
    if not key:
        return None
    return ATSWriteClient(env.get("ATS_API_URL", "").strip() or DEFAULT_BASE_URL, key)
