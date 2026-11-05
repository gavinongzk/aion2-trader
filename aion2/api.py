"""A small, polite client of the aion2.exchange API (read-only, no key)."""

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

USER_AGENT = f"aion2-trader/{__version__} (personal market analysis)"
RETRY_STATUS = {429, 500, 502, 503, 504}


class ApiError(Exception):
    def __init__(self, status: int | None, url: str, detail: str = ""):
        super().__init__(f"{status or 'network error'} for {url} {detail}".strip())
        self.status = status


class Client:
    def __init__(self, base_url: str, server: int | None = None, delay: float = 1.0,
                 timeout: float = 30, retries: int = 4):
        self.base_url = base_url.rstrip("/")
        self.server = server
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.requests = 0
        self._last = 0.0

    def url(self, path: str, params: dict) -> str:
        params = {k: v for k, v in params.items() if v is not None}
        if self.server is not None and path != "/servers":
            params.setdefault("server", self.server)
        query = urllib.parse.urlencode(params)
        return f"{self.base_url}{path}" + (f"?{query}" if query else "")

    def get(self, path: str, **params):
        url = self.url(path, params)
        for attempt in range(self.retries + 1):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                           "Accept": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as e:
                if e.code not in RETRY_STATUS or attempt == self.retries:
                    raise ApiError(e.code, url, e.read(300).decode("utf-8", "replace")) from None
                retry_after = e.headers.get("Retry-After")
                backoff = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt * 2
            # a response cut off mid-body (IncompleteRead) or a dropped connection: worth another try
            except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError) as e:
                if attempt == self.retries:
                    raise ApiError(None, url, str(e)) from None
                backoff = 2 ** attempt * 2
            time.sleep(backoff)
