"""What every connector run shares: the output root, a raw cache, polite HTTP, a run record."""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

USER_AGENT = "neorisk-ethcollect/0.1 (+research)"
SECRET_PARAMS = {"apikey", "api_key", "key", "token"}


class FetchError(RuntimeError):
    pass


@dataclass
class Context:
    out: Path
    source: str
    since: date
    until: date
    refresh: bool = False  # True: ignore the cache and fetch again
    rate: float = 2.0  # calls per second for this source
    record: dict = field(default_factory=dict)
    _last: float = 0.0

    @property
    def raw(self) -> Path:
        return self.out / "raw" / self.source

    def note(self, key: str, value) -> None:
        self.record[key] = value

    def count(self, key: str, n: int = 1) -> None:
        self.record[key] = self.record.get(key, 0) + n

    def warn(self, msg: str) -> None:
        self.record.setdefault("warnings", []).append(msg)
        print(f"  warning: {msg}")

    # -- raw cache -------------------------------------------------------------------------

    def cache_path(self, key: str, suffix: str = "") -> Path:
        """Stable file name for a cache key. Secrets never reach the key, so never the disk."""
        digest = hashlib.sha1(key.encode()).hexdigest()[:16]
        return self.raw / f"{digest}{suffix}"

    def cached(self, key: str, fetch, suffix: str = "") -> bytes:
        p = self.cache_path(key, suffix)
        if p.exists() and not self.refresh:
            self.count("cache_hits")
            return p.read_bytes()
        body = fetch()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
        self.count("fetched")
        return body

    # -- http --------------------------------------------------------------------------------

    def _throttle(self) -> None:
        wait = 1.0 / self.rate - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def http(self, url: str, *, data: bytes | None = None, headers=None, tries: int = 6) -> bytes:
        """POST if `data`, else GET. Retries 429 and 5xx with back-off (Retry-After wins)."""
        hdrs = {"user-agent": USER_AGENT, **(headers or {})}
        for attempt in range(tries):
            self._throttle()
            req = urllib.request.Request(url, data=data, headers=hdrs)
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    return r.read()
            except (urllib.error.URLError, TimeoutError) as e:
                code = getattr(e, "code", None)
                if code is not None and code < 500 and code != 429:
                    raise FetchError(f"{code} from {redact(url)}") from e
                if attempt == tries - 1:
                    raise FetchError(f"{e} from {redact(url)}") from e
                hdrs_in = getattr(e, "headers", None) or {}
                reset_ms = hdrs_in.get("x-ratelimit-reset")  # Blockscout: ms until reset
                if code == 429 and reset_ms and reset_ms.isdigit() and int(reset_ms) > 60_000:
                    raise FetchError(f"rate limited by {urllib.parse.urlsplit(url).netloc} for "
                                     f"{int(reset_ms) // 60_000} more minutes") from e
                after = hdrs_in.get("retry-after")
                pause = float(after) if after and after.isdigit() else 2 ** (attempt + 1)
                self.count("retries")
                time.sleep(min(pause, 60))
        raise AssertionError("unreachable")

    def get(self, url: str, *, params: dict | None = None, suffix: str = "") -> bytes:
        """GET through the cache. The cache key leaves out secret query parameters."""
        params = params or {}
        full = url + ("?" + urllib.parse.urlencode(params) if params else "")
        return self.cached(self.key_for(url, params), lambda: self.http(full), suffix)

    def forget(self, url: str, params: dict | None = None, suffix: str = "") -> None:
        """Drop a cached response, e.g. an error body that must not be replayed."""
        self.cache_path(self.key_for(url, params or {}), suffix).unlink(missing_ok=True)

    @staticmethod
    def key_for(url: str, params: dict) -> str:
        public = {k: v for k, v in params.items() if k.lower() not in SECRET_PARAMS}
        return url + "?" + urllib.parse.urlencode(sorted(public.items()))

    # -- run record --------------------------------------------------------------------------

    def save_record(self, options: dict) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        p = self.out / "runs" / f"{self.source}-{stamp}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        clean = {k: v for k, v in options.items() if k.lower() not in SECRET_PARAMS}
        p.write_text(json.dumps({"source": self.source, "options": clean, **self.record},
                                indent=2, default=str))
        return p


def redact(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    q = [(k, "***" if k.lower() in SECRET_PARAMS else v)
         for k, v in urllib.parse.parse_qsl(parts.query)]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(q)))


def default_window(days: int = 365) -> tuple[date, date]:
    today = datetime.now(UTC).date()
    return today - timedelta(days=days), today


def env(name: str) -> str | None:
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else None
