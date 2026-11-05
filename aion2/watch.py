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


def due(conn, server_id: int) -> list[Alert]:
    """Watches whose item is now listed at or below their price, and cheaper than when they were
    last told (so one listing doesn't alert every hour). A watch whose item went back above its
    price is re-armed."""
    rows = conn.execute(
        """SELECT w.*, i.name, i.price, i.listings FROM watches w
           JOIN items i ON i.server_id=w.server_id AND i.item_key=w.item_key
           WHERE w.server_id=?""", (server_id,)).fetchall()
    alerts = []
    for r in rows:
        price = r["price"]
        if price is None or price > r["below"]:
            if r["last_alert_price"] is not None:
                conn.execute("UPDATE watches SET last_alert_price=NULL WHERE user_id=? AND server_id=? AND item_key=?",
                             (r["user_id"], server_id, r["item_key"]))
            continue
        if r["last_alert_price"] is not None and price >= r["last_alert_price"]:
            continue
        conn.execute("UPDATE watches SET last_alert_price=? WHERE user_id=? AND server_id=? AND item_key=?",
                     (price, r["user_id"], server_id, r["item_key"]))
        alerts.append(Alert(r["user_id"], r["channel_id"], r["item_key"], r["name"] or str(r["item_key"]),
                            price, r["below"], r["listings"]))
    conn.commit()
    return alerts
