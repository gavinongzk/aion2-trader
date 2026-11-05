"""The local SQLite store: the latest item list, our own snapshots of it, and raw API responses."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    server_id INTEGER, item_key INTEGER, name TEXT, section_id TEXT, category TEXT,
    price REAL, listings INTEGER, change_pct REAL, units_sold INTEGER,
    sold_avg_price REAL, sold_min_price REAL, sold_max_price REAL,
    captured_at TEXT, updated_at TEXT,
    PRIMARY KEY (server_id, item_key)
);
-- one row per item per collector run: our own history, kept even if the site's goes away
CREATE TABLE IF NOT EXISTS item_snapshots (
    server_id INTEGER, item_key INTEGER, captured_at TEXT,
    price REAL, listings INTEGER, units_sold INTEGER, sold_avg_price REAL,
    PRIMARY KEY (server_id, item_key, captured_at)
);
CREATE TABLE IF NOT EXISTS crafts (
    server_id INTEGER, target_key INTEGER, name TEXT, category TEXT, profile_label TEXT,
    cost REAL, cost_market REAL, market_price REAL, listings INTEGER,
    carried INTEGER, missing INTEGER, updated_at TEXT,
    PRIMARY KEY (server_id, target_key)
);
-- Discord price alerts: tell user_id in channel_id when item_key is listed at or below ``below``
CREATE TABLE IF NOT EXISTS watches (
    user_id INTEGER, server_id INTEGER, item_key INTEGER, below REAL, channel_id INTEGER,
    last_alert_price REAL, created_at TEXT,
    PRIMARY KEY (user_id, server_id, item_key)
);
-- every idea the analysis made, once a day at most per strategy and item, to score it later
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY, server_id INTEGER, strategy TEXT, kind TEXT, item_key INTEGER, name TEXT,
    called_at TEXT, entry REAL, target REAL, score REAL, rank INTEGER, posted INTEGER, metrics TEXT
);
CREATE INDEX IF NOT EXISTS calls_item ON calls (server_id, strategy, item_key, called_at);
-- what the price did after a call: at 24h, 72h and 168h
CREATE TABLE IF NOT EXISTS outcomes (
    call_id INTEGER, horizon_h INTEGER, price REAL, best REAL, ret REAL, best_ret REAL, hit INTEGER,
    evaluated_at TEXT,
    PRIMARY KEY (call_id, horizon_h)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
-- per-item series (prices, volume, listings, craft detail) exactly as the API returned them
CREATE TABLE IF NOT EXISTS responses (
    server_id INTEGER, path TEXT, params TEXT, fetched_at TEXT, body TEXT,
    PRIMARY KEY (server_id, path, params)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _params_key(params: dict) -> str:
    return json.dumps({k: v for k, v in params.items() if v is not None}, sort_keys=True)


def save_response(conn, server_id: int, path: str, params: dict, body) -> None:
    conn.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?)",
                 (server_id, path, _params_key(params), now(), json.dumps(body)))


def load_response(conn, server_id: int, path: str, params: dict, max_age_minutes: float | None = None):
    row = conn.execute("SELECT fetched_at, body FROM responses WHERE server_id=? AND path=? AND params=?",
                       (server_id, path, _params_key(params))).fetchone()
    if row is None:
        return None
    if max_age_minutes is not None:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(row["fetched_at"])
        if age > timedelta(minutes=max_age_minutes):
            return None
    return json.loads(row["body"])


def set_home_server(conn, server_id: int) -> None:
    """Remember which server is yours: analysis reads it back, as other servers' data is stored too."""
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('home_server_id', ?)", (str(server_id),))
    conn.commit()
