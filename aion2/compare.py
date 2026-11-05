"""Prices across comparable servers: where each item is cheap or dear, and how pricey each server is.

"Comparable" means the home server's region, both factions (``scope = "region"``) or its faction
only (``scope = "faction"``). Each server's item list is one request, so a run over a region's 20
servers takes about 20 requests; a server collected within ``cache_minutes`` is reused.

An item's price on a server is the median of its cheapest listing over the last 24 hours of our
snapshots (one stray listing at an absurd price then moves nothing). Its ratio on a server is that
price over the median of all servers that list it. A server's index is the geometric mean of its
items' ratios over the basket (items listed on at least ``min_servers`` servers), leaving out the
10% most extreme at each end: 1.10 means things there cost about 10% more than on a
typical comparable server.
"""

import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db, scorecard, value
from .api import Client
from .collect import collect_items, resolve_server
from .config import Config
from .stats import quantile


def typical_ratio(ratios: list[float], trim: float = 0.1) -> float | None:
    """Geometric mean of ``ratios`` without the ``trim`` share at each end. A plain median sits at
    exactly 1.0 when most items share a round price, and hides a server that is dearer across the board."""
    logs = sorted(math.log(r) for r in ratios if r > 0)
    cut = int(len(logs) * trim)
    logs = logs[cut: len(logs) - cut] or logs
    return math.exp(statistics.fmean(logs)) if logs else None


def comparable(servers: list[dict], home: dict, scope: str = "region") -> list[dict]:
    """The servers to compare with ``home`` (``home`` included), in the API's order."""
    if scope not in ("region", "faction"):
        raise ValueError(f"compare scope must be 'region' or 'faction', not {scope!r}")
    return [s for s in servers if s.get("has_data", True) and s.get("region") == home.get("region")
            and (scope == "region" or s.get("faction") == home.get("faction"))]


def _collected_at(conn, server_id: int) -> datetime | None:
    row = conn.execute("SELECT MAX(updated_at) FROM items WHERE server_id=?", (server_id,)).fetchone()
    return datetime.fromisoformat(row[0]) if row and row[0] else None


def collect(cfg: Config, log=print) -> tuple[int, list[dict]]:
    """Fetch the item list of every comparable server; returns the home id and the servers."""
    client = Client(cfg.base_url, None, cfg.delay_seconds)
    conn = db.connect(cfg.db)
    home_id, _ = resolve_server(client, cfg.server)
    db.set_home_server(conn, home_id)
    servers = client.get("/servers")["servers"]
    home = next(s for s in servers if s["server_id"] == home_id)
    peers = comparable(servers, home, cfg.compare.scope)
    fresh_after = datetime.now(timezone.utc) - timedelta(minutes=cfg.collect.cache_minutes)
    log(f"comparing {len(peers)} servers in {home.get('region_name') or home.get('region')}")
    for s in peers:
        stamp = _collected_at(conn, s["server_id"])
        if stamp and stamp > fresh_after:
            continue
        client.server = s["server_id"]
        log(f"  {s['name']} ({s.get('faction')}): {collect_items(client, conn, s['server_id'])} items")
    conn.close()
    return home_id, peers


def server_prices(conn, server_id: int, since: str, min_listings: int) -> dict[int, dict]:
    """Each listed item's 24h median cheapest price and its latest listings and category."""
    latest = {r["item_key"]: r for r in conn.execute(
        """SELECT item_key, name, category, section_id, price, listings FROM items
           WHERE server_id=? AND price > 0 AND listings >= ?""", (server_id, min_listings))}
    history: dict[int, list[float]] = {}
    for r in conn.execute("""SELECT item_key, price FROM item_snapshots
                             WHERE server_id=? AND captured_at >= ? AND price > 0""", (server_id, since)):
        history.setdefault(r["item_key"], []).append(r["price"])
    return {key: {"name": r["name"], "category": r["category"], "section": r["section_id"],
                  "price": statistics.median(history.get(key) or [r["price"]]), "listings": r["listings"]}
            for key, r in latest.items()}


def build(conn, home_id: int, servers: list[dict], min_servers: int = 5, min_listings: int = 2,
          cfg: Config | None = None) -> dict:
    """The comparison as plain data (what ``reports/compare.json`` holds). With ``cfg`` it also
    holds ``buy``, the valuation of every home-server item, and ``model``, its backtest (see ``value``)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    prices = {s["server_id"]: server_prices(conn, s["server_id"], since, min_listings) for s in servers}
    names = {s["server_id"]: s["name"] for s in servers}

    items, ratios = [], {sid: [] for sid in prices}
    by_section: dict[int, dict[str, list[float]]] = {sid: {} for sid in prices}
    for key in sorted({k for p in prices.values() for k in p}):
        seen = {sid: p[key] for sid, p in prices.items() if key in p}
        if len(seen) < min_servers:
            continue
        values = [v["price"] for v in seen.values()]
        median = statistics.median(values)
        cheapest = min(seen, key=lambda sid: seen[sid]["price"])
        dearest = max(seen, key=lambda sid: seen[sid]["price"])
        any_row = next(iter(seen.values()))
        for sid, v in seen.items():
            ratios[sid].append(v["price"] / median)
            by_section[sid].setdefault(any_row["section"] or "other", []).append(v["price"] / median)
        home = seen.get(home_id)
        items.append({
            "key": key, "name": any_row["name"], "category": any_row["category"], "section": any_row["section"],
            "median": median, "servers": len(seen),
            "home_price": home["price"] if home else None,
            "home_ratio": home["price"] / median if home else None,
            "cheapest": {"server_id": cheapest, "price": seen[cheapest]["price"]},
            "dearest": {"server_id": dearest, "price": seen[dearest]["price"]},
            # how far apart servers usually are; max / min would only measure the wildest listing
            "spread": quantile(values, 0.9) / quantile(values, 0.1),
            "prices": {str(sid): [round(v["price"], 2), v["listings"]] for sid, v in seen.items()},
        })

    home_prices = prices.get(home_id, {})
    rows = []
    for s in servers:
        sid = s["server_id"]
        mine = prices[sid]
        common = [mine[k]["price"] / home_prices[k]["price"] for k in mine if k in home_prices]
        rows.append({
            "id": sid, "name": names[sid], "faction": s.get("faction"), "region": s.get("region"),
            "items": len(mine), "listings": sum(v["listings"] for v in mine.values()),
            "basket": len(ratios[sid]),
            "index": typical_ratio(ratios[sid]),
            "vs_home": 1.0 if sid == home_id else typical_ratio(common),
            "cheapest_count": sum(1 for it in items if it["cheapest"]["server_id"] == sid),
            "sections": {sec: typical_ratio(v) for sec, v in by_section[sid].items() if len(v) >= 3},
        })
    home = next((s for s in servers if s["server_id"] == home_id), {})
    data = {"generated_at": db.now(), "home_id": home_id, "region": home.get("region_name") or home.get("region"),
            "min_servers": min_servers, "min_listings": min_listings, "servers": rows, "items": items}
    if cfg is not None:
        valued, profiles, econ, sections = value.value_all(conn, home_id, prices, cfg, names.get(home_id, "your server"))
        data["buy"] = list(valued.values())
        data["economy"] = {k: v for k, v in econ.items() if not k.startswith("_")}
        data["model"] = value.backtest(profiles, cfg, sections) | {
            "home_weight": cfg.value.home_weight, "margin": cfg.value.margin, "fee": cfg.sales_fee}
    return data


def write(data: dict, reports: str) -> Path:
    path = Path(reports) / "compare.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    return path


def render(data: dict) -> str:
    """A short text summary: the servers from cheapest to dearest."""
    servers = sorted((s for s in data["servers"] if s["index"]), key=lambda s: s["index"])
    lines = [f"Server price index, {data['region']} ({len(data['items'])} items compared; 1.00 = typical)", ""]
    for s in servers:
        mark = "  <- home" if s["id"] == data["home_id"] else ""
        vs = f"{s['vs_home']:.2f}x home" if s["vs_home"] else "   -      "
        lines.append(f"  {s['name']:<14} {s['faction'] or '':<9} {s['index']:.2f}  {vs}  "
                     f"cheapest for {s['cheapest_count']:>3} items, {s['listings']:>6} listings{mark}")
    return "\n".join(lines)


def refresh(cfg: Config, log=print) -> dict:
    """Collect, build and write the comparison; log the valuation's buy calls to the scorecard and
    score the ones that came due, so the model is graded on what happens next."""
    home_id, peers = collect(cfg, log)
    conn = db.connect(cfg.db)
    try:
        data = build(conn, home_id, peers, cfg.compare.min_servers, cfg.compare.min_listings, cfg)
        logged = scorecard.record(conn, home_id, {"value": value.ideas(data["buy"], cfg.strategy.min_per_day)})
        scored = scorecard.evaluate(conn, home_id, cfg.sales_fee)
        lines, pending = scorecard.summary(conn, home_id, strategy="value")
    finally:
        conn.close()
    log(f"value calls: {logged} logged, {scored} outcomes scored")
    data["model"]["live"] = {"pending": pending, "lines": [
        {"kind": l.kind, "horizon_h": l.horizon_h, "n": l.n, "hit_rate": l.hit_rate,
         "median_ret": l.median_ret, "median_best_ret": l.median_best_ret} for l in lines]}
    data["path"] = str(write(data, cfg.reports))
    return data


def run(cfg: Config, log=print) -> Path:
    data = refresh(cfg, log)
    log(render(data))
    if data["model"].get("evaluations"):
        m = data["model"]
        log(f"\nFair value backtest ({m['evaluations']} item-days, {m['horizon_days']:g}-day horizon): "
            f"median error {m['error_fair']:.1%} vs {m['error_now']:.1%} for today's price; "
            f"{m['buy_signals']} buy signals, median return {m['buy_return'] or 0:+.1%} "
            f"(all items {m['all_return']:+.1%})")
    return Path(data["path"])
