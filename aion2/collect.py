"""One collector run: the whole item list, the crafts, then series for a shortlist of items.

The item list and crafts take a handful of requests. The per-item series take three requests an
item, so they are fetched for a shortlist only, and a stored response younger than
``cache_minutes`` is reused (the site collects once an hour).
"""

import math

from . import db
from .api import ApiError, Client
from .config import Config


# The per-item requests; analysis reads them back from the store with the same path and params.
def price_request(key: int):
    # hourly, so listings disappearing between snapshots can stand in for sales where there are none
    return f"/items/{key}/prices", {"range": "30d", "bucket": "1h"}


def volume_request(key: int):
    return f"/items/{key}/volume", {"range": "30d"}


def ladder_request(key: int):
    return f"/items/{key}/depth/ladder", {}


def craft_request(key: int):
    return f"/crafts/{key}", {"range": "14d", "bucket": "6h"}


def _words(text: str) -> list[str]:
    return "".join(c if c.isalnum() else " " for c in text.lower()).split()


def match_server(servers: list[dict], name: str) -> list[dict]:
    """Servers whose name, faction and region together contain every word of ``name``
    ("Hadala Asia" matches a server named Hadala in the Asia region)."""
    wanted = _words(name)
    return [s for s in servers
            if all(w in _words(" ".join(str(s.get(k) or "") for k in
                                        ("name", "faction", "region", "region_name"))) for w in wanted)]


def resolve_server(client: Client, wanted: int | str | None = None) -> tuple[int, str]:
    listing = client.get("/servers")
    servers = {s["server_id"]: s for s in listing["servers"]}
    server_id = wanted if isinstance(wanted, int) else listing["default"]
    if isinstance(wanted, str):
        found = match_server(listing["servers"], wanted)
        if len(found) != 1:
            options = "\n".join(f"  {s['server_id']}: {s['name']} ({s.get('faction') or '?'}, "
                                f"{s.get('region_name') or s.get('region') or '?'})"
                                for s in (found or listing["servers"]))
            raise SystemExit(f"server {wanted!r} matches {len(found) or 'no'} servers; "
                             f"use a more exact name or the id:\n{options}")
        server_id = found[0]["server_id"]
    if server_id not in servers:
        raise SystemExit(f"server {server_id} is not one of the API's servers; run `python -m aion2 servers`")
    if not servers[server_id].get("has_data"):
        print(f"warning: the API has no data collected for server {server_id} yet")
    client.server = server_id
    return server_id, servers[server_id]["name"]


def collect_items(client: Client, conn, server_id: int) -> int:
    offset, seen, stamp = 0, 0, db.now()
    while True:
        page = client.get("/items", limit=1000, offset=offset, sort="key", window="24h")
        for it in page["items"]:
            category = it.get("category") or {}
            row = (server_id, it["item_key"], it.get("name"), category.get("section_id"), category.get("name"),
                   it.get("price") if it.get("listed", True) else None, it.get("listings"), it.get("change_pct"),
                   it.get("units_sold"), it.get("sold_avg_price"), it.get("sold_min_price"),
                   it.get("sold_max_price"), it.get("captured_at"), stamp)
            conn.execute("INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
            if it.get("captured_at"):
                conn.execute("INSERT OR IGNORE INTO item_snapshots VALUES (?,?,?,?,?,?,?)",
                             (server_id, it["item_key"], it["captured_at"], row[5], it.get("listings"),
                              it.get("units_sold"), it.get("sold_avg_price")))
        seen += len(page["items"])
        offset += len(page["items"])
        if not page["items"] or offset >= page["total"]:
            break
    conn.commit()
    return seen


def collect_crafts(client: Client, conn, server_id: int) -> int:
    listing = client.get("/crafts")
    stamp = db.now()
    conn.execute("DELETE FROM crafts WHERE server_id=?", (server_id,))
    for t in listing["targets"]:
        conn.execute("INSERT INTO crafts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (server_id, t["target_key"], t.get("name"), t.get("category"), t.get("profile_label"),
                      t.get("cost"), t.get("cost_market"), t.get("market_price"), t.get("listings"),
                      t.get("carried"), t.get("missing"), stamp))
    conn.commit()
    return len(listing["targets"])


def collect_movers(client: Client) -> tuple[list[int], bool]:
    """The site's biggest price drops and listing drops over 24h and 7d, and whether this server has
    sales statistics at all (some servers only have hourly price and listing snapshots)."""
    movers, has_stats = [], False
    for window in ("24h", "7d"):
        overview = client.get("/overview", window=window, min_listings=2)
        has_stats = has_stats or bool((overview.get("freshness") or {}).get("latest_stats_fetched_at"))
        for kind in ("price_down", "listings_down", "price_up"):
            movers += [m["item_key"] for m in overview.get("movers", {}).get(kind, [])]
    return list(dict.fromkeys(movers)), has_stats


def shortlist(conn, server_id: int, cfg: Config, movers: list[int] = ()) -> list[int]:
    """The items worth a closer look: the watchlist, the site's movers, then a mix of the cheapest
    against their sale price, the biggest 24h changes and the busiest. Without sales statistics,
    "busiest" means the most listings. Craft outputs are added by the craft step."""
    rows = conn.execute(
        """SELECT item_key, price, listings, sold_avg_price, change_pct, units_sold FROM items
           WHERE server_id=? AND price > 0 AND listings > 0
             AND (units_sold >= ? OR (units_sold IS NULL AND listings >= ?))""",
        (server_id, cfg.collect.min_units_sold_28d, cfg.collect.min_listings)).fetchall()
    n = cfg.collect.shortlist
    allowed = {r["item_key"] for r in rows}

    def discount(r):
        return 1 - r["price"] / r["sold_avg_price"] if r["sold_avg_price"] else -math.inf

    picks: list[int] = list(cfg.collect.watchlist) + [k for k in movers if k in allowed]
    for ranking, share in ((discount, 0.4), (lambda r: abs(r["change_pct"] or 0), 0.3),
                           (lambda r: (r["units_sold"] or 0, r["listings"]), 0.3)):
        for r in sorted(rows, key=ranking, reverse=True)[: math.ceil(n * share)]:
            picks.append(r["item_key"])
    return list(dict.fromkeys(picks))[: n + len(cfg.collect.watchlist)]


def fetch_cached(client: Client, conn, server_id: int, request, max_age: float, log) -> bool:
    path, params = request
    if db.load_response(conn, server_id, path, params, max_age) is not None:
        return False
    try:
        body = client.get(path, **params)
    except ApiError as e:
        if e.status in (404, 422):  # an item without that series; nothing to store
            log(f"  skip {path}: {e.status}")
            return False
        raise
    db.save_response(conn, server_id, path, params, body)
    conn.commit()
    return True


def craft_candidates(conn, server_id: int, cfg: Config) -> list[int]:
    rows = conn.execute(
        """SELECT target_key, cost, market_price FROM crafts
           WHERE server_id=? AND cost > 0 AND market_price > 0 AND COALESCE(missing, 0) = 0""",
        (server_id,)).fetchall()
    fee = cfg.sales_fee
    rows = sorted(rows, key=lambda r: (r["market_price"] * (1 - fee) - r["cost"]) / r["cost"], reverse=True)
    return [r["target_key"] for r in rows[: cfg.collect.craft_details]]


def recipe_materials(detail: dict) -> list[dict]:
    """Every material of a stored craft detail, across its steps."""
    return [m for step in detail.get("steps", []) for m in step.get("materials", [])]


def craft_materials(conn, server_id: int, targets: list[int]) -> list[int]:
    """The materials of these crafts that are sold on the market, from their stored details."""
    keys = []
    for target in targets:
        detail = db.load_response(conn, server_id, *craft_request(target))
        keys += [m["material_key"] for m in recipe_materials(detail or {}) if m.get("material_key")]
    listed = {r[0] for r in conn.execute("SELECT item_key FROM items WHERE server_id=?", (server_id,))}
    return [k for k in dict.fromkeys(keys) if k in listed]


def run(cfg: Config, log=print) -> None:
    client = Client(cfg.base_url, None, cfg.delay_seconds)
    conn = db.connect(cfg.db)
    server_id, name = resolve_server(client, cfg.server)
    db.set_home_server(conn, server_id)
    log(f"server {server_id} ({name})")

    log(f"items: {collect_items(client, conn, server_id)}")
    try:
        log(f"crafts: {collect_crafts(client, conn, server_id)}")
    except ApiError as e:
        log(f"crafts: unavailable ({e})")

    movers, has_stats = collect_movers(client)
    if not has_stats:
        log("no sales statistics or listing depth on this server: demand is estimated from listings")
    max_age = cfg.collect.cache_minutes
    crafts = craft_candidates(conn, server_id, cfg)
    fetched = 0
    for key in crafts:  # first, so their materials can join the shortlist
        fetched += fetch_cached(client, conn, server_id, craft_request(key), max_age, log)
    materials = craft_materials(conn, server_id, crafts)
    keys = list(dict.fromkeys(shortlist(conn, server_id, cfg, movers) + crafts + materials))
    requests = (price_request, volume_request, ladder_request) if has_stats else (price_request,)
    log(f"series for {len(keys)} items ({len(crafts)} crafts, {len(materials)} materials; about "
        f"{len(keys) * len(requests) * cfg.delay_seconds / 60:.0f} min if nothing is cached)")
    for i, key in enumerate(keys, 1):
        for request in (r(key) for r in requests):
            fetched += fetch_cached(client, conn, server_id, request, max_age, log)
        if i % 25 == 0:
            log(f"  {i}/{len(keys)} items")
    log(f"done: {client.requests} requests ({fetched} series fetched, the rest cached)")
    conn.close()
