"""Price alerts: someone watches an item below a price, and hears once each time it gets cheaper."""

from dataclasses import dataclass

from . import db


@dataclass
class Alert:
    user_id: int
    channel_id: int
    item_key: int
    name: str
    price: float
    below: float
    listings: int | None


def add(conn, user_id: int, server_id: int, item_key: int, below: float, channel_id: int) -> None:
    conn.execute("""INSERT INTO watches VALUES (?, ?, ?, ?, ?, NULL, ?)
                    ON CONFLICT (user_id, server_id, item_key)
                    DO UPDATE SET below=excluded.below, channel_id=excluded.channel_id, last_alert_price=NULL""",
                 (user_id, server_id, item_key, below, channel_id, db.now()))
    conn.commit()


def remove(conn, user_id: int, server_id: int, item_key: int) -> bool:
    gone = conn.execute("DELETE FROM watches WHERE user_id=? AND server_id=? AND item_key=?",
                        (user_id, server_id, item_key)).rowcount
    conn.commit()
    return bool(gone)


def of_user(conn, user_id: int, server_id: int) -> list:
    return conn.execute(
        """SELECT w.item_key, COALESCE(i.name, w.item_key) AS name, w.below, i.price, i.listings
           FROM watches w LEFT JOIN items i ON i.server_id=w.server_id AND i.item_key=w.item_key
           WHERE w.user_id=? AND w.server_id=? ORDER BY name""", (user_id, server_id)).fetchall()


def check(watches, prices: dict) -> tuple[list[Alert], list[tuple]]:
    """Watches whose item is now listed at or below their price, and cheaper than when they were
    last told (so one listing doesn't alert every hour); a watch whose item went back above its
    price is re-armed. ``watches`` are mappings with user_id, item_key, below, channel_id and
    last_alert_price; ``prices`` is {item_key: (name, price, listings)}. Returns the alerts and the
    (user_id, item_key, new last_alert_price) updates to store."""
    alerts, updates = [], []
    for w in watches:
        name, price, listings = prices.get(w["item_key"], (None, None, None))
        if price is None or price > w["below"]:
            if w["last_alert_price"] is not None:
                updates.append((w["user_id"], w["item_key"], None))
            continue
        if w["last_alert_price"] is not None and price >= w["last_alert_price"]:
            continue
        updates.append((w["user_id"], w["item_key"], price))
        alerts.append(Alert(w["user_id"], w["channel_id"], w["item_key"], name or str(w["item_key"]),
                            price, w["below"], listings))
    return alerts, updates


def prices(conn, server_id: int) -> dict:
    """{item_key: (name, price, listings)} for ``check``, from the latest item list."""
    return {r["item_key"]: (r["name"], r["price"], r["listings"]) for r in conn.execute(
        "SELECT item_key, name, price, listings FROM items WHERE server_id=?", (server_id,))}


def due(conn, server_id: int) -> list[Alert]:
    """The alerts due for the watches stored here (see ``check``), their state updated."""
    rows = conn.execute("SELECT * FROM watches WHERE server_id=?", (server_id,)).fetchall()
    alerts, updates = check(rows, prices(conn, server_id))
    conn.executemany("UPDATE watches SET last_alert_price=? WHERE user_id=? AND server_id=? AND item_key=?",
                     [(price, user, server_id, key) for user, key, price in updates])
    conn.commit()
    return alerts
