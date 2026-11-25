"""The Supabase tables of the online setup: the Discord price alerts (``watches``), read and written by
the hourly job and the slash-command function; and the daily price summaries (``daily_prices``),
uploaded by the job (``archive``). Plain HTTPS to Supabase's REST API with the
project's secret key (sb_secret_..., or a legacy service_role key), from SUPABASE_URL and
SUPABASE_SERVICE_KEY (never in the repo)."""

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
        headers = {"apikey": self.key, "Content-Type": "application/json"}
        if self.key.startswith("eyJ"):  # a legacy service_role key (a JWT); the new sb_secret_ keys go in apikey only
            headers["Authorization"] = f"Bearer {self.key}"
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

    def upsert(self, table: str, rows: list[dict], on_conflict: str, batch: int = 5000) -> None:
        for i in range(0, len(rows), batch):
            self._call("POST", table, {"on_conflict": on_conflict}, rows[i:i + batch],
                       prefer="resolution=merge-duplicates,return=minimal")

    def delete_before(self, table: str, column: str, value: str) -> None:
        self._call("DELETE", table, {column: f"lt.{value}"}, prefer="return=minimal")
