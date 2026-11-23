"""Per-host request pacing with bounded 429 retry (#273).

Workday throttles per tenant host and answers 429 well before a pass is done: the
fetch stage spends the budget, then expire's re-checks get 429 for nearly every row.
So every Workday request goes through one `HostPacer`, which

- spaces requests to the same host by MIN_INTERVAL (other hosts are not held back),
- on 429 waits Retry-After (delta-seconds) when given, else BACKOFF * 2**attempt
  (capped at MAX_DELAY), and retries up to RETRIES times (delivery uncertainty:
  RETRY, PRINCIPLES),
- after the last 429 returns that response, so the caller's raise_for_status reports
  http_429 and the row stays alive and inconclusive (KEEP), and answers every request
  to that host with the same 429, without sending it, for COOLDOWN seconds. A
  Retry-After above MAX_DELAY is not clamped and retried: the host gives up at once
  and cools for that long (at least COOLDOWN, at most MAX_COOLDOWN). So the time one
  throttled tenant costs a pass is bounded per host.

Thread-safe: the feed calls fetch_one from a thread pool. A slot is reserved under
the lock and slept for outside it; the cooldown is re-checked after the sleep.
"""
from __future__ import annotations

import math
import threading
import time
from urllib.parse import urlparse

# Workday publishes no rate limit. 0.5s caps one tenant at 2 req/s, about what a
# serial fetch issues anyway at typical latency; it only spaces bursts.
MIN_INTERVAL = 0.5
BACKOFF = 2.0      # first wait when a 429 carries no Retry-After; doubles per retry
RETRIES = 3        # retries after the first 429; worst case 2+4+8s per request
MAX_DELAY = 30.0   # ceiling on any single wait, Retry-After included
COOLDOWN = 120.0   # a host that exhausted its retries is answered 429 locally this long
MAX_COOLDOWN = 900.0  # ceiling on a cooldown taken from a long Retry-After


def _retry_after(resp) -> float | None:
    try:
        value = float(resp.headers.get("Retry-After"))
    except (AttributeError, TypeError, ValueError):
        return None   # absent, or an HTTP-date: fall back to exponential backoff
    return value if math.isfinite(value) else None   # nan/inf: same fallback


class HostPacer:
    def __init__(self, clock=time.monotonic, sleep=time.sleep):
        self._clock, self._sleep = clock, sleep
        self._lock = threading.Lock()
        self._next: dict[str, float] = {}        # host -> earliest next send
        self._cooling: dict[str, tuple[float, object]] = {}  # host -> (until, 429 resp)

    def _slot(self, host: str, delay: float = 0.0):
        """Reserve the host's next send slot and wait for it; None to send, or the
        cached 429 while the host is cooling down."""
        with self._lock:
            now = self._clock()
            cooling = self._cooling.get(host)
            if cooling and cooling[0] > now:
                return cooling[1]
            last = self._next.get(host)
            at = max(now + delay, now if last is None else last + MIN_INTERVAL)
            self._next[host] = at
        if at > now:
            self._sleep(at - now)
            with self._lock:   # another thread may have cooled the host meanwhile
                cooling = self._cooling.get(host)
                if cooling and cooling[0] > self._clock():
                    return cooling[1]
        return None

    def request(self, http, method: str, url: str, **kwargs):
        host = urlparse(url).hostname or ""
        delay, cool = 0.0, COOLDOWN
        for attempt in range(RETRIES + 1):
            cached = self._slot(host, delay)
            if cached is not None:
                return cached
            resp = getattr(http, method)(url, **kwargs)
            if getattr(resp, "status_code", None) != 429:
                return resp
            wait = _retry_after(resp)
            if wait is not None and wait > MAX_DELAY:
                cool = max(COOLDOWN, min(wait, MAX_COOLDOWN))
                break   # the server asked for longer than a pass should wait
            delay = min(BACKOFF * 2 ** attempt if wait is None else max(wait, 0.0),
                        MAX_DELAY)
        with self._lock:
            self._cooling[host] = (self._clock() + cool, resp)
        return resp
