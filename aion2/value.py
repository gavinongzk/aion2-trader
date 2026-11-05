"""What an item is worth on your server, and the price to buy it at: a small valuation model.

Each server is its own economy, so the fair value is built from your server's prices. Two estimates,
each with an uncertainty (sigma, as a log-price standard deviation):

  history  your server's recent prices: the median of the cheapest listing over the last
           ``level_days``, each price weighted down by half every ``half_life_days``. Sigma is the
           day-to-day spread of the daily median over 14 days, widened by the gap between the recent
           level and the 14-day one (a sudden jump may not last). The backtest picked the short window:
           a 14-day level forecast worse than today's price (prices here move in steps that don't
           come back), while a 2-day level with a 6-hour half-life catches the dips that do.
  peers    relative value, like valuing a company from comparable ones. On the other servers an item
           trades at a fairly steady ratio to similar items (same category): a Greatsword at about
           1.3× a Longsword of the same set, say. That ratio times what the similar item costs on
           your server gives an implied price that uses only your server's price level. The
           ``peers`` most consistent ratios count, each weighted by how steady it is across servers
           and by how close the two items are in price (a peer of the same tier says more).

The fair value blends the two in log space, each weighted by its precision (1 / sigma²) and how much
data it has, with history counting ``home_weight`` times as much and the peers never more than
``max_peer_share``. The blend's sigma includes how far the two estimates disagree.

From the fair value:
  buy below   fair value less a margin of safety: ``margin``, or half a sigma if wider, and always
              enough that a resale at fair value clears the market fee plus 3%
  list at     the fair value, for a resale (the profit is shown after the market fee)
  rating      Strong buy / Buy below the buy price (Strong: 1.5+ sigma under fair value);
              Overpriced above fair value plus the margin; Fair in between; Wait while the price
              is still falling, as a falling price is usually cheaper later; Sell when it's
              Overpriced and trades daily (if you hold one, list just under the cheapest)

``backtest`` replays the history estimate on past days and checks it against the price
``horizon_days`` later: whether it forecasts better than today's price, and what its buy signals returned.
"""

import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from zoneinfo import ZoneInfo

from . import analysis, collect, economy, timing
from .analysis import Idea, Profile
from .config import Config
from .trades import Trades
from .stats import kina, parse_ts, pct, quantile, robust_sd, weighted_median

FALLING = -0.03    # falling 3%+/day over a week (and still falling): wait
DROPPING = -0.10   # without a week of history: down 10%+ in a day, wait too
STRONG_Z = -1.5    # this many sigmas under fair value: a strong buy
Z80 = 1.2816       # the 80% range is fair value × exp(±1.28 sigma)
MIN_SIGMA = {"history": 0.08, "peers": 0.05}  # the cheapest listing alone jumps that much
MAX_PEER_RATIO = 4.0  # a peer more than 4× dearer or cheaper is another tier, not a comparable
MIN_SALES = 3         # sales in the window before their prices give a "recently sold at"
NO_SALES_SIGMA = 0.15 # no sale in the window: the asks are unproven, widen the range by this much
TONES = {"Strong buy": "good", "Buy": "good", "Fair": "ok", "Wait": "warn", "Overpriced": "bad", "Sell": "sell"}
SELL_MIN_PER_DAY = 1.0  # Sell needs an item that trades daily: on thin items a withdrawn troll ask looks like a sale
SELL_MAX_RATIO = 2.0    # ...and an ask under 2× fair value: past that the value itself is in doubt
UNDERCUT = 0.97         # a Sell lists this far under the cheapest listing


@dataclass
class Estimate:
    source: str        # "history" or "peers"
    price: float
    sigma: float       # uncertainty of log(price)
    reliability: float # 0..1: how much data stands behind it
    basis: str = ""    # history: "sales" (some sold), "no sales", "expired" (capped by an unsold ask), "asks" (not checked)
    sales: int = 0     # history: sales seen in its window
    expired: int = 0   # history: cheapest listings that expired unsold since the last sale
    sold_at: float | None = None  # history: the level of the sale prices, with MIN_SALES of them

    def as_dict(self, weight: float) -> dict:
        return {"source": self.source, "price": self.price, "low": self.price * math.exp(-Z80 * self.sigma),
                "high": self.price * math.exp(Z80 * self.sigma), "sigma": self.sigma, "weight": weight,
                "basis": self.basis or None, "sales": self.sales, "expired": self.expired, "sold_at": self.sold_at}


# --- history ---------------------------------------------------------------------------------------

def snapshot_history(conn, server_id: int, key: int) -> tuple[list, list]:
    """(time, price) and (time, listings) from our own hourly snapshots of the item list."""
    rows = conn.execute("""SELECT captured_at, price, listings FROM item_snapshots
                           WHERE server_id=? AND item_key=? ORDER BY captured_at""", (server_id, key)).fetchall()
    return ([(parse_ts(r["captured_at"]), r["price"]) for r in rows if r["price"]],
            [(parse_ts(r["captured_at"]), r["listings"]) for r in rows])


def load(conn, server_id: int, cfg: Config) -> dict[int, Profile]:
    """Every item of the server with a price history up to now: the fetched series (only
    refreshed while the item is on the collector's shortlist), then our snapshots since it ends."""
    profiles = analysis.load_profiles(conn, server_id, cfg.strategy.shift_min_change)
    for key, p in profiles.items():
        closes, counts = snapshot_history(conn, server_id, key)
        if p.closes:
            end = p.closes[-1][0]
            closes, counts = [c for c in closes if c[0] > end], [c for c in counts if c[0] > end]
        p.closes += closes
        p.listing_counts += counts
    return profiles


def history_estimate(closes: list, half_life: float = 0.25, days: float = 2, at: datetime | None = None,
                     sigma_days: float = 14, sold: Trades | None = None) -> Estimate | None:
    """The recency-weighted median of the prices in the ``days`` up to ``at`` (default: the last
    one), with the spread of the daily median over ``sigma_days`` as its sigma.

    With ``sold`` (from ``trades.infer``), asks nobody paid count for less: a cheapest listing that
    expired unsold since the last sale caps the level, and with no sale in the window at all the
    sigma widens. (Valuing from the sale prices themselves did worse in the backtest: sales lag a dip,
    so the value stays high just as the price falls.) ``sold_at`` is the sale prices' level: what a
    resale actually fetched lately."""
    if not closes:
        return None
    end = at or closes[-1][0]
    start = end - timedelta(days=days)

    def level_of(points):
        return weighted_median([v for _, v in points], [0.5 ** ((end - t).total_seconds() / 86400 / half_life)
                                                        for t, _ in points])

    recent = [(t, v) for t, v in closes if start <= t <= end and v]
    if not recent:
        return None
    level, basis, sales, expired, sold_at = level_of(recent), "asks", 0, 0, None
    if sold is not None:
        window = sold.since(start, end)
        sales = len(window.sales)
        basis = "sales" if sales else "no sales"
        if sales >= MIN_SALES:
            sold_at = level_of(window.sales)
        last_sale = window.sales[-1][0] if window.sales else start
        unsold = [v for t, v in window.expired if t > last_sale]
        expired = len(unsold)
        if unsold and min(unsold) < level:
            level, basis = min(unsold), "expired"
    by_day = defaultdict(list)
    for t, v in closes:
        if end - timedelta(days=sigma_days) <= t <= end and v:
            by_day[t.date()].append(v)
    daily = [math.log(statistics.median(v)) for _, v in sorted(by_day.items())]
    # with under 3 days there's no day-to-day spread to measure: assume a wide one
    sigma = max(MIN_SIGMA["history"], robust_sd(daily)) if len(daily) >= 3 else 0.25
    if len(daily) >= 3:
        # a recent level far from the longer one may not last: widen by the gap between them
        sigma = math.hypot(sigma, math.log(level) - statistics.median(daily))
    if basis == "no sales":
        sigma = math.hypot(sigma, NO_SALES_SIGMA)  # nobody has paid these asks: they may be too high
    return Estimate("history", level, sigma, min(1.0, max(0.1, len(daily) / 7)), basis, sales, expired, sold_at)


def _history(p: Profile, cfg: Config, at: datetime | None = None) -> Estimate | None:
    return history_estimate(p.closes, cfg.value.half_life_days, cfg.value.level_days, at,
                            sold=p.trades if cfg.value.use_sales else None)


# --- peers -----------------------------------------------------------------------------------------

def peer_estimate(key: int, meta: dict[int, dict], prices: dict[int, dict[int, dict]], home_id: int,
                  levels: dict[int, float], cfg: Config) -> tuple[Estimate | None, list[dict]]:
    """The price implied by similar items: their level on the home server times the item's usual
    ratio to them on the other servers. ``prices`` is {server: {item: {"price": ...}}} (24h medians),
    ``levels`` the home server's price level of each item."""
    others = [p for sid, p in prices.items() if sid != home_id and key in p]
    if len(others) < cfg.value.min_common_servers:
        return None, []
    me = meta.get(key, {})

    def same(field):
        return [k for k in levels if k != key and me.get(field) and meta.get(k, {}).get(field) == me.get(field)]

    pool = same("category")
    if len(pool) < 3:  # too few in the category: widen to its section
        pool = list(dict.fromkeys(pool + same("section")))
    peers = []
    for j in pool:
        logs = [math.log(p[key]["price"] / p[j]["price"]) for p in others if j in p]
        if len(logs) < cfg.value.min_common_servers:
            continue
        ratio, spread = statistics.median(logs), max(0.02, robust_sd(logs))
        if abs(ratio) > math.log(MAX_PEER_RATIO):
            continue
        peers.append({"key": j, "name": meta[j].get("name"), "ratio": math.exp(ratio), "home_level": levels[j],
                      "implied": levels[j] * math.exp(ratio), "servers": len(logs), "spread": spread,
                      "weight": len(logs) / spread ** 2 / (1 + abs(ratio))})
    peers = sorted(peers, key=lambda x: -x["weight"])[: cfg.value.peers]
    if not peers:
        return None, []
    logs, weights = [math.log(x["implied"]) for x in peers], [x["weight"] for x in peers]
    center, total = weighted_median(logs, weights), sum(weights)
    # each peer's own spread across servers, plus how far the peers disagree with each other
    var = sum(w * (x["spread"] ** 2 + (l - center) ** 2) for x, l, w in zip(peers, logs, weights)) / total
    for x in peers:
        x["weight"] /= total
    return Estimate("peers", math.exp(center), max(MIN_SIGMA["peers"], math.sqrt(var)), min(1.0, len(peers) / 3)), peers


# --- blend and verdict ----------------------------------------------------------------------------

def blend(estimates: list[Estimate], home_weight: float, max_peer_share: float = 1.0) -> tuple[float, float, list[float]]:
    """(fair value, sigma, each estimate's share of the weight): a precision-weighted mean of the
    log prices, whose sigma also counts the disagreement between estimates. With history present,
    the peers' share is capped at ``max_peer_share``: each server is its own economy, and the peer
    estimate can't be backtested yet."""
    raw = [(home_weight if e.source == "history" else 1.0) * e.reliability / e.sigma ** 2 for e in estimates]
    total = sum(raw)
    shares = [w / total for w in raw]
    peer = next((i for i, e in enumerate(estimates) if e.source == "peers"), None)
    if peer is not None and len(estimates) > 1 and shares[peer] > max_peer_share:
        shares = [max_peer_share if i == peer else (1 - max_peer_share) for i in range(len(estimates))]
    center = sum(s * math.log(e.price) for s, e in zip(shares, estimates))
    var = sum(s * (e.sigma ** 2 + (math.log(e.price) - center) ** 2) for s, e in zip(shares, estimates))
    return math.exp(center), math.sqrt(var), shares


MIN_RESALE_PROFIT = 0.03  # bought at the buy price and resold at fair value, this much is left after the fee


def margin_for(sigma: float, cfg: Config) -> float:
    """The margin of safety: ``margin``, half a sigma when the value is that uncertain, and never so
    thin that a resale at fair value fails to clear the fee plus ``MIN_RESALE_PROFIT``."""
    covers_fee = 1 - (1 - cfg.sales_fee) / (1 + MIN_RESALE_PROFIT)
    return max(cfg.value.margin, sigma / 2, covers_fee)


def below_sales(now: float, hist: Estimate, margin: float) -> bool:
    """A buy also has to be cheap against what recently sold, when enough did: an item whose asks sit
    well above its sale prices isn't a bargain at the sale price. (In the backtest this lifted the
    median buy from +5.5% to +7.1% after a 12% fee, with a sixth fewer signals.)"""
    return hist.sold_at is None or now <= hist.sold_at * (1 - margin)


def recommend(now: float, fair: float, sigma: float, cfg: Config) -> dict:
    """Prices and the rating before timing: what to pay, where to sell, how far off now is."""
    margin = margin_for(sigma, cfg)
    buy_below = fair * (1 - margin)
    z = math.log(now / fair) / sigma if sigma else 0.0
    if now <= buy_below:
        label = "Strong buy" if z <= STRONG_Z else "Buy"
    elif now >= fair * (1 + margin):
        label = "Overpriced"
    else:
        label = "Fair"
    return {"fair": fair, "low": fair * math.exp(-Z80 * sigma), "high": fair * math.exp(Z80 * sigma),
            "sigma": sigma, "margin": margin, "buy_below": buy_below, "list_at": fair, "z": z,
            "upside": fair / now - 1, "resale_roi": (fair * (1 - cfg.sales_fee) - now) / now, "label": label}


def assess(p: Profile, hist: Estimate | None, peers_est: Estimate | None, peers: list[dict], cfg: Config,
           home_name: str = "your server", section: tuple[str, float | None] | None = None) -> dict:
    """The valuation of ``p`` on its server and the rating of buying it at today's cheapest price."""
    now = p.price
    growth = p.growth7 if p.history_days >= 4 else None
    day_change = p.change(1) if growth is None else None
    # a week's fall only counts while it goes on: flat for two days after a crash is a new floor
    falling = growth is not None and growth <= FALLING and (p.change(2) or 0) < -0.02
    # without sales statistics, demand needs a day of snapshots; before that it's unknown, not zero
    per_day = None if p.estimated and p.listings_taken_per_day() is None else p.per_day
    section_name, trend = section or (None, None)
    out = {"now": now, "growth": growth, "section_trend": trend, "per_day": None if per_day is None else round(per_day, 2),
           "listings": p.listings, "estimates": [], "peers": [],
           "history": [(t.date().isoformat(), round(v, 2)) for t, v in p._daily(14, since_shift=False)]}
    estimates = [e for e in (hist, peers_est) if e]
    if not estimates:
        return out | {"label": "Unknown", "tone": "none", "reasons": ["No price history and no comparable items."]}

    fair, sigma, shares = blend(estimates, cfg.value.home_weight, cfg.value.max_peer_share)
    out["estimates"] = [e.as_dict(s) for e, s in zip(estimates, shares)]
    out["peers"] = [{k: x[k] for k in ("key", "name", "ratio", "home_level", "implied", "servers", "spread", "weight")}
                    for x in peers[:5]]
    if not now:
        rec = recommend(fair, fair, sigma, cfg)
        return out | rec | {"label": "Not listed", "tone": "none", "upside": None, "z": None, "resale_roi": None,
                            "reasons": [f"Nobody is selling it on {home_name} now. Fair value {kina(fair)}: "
                                        f"buy at {kina(rec['buy_below'])} or less when it's listed."]}

    rec = recommend(now, fair, sigma, cfg)
    z = rec["z"]
    where = (f"{abs(z):.1f} sigma {'under' if z < 0 else 'over'}" if abs(z) <= 3
             else f"far {'under' if z < 0 else 'over'} its normal range")
    reasons = [f"Fair value {kina(fair)} (80% range {kina(rec['low'])}–{kina(rec['high'])}); "
               f"now {pct(now / fair - 1)}, {where}."]
    for e, share in zip(estimates, shares):
        if e.source == "history":
            reasons.append(f"{home_name}'s own prices say {kina(e.price)} ({pct(share, False)} of the weight).")
        else:
            top = peers[0]
            reasons.append(f"Similar items say {kina(e.price)} ({pct(share, False)} of the weight): elsewhere it "
                           f"costs {top['ratio']:.2f}× {top['name']}, which is {kina(top['home_level'])} on {home_name}.")
    if not hist:
        reasons.append(f"No price history on {home_name} yet: valued from similar items only.")
    elif hist.basis == "no sales":
        reasons.append(f"No sales seen in {cfg.value.level_days:g} days: these are asks nobody has paid yet, "
                       f"so the range is wider.")
    elif hist.basis == "expired":
        reasons.append(f"A listing at {kina(hist.price)} expired unsold: the value is capped there.")
    # what a resale fetches: the recent sale prices when they sit below the fair value
    if hist and hist.sold_at and hist.sold_at < rec["list_at"]:
        rec["list_at"] = hist.sold_at
        rec["resale_roi"] = (hist.sold_at * (1 - cfg.sales_fee) - now) / now
        if not below_sales(now, hist, rec["margin"]) and rec["label"] in ("Strong buy", "Buy"):
            rec["label"] = "Fair"
            reasons.append(f"Recent sales went for about {kina(hist.sold_at)}: today's price is the going rate, "
                           f"not a bargain. The dearer asks aren't selling.")
        elif hist.sold_at < fair * 0.95:
            reasons.append(f"Recent sales went for about {kina(hist.sold_at)}, below the asks: expect to resell nearer that.")
    if hist and peers_est and abs(math.log(hist.price / peers_est.price)) > max(math.log(2), 2 * peers_est.sigma):
        side = "below" if peers_est.price < hist.price else "above"
        reasons.append(f"The two disagree: similar items put it well {side} {home_name}'s own level. Check before a big buy.")
    # a strong buy needs the relative value to agree that it's cheap, when there is one
    if rec["label"] == "Strong buy" and peers_est and now > peers_est.price * (1 - rec["margin"]):
        rec["label"] = "Buy"

    label = rec["label"]
    if label in ("Strong buy", "Buy", "Fair") and (falling or (day_change is not None and day_change <= DROPPING)):
        label = "Wait"
        drop = f"down {pct(-day_change, False)} in a day" if growth is None else f"falling {pct(-growth, False)}/day"
        reasons.insert(0, f"Price {drop}: likely cheaper in a few days; buy below {kina(rec['buy_below'])} once it settles.")
    elif label in ("Strong buy", "Buy"):
        reasons.append(f"Buy at {kina(rec['buy_below'])} or less (a {pct(rec['margin'], False)} margin of safety).")
    elif label == "Overpriced" and sellable(rec["z"], now / fair, per_day, hist):
        # the mirror of a buy: overpriced to buy is the time to sell, for an item that trades
        label = "Sell"
        rec["list_at"] = now * UNDERCUT
        reasons.insert(0, f"If you hold one, sell: list just under the cheapest, at {kina(rec['list_at'])}. In the "
                          f"backtest, doing that on items that trade daily beat holding 3 days twice as often as it "
                          f"lost (40% vs 20%); the rest of the time it didn't sell and you'd sell later anyway.")
        reasons.append(f"To buy, wait for a listing at {kina(rec['buy_below'])} or less.")
    elif label == "Overpriced":
        reasons.append(f"Wait for a listing at {kina(rec['buy_below'])} or less.")
    if trend is not None and abs(trend) >= 0.05:
        reasons.append(f"Its section ({section_name}) is {'up' if trend > 0 else 'down'} {pct(abs(trend), False)} this week.")
    if growth is not None and abs(growth) >= 0.01 and label != "Wait":
        settled = " (flat the last 2 days)" if growth < 0 and not falling else ""
        reasons.append(f"Price {'rising' if growth > 0 else 'falling'} {pct(abs(growth), False)}/day over the week{settled}.")
    if per_day is not None and per_day < cfg.strategy.min_per_day:
        if label in ("Strong buy", "Buy"):
            reasons.append(f"Trades slowly ({p.demand()}): in the backtest, cheap buys of slow sellers mostly lost "
                           f"money on resale. Buy it to use, not to flip.")
        else:
            reasons.append(f"Trades slowly ({p.demand()}): fine to use, hard to resell.")
    elif label in ("Strong buy", "Buy") and rec["resale_roi"] > 0:
        reasons.append(f"Resell at {kina(rec['list_at'])}: {pct(rec['resale_roi'])} after the {pct(cfg.sales_fee, False)} fee.")
    return out | rec | {"label": label, "tone": TONES[label], "reasons": reasons}


def value_all(conn, home_id: int, prices: dict[int, dict[int, dict]], cfg: Config,
              home_name: str = "your server") -> tuple[dict[int, dict], dict[int, Profile]]:
    """The valuation of every item with a price history on the home server, or comparable items."""
    profiles = load(conn, home_id, cfg)
    hist = {k: _history(p, cfg) for k, p in profiles.items()}
    # a peer's price level should be steady: a week, not the 2 days that catch dips
    steady = {k: history_estimate(p.closes, half_life=1, days=7) for k, p in profiles.items()}
    levels = {k: e.price for k, e in steady.items() if e}
    meta = {k: {"name": v["name"], "category": v["category"], "section": v["section"]}
            for p in prices.values() for k, v in p.items()}
    for k, p in profiles.items():
        meta.setdefault(k, {"name": p.name})
    sections = {k: m.get("section") for k, m in meta.items()} | home_sections(conn, home_id)
    econ = economy.build(profiles, sections, cfg.sales_fee, tz=ZoneInfo(cfg.timezone))
    costs = craft_costs(conn, home_id, profiles)
    out = {}
    for k, p in profiles.items():
        peers_est, peers = peer_estimate(k, meta, prices, home_id, levels, cfg)
        if not hist[k] and not peers_est:
            continue
        out[k] = ({"key": k, "name": p.name, "category": meta[k].get("category"), "section": meta[k].get("section")}
                  | assess(p, hist[k], peers_est, peers, cfg, home_name,
                           (sections.get(k), economy.section_trend(econ, sections.get(k)))))
        add_context(out[k], p, cfg, costs.get(k))
    return out, profiles, econ, sections


# --- context: facts that don't change the rating (each was tested; see the README) -------------

CRAFT_FLOOR = 0.9  # under 90% of its craft cost: crafters stop making it
CRAFT_PAYS = 1.2   # over 120%: crafting it pays, more will be made


def craft_costs(conn, server_id: int, profiles: dict[int, Profile], at: datetime | None = None) -> dict[int, float]:
    """What each tracked craft costs to make (at ``at``, default now): each material's expected
    quantity × its price, the market's 2-day level where it's bought there, else its listed price."""
    out = {}
    for r in conn.execute("SELECT path, body FROM responses WHERE server_id=? AND path LIKE '/crafts/%'", (server_id,)):
        detail = json.loads(r["body"])
        total = 0.0
        for m in collect.recipe_materials(detail):
            price = None
            if m.get("method") == "buy" and m.get("material_key") in profiles:
                est = history_estimate(profiles[m["material_key"]].closes, half_life=1, days=2, at=at)
                price = est.price if est else None
            total += (m.get("expected") or 0) * (price or m.get("unit_price") or 0)
        if total and detail.get("target_key"):
            out[detail["target_key"]] = total
    return out


def fill_rates(p: Profile, cfg: Config, days: int = 14) -> dict | None:
    """How often a listing at the going rate (what sold lately, else the fair value) found a buyer:
    on each of the ``days`` days that have 3 days after them, whether a sale at 97%+ of that price
    came within 1 and within 3 days. In the backtest this didn't predict which buys paid (slow fills
    did no worse), so it's resale information, not part of the rating."""
    if not p.closes:
        return None
    end = p.closes[-1][0] - timedelta(days=3)
    one = three = n = 0
    for i in range(days):
        day = end - timedelta(days=i)
        est = _history(p, cfg, at=day)
        if not est:
            continue
        price = (est.sold_at or est.price) * 0.97
        later = [t for t, v in p.trades.sales if day < t <= day + timedelta(days=3) and v >= price]
        n += 1
        one += any(t <= day + timedelta(days=1) for t in later)
        three += bool(later)
    return {"fill_1d": one / n, "fill_3d": three / n, "fill_days": n} if n >= 5 else None


def add_context(v: dict, p: Profile, cfg: Config, craft_cost: float | None) -> None:
    """Add the timing, resale and craft-cost facts to valuation ``v`` (fields and reasons)."""
    reasons = v.setdefault("reasons", [])
    hours = timing.hourly(p.closes, ZoneInfo(cfg.timezone))
    if timing.is_edge(hours):
        # 6 of the 7 items with a pattern in the first half of the data kept it in the second
        v["cheap_hour"], v["dear_hour"] = hours.cheap, hours.dear
        reasons.append(f"Timing: {hours.describe()}.")
    fills = fill_rates(p, cfg)
    if fills:
        v |= fills
        reasons.append(f"Listed at the going rate, it found a buyer within a day {pct(fills['fill_1d'], False)} and "
                       f"within 3 days {pct(fills['fill_3d'], False)} of the time over the last {fills['fill_days']} days.")
    if craft_cost and v.get("now"):
        v["craft_cost"] = craft_cost
        ratio = v["now"] / craft_cost
        if ratio < CRAFT_FLOOR:
            reasons.insert(1, f"Below its craft cost ({kina(craft_cost)}, {pct(ratio - 1)}): crafters stop making it at "
                              f"this price. In the backtest every craft that went 10%+ under cost rose within 3 days "
                              f"(median +32%), but that's 16 cases from 5 crafts: early evidence.")
        elif ratio > CRAFT_PAYS:
            reasons.append(f"Crafting it pays: it costs {kina(craft_cost)} to make and sells for {pct(ratio - 1)} more. "
                           f"Expect more to be made (in the backtest the price drifted down, about 1% over 3 days).")
        else:
            reasons.append(f"It costs about {kina(craft_cost)} to craft, close to the price.")


def home_sections(conn, server_id: int) -> dict[int, str]:
    return {r["item_key"]: r["section_id"] for r in conn.execute(
        "SELECT item_key, section_id FROM items WHERE server_id=? AND section_id IS NOT NULL", (server_id,))}


def ideas(valuations: list[dict], min_per_day: float = 0.5) -> list[Idea]:
    """The buy ratings as scorecard calls, most upside first: bought at today's price, a hit when the
    price reaches the fair value. The metrics keep what the call was made from (the peers' share of
    the weight, whether the estimates disagreed), so the scorecard can later say which part works.
    Slow sellers (under ``min_per_day``) are scored apart, as "buy+slow": the backtest says they lose."""
    buys = sorted((v for v in valuations if v["label"] in ("Strong buy", "Buy")), key=lambda v: -v["upside"])

    def slow(v):
        return v.get("per_day") is not None and v["per_day"] < min_per_day

    out = []
    for v in buys:
        peer_share = next((e["weight"] for e in v["estimates"] if e["source"] == "peers"), 0.0)
        out.append(Idea("value", v["key"], v["name"], v["upside"],
                        f"{v['label']}: {kina(v['now'])}, fair value {kina(v['fair'])}", v["reasons"],
                        {"entry": v["now"], "target": v["fair"],
                         "patterns": [v["label"].lower()] + (["slow"] if slow(v) else []),
                         "buy_below": v["buy_below"], "sigma": v["sigma"], "z": v["z"], "peer_share": peer_share,
                         "disagree": any("disagree" in r for r in v["reasons"]),
                         "section_trend": v.get("section_trend")}))
    # under its craft cost but not a buy: scored apart, to see whether the craft floor holds
    for v in valuations:
        cost = v.get("craft_cost")
        if cost and v.get("now") and v["now"] < cost * CRAFT_FLOOR and v["label"] not in ("Strong buy", "Buy"):
            out.append(Idea("value", v["key"], v["name"], cost / v["now"] - 1,
                            f"Under craft cost: {kina(v['now'])}, costs {kina(cost)} to make", v["reasons"],
                            {"entry": v["now"], "target": cost, "patterns": ["below cost"], "craft_cost": cost,
                             "section_trend": v.get("section_trend")}))
    return out


# --- backtest -------------------------------------------------------------------------------------

def backtest(profiles: dict[int, Profile], cfg: Config, sections: dict[int, str] | None = None) -> dict:
    """Replay the history estimate once a day on the past: at each day, the fair value from the
    prices up to then against the median price over the next ``horizon_days``. Peers can't be
    replayed until the other servers have history of their own (``compare`` stores it each run).

    A buy is resold at the median price of the sales seen over the horizon; with no sale in it, at
    the lowest ask (you'd have to undercut everyone). ``*_asks`` is the old, kinder assumption:
    resold at the median ask, whether or not anyone paid it."""
    horizon = timedelta(days=cfg.value.horizon_days)
    # the whole history, so every replayed day has a section trend (the live one covers 3 weeks)
    econ = economy.build(profiles, sections, cfg.sales_fee, window_days=10_000) if sections else {}
    falling_section = []
    errors_fair, errors_now, buys, buys_asks, everyone, unsold, items = [], [], [], [], [], 0, 0
    sells = []  # (vs holding: +0.1 = got 10% more, whether the listing sold)
    for p in profiles.values():
        closes = p.closes
        if len(closes) < 24 or closes[-1][0] - closes[0][0] < timedelta(days=5) + horizon:
            continue
        items += 1
        day = closes[0][0] + timedelta(days=4)
        while day + horizon <= closes[-1][0]:
            est = _history(p, cfg, at=day)
            now = next((v for t, v in reversed(closes) if t <= day), None)
            future = [v for t, v in closes if day < t <= day + horizon]
            if est and now and len(future) >= 3:
                later = statistics.median(future)
                errors_fair.append(abs(math.log(later / est.price)))
                errors_now.append(abs(math.log(later / now)))
                sales = [v for t, v in p.trades.sales if day < t <= day + horizon]
                resale = statistics.median(sales) if sales else min(future)
                ret = resale * (1 - cfg.sales_fee) / now - 1  # bought now, sold at what sold later
                everyone.append(ret)
                margin = margin_for(est.sigma, cfg)
                if now <= est.price * (1 - margin) and below_sales(now, est, margin):
                    buys.append(ret)
                    trend = economy.section_trend(econ, sections.get(p.key), day.date()) if econ else None
                    if trend is not None and trend < 0:
                        falling_section.append(ret)
                    buys_asks.append(later * (1 - cfg.sales_fee) / now - 1)
                    unsold += not sales
                if now >= est.price * (1 + margin) and sellable(math.log(now / est.price) / est.sigma, now / est.price, p.per_day, est):
                    sell = _sell_outcome(p, day, now * UNDERCUT, horizon)
                    if sell:
                        sells.append(sell)
            day += timedelta(days=1)
    if not errors_fair:
        return {"evaluations": 0, "horizon_days": cfg.value.horizon_days}
    return {
        "items": items, "evaluations": len(errors_fair), "horizon_days": cfg.value.horizon_days,
        "error_fair": statistics.median(errors_fair), "error_now": statistics.median(errors_now),
        "fair_closer": sum(f < n for f, n in zip(errors_fair, errors_now)) / len(errors_fair),
        "buy_signals": len(buys),
        "buy_return": statistics.median(buys) if buys else None,
        "buy_win_rate": sum(r > 0 for r in buys) / len(buys) if buys else None,
        "buy_return_p25": quantile(buys, 0.25) if buys else None,
        "buy_return_asks": statistics.median(buys_asks) if buys_asks else None,
        "buy_unsold": unsold / len(buys) if buys else None,
        # the buys made while their section's index was falling over the week: not used in the
        # ratings (too few yet), tracked to see whether it becomes a signal
        "buy_falling_section": len(falling_section),
        "buy_falling_section_return": statistics.median(falling_section) if falling_section else None,
        "all_return": statistics.median(everyone),
        "sell_signals": len(sells),
        "sell_better": sum(g > 0 for g, _ in sells) / len(sells) if sells else None,
        "sell_worse": sum(g < 0 for g, _ in sells) / len(sells) if sells else None,
        "sell_sold": sum(s for _, s in sells) / len(sells) if sells else None,
        "sell_gain_when_sold": statistics.median([g for g, s in sells if s] or [0]) if sells else None,
    }


def sellable(z: float | None, ratio: float | None, per_day: float | None, hist: Estimate | None) -> bool:
    """An Overpriced item worth selling into: it trades daily, something sold in the last 2 days,
    and the cheapest ask is under 1.5 sigma (and 2×) over fair value. Further over, listings just under it
    mostly didn't sell (36%): those are asks nobody pays, and listing next to them isn't selling."""
    return (z is not None and z < -STRONG_Z and ratio is not None and ratio <= SELL_MAX_RATIO
            and per_day is not None and per_day >= SELL_MIN_PER_DAY and hist is not None and hist.basis != "no sales")


def _sell_outcome(p: Profile, day: datetime, price: float, horizon: timedelta) -> tuple[float, bool] | None:
    """A Sell listed at ``price`` on ``day`` against holding: it sold if a sale at that price or more
    came within ``horizon`` (buyers take the cheapest first, and this was under it); holding sells at
    the median sale of the horizon after that (no sale: the lowest ask). Unsold, you sell later
    anyway: a tie. (gain vs holding, sold)"""
    sold = any(day < t <= day + horizon and v >= price for t, v in p.trades.sales)
    after = [v for t, v in p.trades.sales if day + horizon < t <= day + 2 * horizon]
    asks = [v for t, v in p.closes if day + horizon < t <= day + 2 * horizon]
    if not asks:
        return None
    hold = statistics.median(after) if after else min(asks)
    return (price / hold - 1 if sold else 0.0), sold
