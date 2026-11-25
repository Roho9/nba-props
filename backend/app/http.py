"""Rate-limited HTTP client with retries and a persistent fetch log."""
from __future__ import annotations

import logging
import re
import threading
import time

import httpx

from .db import FetchLog, session

log = logging.getLogger("http")
UA = "nba-props-research/1.0 (personal, non-commercial research; low request rate)"


class RateLimitedClient:
    def __init__(self, source: str, min_interval_s: float, timeout: float = 25.0):
        self.source = source
        self.min_interval_s = min_interval_s
        self._lock = threading.Lock()
        self._last = 0.0
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": UA, "Accept": "application/json"},
                                    follow_redirects=True)

    def _wait(self):
        with self._lock:
            gap = time.monotonic() - self._last
            if gap < self.min_interval_s:
                time.sleep(self.min_interval_s - gap)
            self._last = time.monotonic()

    def get_json(self, url: str, params: dict | None = None, retries: int = 3, log_fetch: bool = True, tag: str | None = None):
        """Returns (status, json_or_None). 404 is returned, not raised: it means 'not available'."""
        last_err = None
        for attempt in range(retries + 1):
            self._wait()
            t0 = time.monotonic()
            try:
                r = self._client.get(url, params=params)
                ms = int((time.monotonic() - t0) * 1000)
                if r.status_code == 429 or r.status_code >= 500:
                    last_err = f"HTTP {r.status_code}"
                    self._record(str(r.url), r.status_code, False, ms, last_err, log_fetch)
                    time.sleep(min(30, 2 ** attempt * 1.5))
                    continue
                ok = r.status_code == 200
                self._record(str(r.url), r.status_code, ok, ms, tag, log_fetch)
                return r.status_code, (r.json() if ok else None), r.headers
            except (httpx.HTTPError, ValueError) as e:
                last_err = repr(e)
                self._record(url, 0, False, int((time.monotonic() - t0) * 1000), last_err, log_fetch)
                time.sleep(min(30, 2 ** attempt * 1.5))
        log.warning("%s fetch failed after retries: %s (%s)", self.source, url, last_err)
        return 0, None, {}

    def _record(self, url, status, ok, ms, note, enabled):
        if not enabled:
            return
        url = re.sub(r"(apiKey|api_key|key)=[^&]+", r"\1=REDACTED", url)
        try:
            with session() as s:
                s.add(FetchLog(source=self.source, url=url[:2000], status=status, ok=ok, elapsed_ms=ms, note=note))
                s.commit()
        except Exception:  # logging must never break ingestion
            log.exception("fetch log write failed")
