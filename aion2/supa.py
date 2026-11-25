"""The Supabase table the online setup shares: the Discord price alerts (``watches``), read and written
by the hourly job and the slash-command function. Plain HTTPS to Supabase's REST API with the
service key, from SUPABASE_URL and SUPABASE_SERVICE_KEY (never in the repo)."""

import json
import os
import urllib.parse
import urllib.request


class Supabase:
    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/")
        self.key = key

    @classmethod
    def from_env(cls) -> "Supabase | None":
        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
        return cls(url, key) if url and key else None

    def _call(self, method: str, table: str, query: dict | None = None, body=None, prefer: str | None = None):
        url = f"{self.url}/rest/v1/{table}" + (f"?{urllib.parse.urlencode(query)}" if query else "")
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        req = urllib.request.Request(url, method=method, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
        with urllib.request.urlopen(req, timeout=20) as res:
            text = res.read()
            return json.loads(text) if text else None

    def select(self, table: str, **filters) -> list[dict]:
        return self._call("GET", table, {"select": "*", **{k: f"eq.{v}" for k, v in filters.items()}})

    def update(self, table: str, values: dict, **filters) -> None:
        self._call("PATCH", table, {k: f"eq.{v}" for k, v in filters.items()}, values)
