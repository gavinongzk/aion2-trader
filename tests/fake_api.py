"""A local stand-in for the aion2.exchange API, shaped like its OpenAPI schema, with made-up items
that each show one pattern. Used by the tests; never talks to the real site."""

import json
import math
import re
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
STEP = timedelta(hours=6)
CAT = {"id": 1, "name": "Ore", "section_id": "materials", "section_name": "Materials"}


def iso(t):
    return t.isoformat().replace("+00:00", "Z")


def flat(price):
    return lambda i, n: price * (1 + 0.03 * math.sin(i))


def dip(i, n):  # sat around 10k for a month, dropped to 8k in the last day
    return 10000 * (1 + 0.04 * math.sin(i)) if i < n - 4 else 8000


def slide(i, n):  # sat around 10k, then slid steadily to 8k over the last week: not a dip
    return 10000 * (1 + 0.04 * math.sin(i)) if i < n - 28 else 10000 - 2000 * (i - (n - 28)) / 27


def rise(i, n):  # flat at 5k, then +3%/day over the last week
    return 5000 if i < n - 28 else 5000 * 1.03 ** ((i - (n - 28)) / 4)


# key: name, price now, listings now, 28-day units sold, average sale price, price path, listings path, ladder
ITEMS = {
    100000001: ("Cheap Ore", 7000, 30, 600, 10000, flat(10000), lambda i, n: 30,
                [(7000, 3), (9600, 20), (9900, 40)]),
    100000002: ("Dipping Scale", 8000, 25, 300, 8300, dip, lambda i, n: 25, [(8000, 10), (8100, 20)]),
    100000005: ("Sliding Scale", 8000, 25, 300, 8300, slide, lambda i, n: 25, [(8000, 10), (8100, 20)]),
    100000003: ("Rising Essence", 6100, 12, 400, 6000, rise, lambda i, n: 40 if i < n - 28 else 15,
                [(6100, 5), (6200, 10)]),
    100000004: ("Dead Relic", 50, 3, 4, 100, flat(100), lambda i, n: 3, [(50, 3)]),
    200000001: ("Splendent Blade", 520000, 4, 60, 515000, flat(520000), lambda i, n: 4, [(520000, 4)]),
}
CRAFTS = [
    {"target_key": 200000001, "name": "Splendent Blade", "category": "Weapon", "skill": "Weaponsmithing",
     "profile": "w1", "profile_label": "Weapon", "cost": 392000, "cost_market": 470000,
     "market_price": 520000, "listings": 4, "carried": 0, "missing": 0, "margin": 128000,
     "margin_pct": 32.6, "attempts": []},
    {"target_key": 200000002, "name": "Splendent Bow", "category": "Weapon", "skill": "Weaponsmithing",
     "profile": "w1", "profile_label": "Weapon", "cost": 100000, "cost_market": 120000,
     "market_price": 900000, "listings": 1, "carried": 0, "missing": 2, "margin": 800000,
     "margin_pct": 800, "attempts": []},
]


def history(key):
    name, price, listings, sold, avg, path, lpath, _ = ITEMS[key]
    n = 120
    points = []
    for i in range(n):
        p = price if i == n - 1 else path(i, n)
        points.append({"ts": iso(NOW - STEP * (n - 1 - i)), "low": p, "high": p, "avg": p, "close": p,
                       "listings": lpath(i, n), "listings_min": 0, "listings_max": 0, "samples": 6})
    return points


def item_summary(key):
    name, price, listings, sold, avg, *_ = ITEMS[key]
    return {"item_key": key, "name": name, "category": CAT, "group": None, "price": price,
            "listings": listings, "captured_at": iso(NOW), "listed": True, "last_seen_at": iso(NOW),
            "last_price": price, "change_pct": -5.0, "change_basis_seconds": 86400, "units_sold": sold,
            "sold_avg_price": avg, "sold_min_price": avg * 0.8, "sold_max_price": avg * 1.2}


def route(path, q):
    if path == "/api/servers":
        return {"default": 7, "servers": [{"server_id": 7, "name": "Test World", "game_server_key": 1,
                                           "region": "eu", "region_name": "Europe", "faction": "Elyos",
                                           "has_data": True}]}
    if q.get("server") != ["7"]:
        return 422, {"detail": "server missing"}
    if path == "/api/items":
        limit, offset = int(q["limit"][0]), int(q["offset"][0])
        keys = sorted(ITEMS)
        return {"total": len(keys), "limit": limit, "offset": offset, "sort": "key", "order": "asc",
                "window": "24h", "items": [item_summary(k) for k in keys[offset:offset + limit]]}
    if path == "/api/overview":
        return {"server_id": 7, "items": len(ITEMS), "freshness": {"latest_stats_fetched_at": iso(NOW)},
                "movers": {"price_down": [{"item_key": 100000002}], "listings_down": [], "price_up": []}}
    if path == "/api/crafts":
        return {"server_id": 7, "faction": "Elyos", "race": "Elyos", "model": None,
                "captured_at": iso(NOW), "targets": CRAFTS}
    if m := re.fullmatch(r"/api/crafts/(\d+)", path):
        points = [{"ts": iso(NOW - STEP * (55 - i)), "cost": 392000, "cost_market": 470000,
                   "market_price": 520000 if i % 5 else 400000} for i in range(56)]
        steps = [{"step_no": 1, "recipe_id": 1, "mastery_level": 1, "success_rate": 0.25,
                  "combo_probability": 0, "attempts": 4, "result_key": int(m[1]), "result_name": "x",
                  "step_cost": 392000, "materials": [
                      {"material_key": 1, "name": "Star Dragon Scale", "per_attempt": 2, "expected": 8,
                       "unit_price": 41000, "subtotal": 328000, "listing_price": 50000, "method": "craft",
                       "via": []},
                      {"material_key": 2, "name": "Refined Ore", "per_attempt": 5, "expected": 20,
                       "unit_price": 3000, "subtotal": 60000, "listing_price": 3000, "method": "buy",
                       "via": []}]}]
        return {"target_key": int(m[1]), "steps": steps, "tiers": [],
                "series": {"range_start": "", "range_end": "", "bucket": "6h", "auto": False, "points": points}}
    m = re.fullmatch(r"/api/items/(\d+)/(prices|volume|depth/ladder)", path)
    if not m or int(m[1]) not in ITEMS:
        return 404, {"detail": "not found"}
    key, kind = int(m[1]), m[2]
    if kind == "prices":
        return {"item_key": key, "bucket": "6h", "auto": False, "points": history(key), "summary": {}}
    if kind == "volume":
        sold = ITEMS[key][3]
        return {"item_key": key, "days": [{"registered": iso(NOW - timedelta(days=29 - d)),
                                           "units_sold": sold, "last_fetched_at": iso(NOW),
                                           "observations": 1, "variants": 1} for d in range(30)]}
    levels, cum_u, cum_c = [], 0, 0
    for price, units in ITEMS[key][7]:
        cum_u += units
        cum_c += price * units
        levels.append({"unit_price": price, "listings": 1, "units": units, "cum_units": cum_u, "cum_cost": cum_c})
    return {"item_key": key, "captured_at": iso(NOW), "complete": True, "listings_total": len(levels),
            "units_total": cum_u, "levels": levels}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        result = route(url.path, parse_qs(url.query))
        status, body = result if isinstance(result, tuple) else (200, result)
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def start() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/api"
