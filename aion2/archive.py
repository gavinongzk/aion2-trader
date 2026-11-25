"""Daily price summaries in Supabase (``daily_prices``, see supabase/daily_prices.sql): one row per
server, item and day, the day's median price and listings, kept ``DAILY_DAYS``. Each run uploads the
complete days it hasn't yet (the first run, the 30 days the job's database holds) and deletes older
ones, so a day goes up once. A copy to query, not something the job reads back: the job's own
database stays its working store."""

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from .db import DAILY_DAYS

TABLE = "daily_prices"


def summaries(conn, first: date, last: date) -> list[dict]:
    """The daily rows for ``first``..``last``: from the hourly snapshots where the job still has
    them, else from its own rolled-up ``daily_prices``."""
    groups: dict[tuple, tuple[list, list]] = defaultdict(lambda: ([], []))
    for r in conn.execute("""SELECT server_id, item_key, substr(captured_at, 1, 10) AS day, price, listings
                             FROM item_snapshots WHERE captured_at >= ? AND captured_at < ?""",
                          (first.isoformat(), (last + timedelta(days=1)).isoformat())):
        prices, listings = groups[(r["server_id"], r["item_key"], r["day"])]
        if r["price"]:
            prices.append(r["price"])
        if r["listings"] is not None:
            listings.append(r["listings"])
    rows = {key: {"server_id": key[0], "item_key": key[1], "day": key[2],
                  "price": statistics.median(p) if p else None,
                  "listings": round(statistics.median(n)) if n else None}
            for key, (p, n) in groups.items()}
    for r in conn.execute("SELECT * FROM daily_prices WHERE day >= ? AND day <= ?", (first.isoformat(), last.isoformat())):
        rows.setdefault((r["server_id"], r["item_key"], r["day"]), {
            "server_id": r["server_id"], "item_key": r["item_key"], "day": r["day"],
            "price": r["price"], "listings": r["listings"]})
    return list(rows.values())


def upload(conn, supabase, log=print, today: date | None = None) -> int:
    """Upload the complete days not uploaded yet, drop days past ``DAILY_DAYS``; returns rows sent."""
    today = today or datetime.now(timezone.utc).date()
    last = today - timedelta(days=1)
    row = conn.execute("SELECT value FROM meta WHERE key='supabase_daily_through'").fetchone()
    first = date.fromisoformat(row["value"]) + timedelta(days=1) if row else today - timedelta(days=DAILY_DAYS)
    sent = 0
    if first <= last:
        rows = summaries(conn, first, last)
        supabase.upsert(TABLE, rows, on_conflict="server_id,item_key,day")
        sent = len(rows)
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('supabase_daily_through', ?)", (last.isoformat(),))
        conn.commit()
    supabase.delete_before(TABLE, "day", (today - timedelta(days=DAILY_DAYS)).isoformat())
    log(f"daily prices: {sent} rows uploaded ({first} to {last})" if sent else "daily prices: up to date")
    return sent
