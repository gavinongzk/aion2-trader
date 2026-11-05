"""Turns the stored market data into trade ideas, each with the numbers that explain it.

Three strategies:
  flip       buy below what the item usually sells for, relist at the usual price
  craft      craft an item whose market price is above its crafting cost
  speculate  buy into a dip, an uptrend or a supply squeeze and wait

Prices are the cheapest listing ("price"); "units sold" is the API's rolling 28-day total.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from functools import cached_property
from zoneinfo import ZoneInfo

from . import db, timing, trades
from .collect import craft_request, ladder_request, price_request, recipe_materials, volume_request
from .config import Config
from .stats import (daily_volatility, growth_per_day, kina, level_shift, parse_ts, pct, percentile_rank,
                    quantile)

SALES_WINDOW_DAYS = 28


def window_change(series: list, days: float) -> float | None:
    """The median of a (time, value) series over its last 24 hours against the 24 hours ending
    ``days`` earlier (-0.1 = down 10%)."""
    if not series:
        return None
    end = series[-1][0]
    now = [v for t, v in series if t > end - timedelta(hours=24) and v]
    then = [v for t, v in series if end - timedelta(days=days, hours=24) < t <= end - timedelta(days=days) and v]
    if not now or not then:
        return None
    return quantile(now, 0.5) / quantile(then, 0.5) - 1


@dataclass
class Idea:
    strategy: str
    item_key: int
    name: str
    score: float          # expected profit in Kina (flip, craft) or a relative strength (speculate)
    headline: str
    reasons: list[str]
    metrics: dict = field(default_factory=dict)


@dataclass
class Profile:
    """Everything known about one item, from the item list and its stored series."""
    key: int
    name: str
    price: float | None
    listings: int | None
    units_sold: int | None
    sold_avg: float | None
    closes: list = field(default_factory=list)       # (time, cheapest price) per 6h bucket, 30 days
    listing_counts: list = field(default_factory=list)
    volume_days: list = field(default_factory=list)
    ladder: list = field(default_factory=list)       # listings now, cheapest first
    min_shift: float = 0.25                          # a jump this big in the daily median is a new price level

    @property
    def estimated(self) -> bool:
        """No sales statistics for this item: demand comes from listings disappearing."""
        return self.units_sold is None

    @property
    def per_day(self) -> float:
        if self.estimated:
            return self.listings_taken_per_day() or 0
        return self.units_sold / SALES_WINDOW_DAYS

    @property
    def trades(self) -> trades.Trades:
        """Sales and expiries inferred from the series (recomputed when the series grow)."""
        size = (len(self.closes), len(self.listing_counts))
        if getattr(self, "_trades_for", None) != size:
            self._trades, self._trades_for = trades.infer(self.closes, self.listing_counts), size
        return self._trades

    def listings_taken_per_day(self, days: float | None = None, end_days_ago: float = 0) -> float | None:
        """Listings that disappeared between snapshots other than by expiring (bought, or withdrawn),
        per day. It counts listings, not units, and misses anything listed and taken within one hour."""
        series = [(t, v) for t, v in self.listing_counts if v is not None]
        if len(series) < 2:
            return None
        end = series[-1][0] - timedelta(days=end_days_ago)
        start = end - timedelta(days=days) if days else series[0][0]
        series = [(t, v) for t, v in series if start <= t <= end]
        span = (series[-1][0] - series[0][0]).total_seconds() / 86400 if len(series) > 1 else 0
        if span < 1:
            return None
        return sum(n for t, n in self.trades.taken if series[0][0] < t <= series[-1][0]) / span

    def demand(self) -> str:
        if self.estimated:
            return f"~{self.per_day:.1f} listings taken/day (est.)"
        return f"sells ~{self.per_day:.1f}/day"

    @property
    def history_days(self) -> float:
        return (self.closes[-1][0] - self.closes[0][0]).total_seconds() / 86400 if len(self.closes) > 1 else 0

    # The cheapest price jumps whenever cheap stock sells out or someone lists at an absurd price,
    # and a young market drifts a long way in a month: so "usual" is the last 7 days' median and
    # "range" the 10th to 90th percentile of the last 14 days, never the raw low and high. After a
    # sudden change of level (a patch, a drop-rate change) only the days since count.
    @cached_property
    def shift(self) -> tuple[datetime, float] | None:
        """The latest abrupt change of price level: (first day at the new level, new/old ratio).
        Not for items with only a listing or two, whose cheapest price is mostly noise."""
        counts = [v for _, v in self.listing_counts if v is not None]
        if not counts or sum(counts) / len(counts) < 3:
            return None
        return level_shift(self._daily(30, since_shift=False), self.min_shift)

    @property
    def shift_start(self) -> datetime | None:
        if self.shift is None:
            return None
        return datetime.combine(self.shift[0].date(), time.min, tzinfo=timezone.utc)

    def _since_shift(self, series):
        start = self.shift_start
        return series if start is None else [(t, v) for t, v in series if t >= start]

    def _prices(self, days: float):
        return [p for _, p in self._since_shift(self._last(self.closes, days))]

    @property
    def usual(self):
        return quantile(self._prices(7), 0.5)

    @property
    def range14(self) -> tuple[float | None, float | None]:
        prices = self._prices(14)
        return quantile(prices, 0.1), quantile(prices, 0.9)

    @property
    def position(self) -> float | None:
        """Where today's price sits among the last 14 days' prices (0 = lowest, 1 = highest)."""
        prices = self._prices(14)
        return percentile_rank(prices, self.price) if prices and self.price else None

    def _last(self, series, days):
        if not series:
            return []
        start = series[-1][0] - timedelta(days=days)
        return [(t, v) for t, v in series if t >= start]

    @property
    def growth7(self):
        return growth_per_day(self._daily(7))

    @property
    def volatility(self):
        return daily_volatility(self._daily(14))

    def _daily(self, days: float, since_shift: bool = True) -> list:
        """One median price per day, which shrugs off single odd hours."""
        by_day = defaultdict(list)
        points = self._last(self.closes, days)
        for t, p in (self._since_shift(points) if since_shift else points):
            by_day[t.date()].append((t, p))
        return [(points[-1][0], quantile([p for _, p in points], 0.5)) for _, points in sorted(by_day.items())]

    def change(self, days: float = 3) -> float | None:
        """The median price of the last 24 hours against the 24 hours ending ``days`` ago."""
        return window_change(self.closes, days)

    def shift_note(self) -> str | None:
        """A reason line when the price level changed in the last two weeks."""
        if self.shift is None or self.closes[-1][0] - self.shift[0] > timedelta(days=14):
            return None
        days = max(1, round((self.closes[-1][0] - self.shift_start).total_seconds() / 86400))
        ratio = self.shift[1]
        moved = f"jumped {pct(ratio - 1, False)}" if ratio > 1 else f"dropped {pct(1 - ratio, False)}"
        return (f"Price level {moved} on {self.shift_start:%d %b} (a patch or drop change?): "
                f"usual price and range use only the {days} day{'s' * (days > 1)} since.")

    @property
    def listings_avg7(self):
        recent = [v for _, v in self._last(self.listing_counts, 7) if v is not None]
        return sum(recent) / len(recent) if recent else None

    @property
    def demand_trend(self) -> float | None:
        """Change of the 28-day units sold against a week earlier (+0.3 = selling 30% more); without
        sales statistics, listings taken this week against the week before."""
        days = [(parse_ts(d["registered"]), d["units_sold"]) for d in self.volume_days
                if d.get("units_sold") is not None]
        if len(days) < 2:
            this_week = self.listings_taken_per_day(7)
            last_week = self.listings_taken_per_day(7, end_days_ago=7)
            return this_week / last_week - 1 if this_week is not None and last_week else None
        days.sort()
        latest_t, latest = days[-1]
        earlier = [u for t, u in days if t <= latest_t - timedelta(days=6)]
        if not earlier or not earlier[-1]:
            return None
        return latest / earlier[-1] - 1

    def cost_of(self, units: int, max_price: float | None = None) -> tuple[float, int]:
        """What buying up to ``units`` costs now, walking up the listings but none dearer than
        ``max_price``; and how many units that gets."""
        cost, got = 0.0, 0
        for level in self.ladder:
            if max_price is not None and level["unit_price"] > max_price:
                break
            take = min(level["units"], units - got)
            cost += take * level["unit_price"]
            got += take
            if got >= units:
                break
        if not self.ladder and self.price and (max_price is None or self.price <= max_price):
            return self.price, 1  # listing depth unknown: only the cheapest unit is certain
        return cost, got

    @property
    def next_level_gap(self) -> float | None:
        """How much dearer the second-cheapest price is than the cheapest (0.25 = 25%)."""
        if len(self.ladder) < 2:
            return None
        return self.ladder[1]["unit_price"] / self.ladder[0]["unit_price"] - 1


def _profile(conn, server_id: int, r, min_shift: float) -> Profile:
    key = r["item_key"]
    p = Profile(key, r["name"] or str(key), r["price"], r["listings"], r["units_sold"], r["sold_avg_price"],
                min_shift=min_shift)
    prices = db.load_response(conn, server_id, *price_request(key))
    if prices:
        points = [pt for pt in prices.get("points", []) if pt.get("close")]
        p.closes = [(parse_ts(pt["ts"]), pt["close"]) for pt in points]
        p.listing_counts = [(parse_ts(pt["ts"]), pt.get("listings")) for pt in points]
    volume = db.load_response(conn, server_id, *volume_request(key))
    if volume:
        p.volume_days = volume.get("days", [])
    ladder = db.load_response(conn, server_id, *ladder_request(key))
    if ladder:
        p.ladder = ladder.get("levels", [])
    return p


def load_profiles(conn, server_id: int, min_shift: float = 0.25) -> dict[int, Profile]:
    return {r["item_key"]: _profile(conn, server_id, r, min_shift)
            for r in conn.execute("SELECT * FROM items WHERE server_id=?", (server_id,)).fetchall()}


def load_profile(conn, server_id: int, item_key: int, min_shift: float = 0.25) -> Profile | None:
    r = conn.execute("SELECT * FROM items WHERE server_id=? AND item_key=?", (server_id, item_key)).fetchone()
    return _profile(conn, server_id, r, min_shift) if r else None


def material_uses(conn, server_id: int, item_key: int) -> list[tuple[str, float, float]]:
    """The crafts whose recipe uses this item: (craft name, expected units per craft, share of the
    craft's cost), from the stored craft details, biggest share first."""
    uses = []
    for r in conn.execute("SELECT target_key, name, cost FROM crafts WHERE server_id=?", (server_id,)).fetchall():
        detail = db.load_response(conn, server_id, *craft_request(r["target_key"]))
        mats = [m for m in recipe_materials(detail or {}) if m.get("material_key") == item_key]
        if mats:
            qty = sum(m.get("expected") or 0 for m in mats)
            share = sum(m.get("subtotal") or 0 for m in mats) / r["cost"] if r["cost"] else 0
            uses.append((r["name"] or str(r["target_key"]), qty, share))
    return sorted(uses, key=lambda u: u[2], reverse=True)


def search_items(conn, server_id: int, text: str, limit: int = 25) -> list:
    """Items whose name contains every word of ``text``, the most listed first."""
    words = text.split()
    where = " AND ".join("name LIKE ?" for _ in words) or "1"
    return conn.execute(f"""SELECT item_key, name, price, listings FROM items
                            WHERE server_id=? AND name IS NOT NULL AND {where}
                            ORDER BY listings DESC, name LIMIT ?""",
                        (server_id, *(f"%{w}%" for w in words), limit)).fetchall()


def flips(profiles: dict[int, Profile], cfg: Config) -> list[Idea]:
    s, fee, ideas = cfg.strategy, cfg.sales_fee, []
    for p in profiles.values():
        if not p.price or not p.closes or p.per_day < s.min_per_day:
            continue
        if not p.usual:
            continue
        # resell at the lowest of what it sold for on average, its usual listed price, and where it
        # has been the last 2 days (a falling item won't climb back to last week's median)
        recent = quantile(p._prices(2), 0.5)
        resale = min(x for x in (p.sold_avg, p.usual, recent) if x)
        qty = max(1, min(s.max_qty, int(p.per_day * s.hold_days)))
        # only listings cheap enough to clear the minimum return after the fee
        cost, got = p.cost_of(qty, max_price=resale * (1 - fee) / (1 + s.flip_min_roi))
        if got == 0:
            continue
        unit_cost = cost / got
        net = resale * (1 - fee) - unit_cost
        roi = net / unit_cost
        if roi < s.flip_min_roi:
            continue
        sold = f"avg sale {kina(p.sold_avg)} and " if p.sold_avg else ""
        reasons = [
            f"Cheapest {kina(p.price)} vs {sold}7-day median {kina(p.usual)} and 2-day median {kina(recent)}"
            f" ({pct(p.price / resale - 1)}).",
            f"{p.demand().capitalize()}; {p.listings} listed.",
            (f"Buying {got} costs {kina(cost)} (avg {kina(unit_cost)}); " if p.ladder else
             "Listing depth isn't tracked on this server: check in game how many sit at this price; ")
            + f"relisting at {kina(resale)} nets {kina(net)}/unit after the {pct(fee, False)} fee.",
        ]
        gap = p.next_level_gap
        if gap is not None and gap >= 0.15:
            reasons.append(f"Next listing is {pct(gap, False)} dearer: the cheap one looks underpriced, "
                           f"likely to go fast.")
        if p.growth7 is not None and p.growth7 <= -0.02:
            reasons.append(f"Caution: price falling {pct(p.growth7)}/day over 7 days; it may keep sliding.")
        if p.demand_trend is not None and p.demand_trend <= -0.25:
            reasons.append(f"Caution: {'listings taken' if p.estimated else 'sales'} down "
                           f"{pct(p.demand_trend)} on a week ago.")
        reasons += context_notes(p, cfg)
        ideas.append(Idea("flip", p.key, p.name, net * got,
                          f"buy {got} @ ~{kina(unit_cost)}, sell @ {kina(resale)}: "
                          f"+{kina(net * got)} ({pct(roi)})",
                          reasons, {"qty": got, "unit_cost": unit_cost, "resale": resale,
                                    "net_per_unit": net, "roi": roi, "per_day": p.per_day,
                                    "entry": unit_cost, "target": resale}))
    return sorted(ideas, key=lambda i: i.score, reverse=True)


def context_notes(p: Profile, cfg: Config) -> list[str]:
    """A recent change of price level, and an hour-of-day pattern worth timing the trade by."""
    notes = []
    if p.shift_note():
        notes.append(p.shift_note())
    hours = timing.hourly(p.closes, ZoneInfo(cfg.timezone))
    if timing.is_edge(hours):
        notes.append(f"Timing: {hours.describe()} ({cfg.timezone}). Buy then, sell later.")
    return notes


def crafts(conn, server_id: int, profiles: dict[int, Profile], cfg: Config) -> list[Idea]:
    s, fee, ideas = cfg.strategy, cfg.sales_fee, []
    rows = conn.execute("SELECT * FROM crafts WHERE server_id=? AND cost > 0 AND market_price > 0",
                        (server_id,)).fetchall()
    for r in rows:
        if r["missing"]:
            continue  # a material without any price: the cost is incomplete
        net = r["market_price"] * (1 - fee) - r["cost"]
        roi = net / r["cost"]
        if roi < s.craft_min_roi:
            continue
        out = profiles.get(r["target_key"])
        known = out is not None and (not out.estimated or bool(out.listing_counts))
        per_day = out.per_day if known else 0
        reasons = [f"Craft cost {kina(r['cost'])} (buying every material: {kina(r['cost_market'])}); "
                   f"sells at {kina(r['market_price'])} → {kina(net)} after the {pct(fee, False)} fee."]
        consistency = 0.5  # unknown without the series
        cost_change = price_change = None
        detail = db.load_response(conn, server_id, *craft_request(r["target_key"]))
        if detail:
            points = [pt for pt in detail.get("series", {}).get("points", [])
                      if pt.get("cost") and pt.get("market_price")]
            if points:
                consistency = sum(pt["market_price"] * (1 - fee) > pt["cost"] for pt in points) / len(points)
                reasons.append(f"Profitable in {pct(consistency, False)} of the last 14 days.")
                times = [(parse_ts(pt["ts"]), pt) for pt in points]
                cost_change = window_change([(t, pt["cost"]) for t, pt in times], 3)
                price_change = window_change([(t, pt["market_price"]) for t, pt in times], 3)
            spend = defaultdict(lambda: [0.0, 0.0, set(), None])
            for m in recipe_materials(detail):
                entry = spend[m.get("name") or m["material_key"]]
                entry[0] += m.get("expected") or 0
                entry[1] += m.get("subtotal") or 0
                entry[3] = m.get("material_key")
                if m.get("method"):
                    entry[2].add(m["method"])
            top = sorted(spend.items(), key=lambda kv: kv[1][1], reverse=True)[:3]
            if top:
                reasons.append("Biggest costs: " + "; ".join(
                    f"{name} ×{qty:.0f} {kina(sub)}" + (f" ({'/'.join(sorted(how))})" if how else "")
                    for name, (qty, sub, how, _) in top) + ".")
            lead = material_lead(spend, profiles, r["cost"], cost_change, price_change)
            if lead:
                reasons.append(lead)
            elif price_change is not None and price_change <= -0.15:
                reasons.append(f"Caution: the sale price fell {pct(-price_change, False)} in 3 days while costs held; "
                               f"the margin is shrinking from the selling side.")
        reasons.append(f"Output: {out.demand()}; {r['listings']} listed." if known
                       else "Output demand unknown: check it sells before crafting many.")
        if r["carried"]:
            reasons.append(f"{r['carried']} material price(s) carried from an earlier poll (none listed now).")
        liquidity = min(1.0, per_day / max(s.min_per_day, 1e-9)) if known else 0.5
        ideas.append(Idea("craft", r["target_key"], r["name"] or str(r["target_key"]),
                          net * liquidity * consistency,
                          f"craft for {kina(r['cost'])}, sell @ {kina(r['market_price'])}: "
                          f"+{kina(net)} ({pct(roi)})",
                          reasons, {"cost": r["cost"], "market_price": r["market_price"], "net": net,
                                    "roi": roi, "consistency": consistency, "per_day": per_day,
                                    "cost_change_3d": cost_change, "price_change_3d": price_change,
                                    "entry": r["cost"], "target": r["market_price"]}))
    return sorted(ideas, key=lambda i: i.score, reverse=True)


def material_lead(spend: dict, profiles: dict[int, Profile], cost: float,
                  cost_change: float | None, price_change: float | None) -> str | None:
    """Materials move first and the crafted item's price follows later, if at all. When the cost of
    a craft moved 8%+ in 3 days but its sale price didn't keep up, say so and name the materials
    behind it (by their share of the cost times their own price change)."""
    if cost_change is None or price_change is None:
        return None
    if cost_change <= -0.08 and price_change - cost_change >= 0.05:
        verdict = "margin widening: craft now, before the sale price catches up"
    elif cost_change >= 0.08 and cost_change - price_change >= 0.05:
        verdict = "margin squeeze: buy materials soon or skip this craft"
    else:
        return None
    drivers = []
    for name, (_, subtotal, _, key) in spend.items():
        p = profiles.get(key)
        change = p.change(3) if p else None
        if change is not None and cost:
            drivers.append((subtotal / cost * change, name, change))
    drivers.sort(key=lambda d: abs(d[0]), reverse=True)
    named = ", ".join(f"{name} {pct(change)}" for _, name, change in drivers[:2] if abs(change) >= 0.03)
    return (f"Materials {'cheaper' if cost_change < 0 else 'dearer'}: cost {pct(cost_change)} in 3 days"
            + (f" ({named})" if named else "") + f" while the sale price moved {pct(price_change)}; {verdict}.")


def speculation(profiles: dict[int, Profile], cfg: Config) -> list[Idea]:
    s, fee, ideas = cfg.strategy, cfg.sales_fee, []
    for p in profiles.values():
        if not p.price or p.per_day < s.min_per_day or p.history_days < s.min_history_days:
            continue
        if (p.next_level_gap or 0) >= 0.15:
            continue  # one stray cheap listing, not a market move: that's a flip
        pos, g7, vol, demand = p.position, p.growth7, p.volatility, p.demand_trend
        avg7 = p.listings_avg7
        supply = p.listings / avg7 - 1 if avg7 and p.listings is not None else None
        patterns, reasons, upside = [], [], None
        lo, hi = p.range14
        # a steady slide is not a dip, however busy the item (listings taken rise as sellers undercut)
        falling_knife = g7 is not None and g7 <= -0.03
        # nor is noise in the first days at a new price level, when "the last 14 days" is only a few
        settled = p.shift_start is None or p.closes[-1][0] - p.shift_start >= timedelta(days=3)

        if pos is not None and pos <= s.dip_percentile and not falling_knife and settled and p.usual:
            upside = p.usual * (1 - fee) / p.price - 1
            if upside > 0:
                patterns.append("dip")
                reasons.append(f"Price {kina(p.price)} is in the bottom {pct(pos, False)} of the last 14 days "
                               f"(usually {kina(lo)}–{kina(hi)}); back to the 7-day median {kina(p.usual)} "
                               f"is {pct(upside)} after the fee.")
                if demand is not None:
                    what = "listings taken this week" if p.estimated else "28-day sales"
                    reasons.append(f"Demand {'holding' if demand > -0.1 else 'softening'}: {what} "
                                   f"{pct(demand)} on a week ago.")
        if g7 is not None and g7 >= s.momentum_per_day and settled and (supply is None or supply < 0) \
                and (demand is None or demand >= 0):
            patterns.append("uptrend")
            reasons.append(f"Rising {pct(g7)}/day over 7 days"
                           + (f" while listings fell {pct(supply)} vs their 7-day average" if supply is not None
                              else "") + ".")
        if supply is not None and supply <= s.squeeze_ratio - 1 and (pos is None or pos <= 0.6):
            patterns.append("squeeze")
            reasons.append(f"Supply drying up: {p.listings} listed vs ~{avg7:.0f} on average this week, "
                           f"and the price has not jumped yet.")
        if not patterns:
            continue
        if vol is not None:
            low = ("below its usual 14-day range" if lo is None or lo >= p.price * 0.995
                   else f"usual 14-day low {kina(lo)} ({pct(lo / p.price - 1)} from here)")
            reasons.append(f"Daily median moves about ±{pct(vol, False)} a day; {low}.")
        reasons.append(f"{p.demand().capitalize()}, so exiting is {'easy' if p.per_day >= 5 else 'slow'}.")
        reasons += context_notes(p, cfg)
        strength = max(upside or 0, (g7 or 0) * 7, -(supply or 0) * 0.3)
        score = strength * min(1.0, p.per_day / 5) / max(vol or 0.05, 0.05)
        # what counts as "worked" on the scorecard: back to the usual price for a dip, else +10%
        target = p.usual if "dip" in patterns else p.price * (1 + s.flip_min_roi)
        ideas.append(Idea("speculate", p.key, p.name, score,
                          f"{' + '.join(patterns)} @ {kina(p.price)}"
                          + (f", target {kina(p.usual)} ({pct(upside)})" if upside else ""),
                          reasons, {"patterns": patterns, "position": pos, "growth7": g7,
                                    "volatility": vol, "supply_vs_avg": supply, "demand_trend": demand,
                                    "entry": p.price, "target": target}))
    return sorted(ideas, key=lambda i: i.score, reverse=True)


def latest_server(conn) -> int | None:
    """The server the last collect resolved; before that was recorded, the one updated last
    (which ``compare`` breaks, as it updates the other servers after yours)."""
    home = conn.execute("SELECT value FROM meta WHERE key='home_server_id'").fetchone()
    if home:
        return int(home["value"])
    row = conn.execute("SELECT server_id FROM items ORDER BY updated_at DESC LIMIT 1").fetchone()
    return row["server_id"] if row else None


def analyze_all(conn, cfg: Config) -> tuple[int, dict[int, Profile], dict[str, list[Idea]]]:
    # a server given by name was resolved to its id by the last collect
    server_id = cfg.server if isinstance(cfg.server, int) else latest_server(conn)
    if server_id is None:
        raise SystemExit("no data yet: run `python -m aion2 collect` first")
    profiles = load_profiles(conn, server_id, cfg.strategy.shift_min_change)
    return server_id, profiles, {"flip": flips(profiles, cfg),
                                 "craft": crafts(conn, server_id, profiles, cfg),
                                 "speculate": speculation(profiles, cfg)}


def analyze(conn, cfg: Config) -> tuple[int, dict[str, list[Idea]]]:
    server_id, _, ideas = analyze_all(conn, cfg)
    return server_id, ideas


def shift_days(profiles: dict[int, Profile], min_items: int = 5) -> list[tuple[datetime, int]]:
    """Days on which many items changed price level at once: likely a patch or an event."""
    counts = defaultdict(int)
    for p in profiles.values():
        if p.closes and p.shift_start:
            counts[p.shift_start] += 1
    return sorted(((d, n) for d, n in counts.items() if n >= min_items), reverse=True)
