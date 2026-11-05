"""When an item is cheap or dear: by hour of day and by day of week, in the players' time zone.

Each hourly price is divided by the median of the 24 hours around it, so a trend doesn't pass for
a time-of-day pattern; the ratios are then grouped by local hour (or weekday). A pattern only counts
when it is big enough and repeats on most days.
"""

import statistics
from collections import defaultdict
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from .stats import pct, rolling_median_ratio

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass
class Pattern:
    """The cheapest and dearest slot (an hour 0-23 or a weekday 0-6) against the local level."""
    kind: str             # "hour" or "weekday"
    cheap: int
    cheap_ratio: float    # 0.95 = 5% under the local level
    cheap_share: float    # share of days (or weeks) on which that slot was under the level
    dear: int
    dear_ratio: float
    dear_share: float
    samples: int          # days (or weeks) of data

    @property
    def swing(self) -> float:
        return self.dear_ratio / self.cheap_ratio - 1

    def label(self, slot: int) -> str:
        return f"{slot:02d}:00" if self.kind == "hour" else WEEKDAYS[slot]

    def describe(self) -> str:
        return (f"cheapest around {self.label(self.cheap)} ({pct(self.cheap_ratio - 1)}, on "
                f"{pct(self.cheap_share, False)} of {'days' if self.kind == 'hour' else 'weeks'}), dearest around "
                f"{self.label(self.dear)} ({pct(self.dear_ratio - 1)}): a {pct(self.swing, False)} swing")


def _pattern(kind: str, by_slot: dict[int, list[tuple[object, float]]], samples: int) -> Pattern | None:
    medians = {slot: statistics.median(r for _, r in values) for slot, values in by_slot.items() if len(values) >= 2}
    if len(medians) < 2:
        return None
    cheap = min(medians, key=medians.get)
    dear = max(medians, key=medians.get)
    cheap_share = sum(r < 1 for _, r in by_slot[cheap]) / len(by_slot[cheap])
    dear_share = sum(r > 1 for _, r in by_slot[dear]) / len(by_slot[dear])
    return Pattern(kind, cheap, medians[cheap], cheap_share, dear, medians[dear], dear_share, samples)


def hourly(closes: list, tz: ZoneInfo, min_days: int = 5) -> Pattern | None:
    """Hour of day; needs ``min_days`` days of hourly prices."""
    ratios = rolling_median_ratio(closes, 24)
    by_hour = defaultdict(list)
    days = set()
    for t, r in ratios:
        local = t.astimezone(tz)
        by_hour[local.hour].append((local.date(), r))
        days.add(local.date())
    return _pattern("hour", by_hour, len(days)) if len(days) >= min_days else None


def weekly(closes: list, tz: ZoneInfo, min_weeks: int = 3) -> Pattern | None:
    """Day of week, from daily medians against the week around them; needs ``min_weeks`` of each day."""
    by_date = defaultdict(list)
    for t, p in closes:
        by_date[t.astimezone(tz).date()].append(p)
    daily = sorted((d, statistics.median(ps)) for d, ps in by_date.items() if len(ps) >= 12)
    if len(daily) < 7 * min_weeks:
        return None
    by_weekday = defaultdict(list)
    for i, (d, p) in enumerate(daily):
        window = [q for _, q in daily[max(0, i - 3):i + 4]]
        if len(window) >= 5:
            by_weekday[d.weekday()].append((d, p / statistics.median(window)))
    if min((len(v) for v in by_weekday.values()), default=0) < min_weeks:
        return None
    return _pattern("weekday", by_weekday, len(daily) // 7)


def is_edge(p: Pattern | None, min_swing: float = 0.05, min_share: float = 0.6) -> bool:
    """A pattern worth acting on: a swing of 5%+ that held on most days at both ends."""
    return p is not None and p.swing >= min_swing and p.cheap_share >= min_share and p.dear_share >= min_share


def highlights(profiles, tz: ZoneInfo, limit: int = 10) -> list[tuple[object, Pattern]]:
    """The items with the strongest hour-of-day edge (then weekday), strongest first."""
    found = []
    for p in profiles:
        if len(p.closes) < 24 * 5:
            continue
        for pattern in (hourly(p.closes, tz), weekly(p.closes, tz)):
            if is_edge(pattern):
                found.append((p, pattern))
    found.sort(key=lambda f: f[1].swing * min(f[1].cheap_share, f[1].dear_share), reverse=True)
    return found[:limit]


def market_summary(hours: dict[int, float]) -> str:
    if len(hours) < 12:
        return "Not enough history yet for a market-wide hour-of-day view."
    cheap, dear = min(hours, key=hours.get), max(hours, key=hours.get)
    spread = hours[dear] / hours[cheap] - 1
    if spread < 0.02:
        return (f"Market-wide, no hour of day stands out (all within {pct(spread, False)}): "
                f"timing only matters item by item.")
    return (f"Market-wide, prices run lowest around {cheap:02d}:00 and highest around {dear:02d}:00 "
            f"({pct(spread, False)} apart).")


def market_hours(profiles, tz: ZoneInfo) -> dict[int, float]:
    """The average ratio to the local level by hour across all items with history: when the market
    as a whole is cheapest. A mean, as most items' cheapest price sits still for hours (a median
    would be exactly 1), with ratios clipped to 0.5-2 so a troll listing can't dominate; each item
    counts once per hour."""
    by_hour = defaultdict(list)
    for p in profiles:
        if len(p.closes) < 24 * 5:
            continue
        per_hour = defaultdict(list)
        for t, r in rolling_median_ratio(p.closes, 24):
            per_hour[t.astimezone(tz).hour].append(min(2.0, max(0.5, r)))
        for hour, rs in per_hour.items():
            by_hour[hour].append(statistics.fmean(rs))
    return {h: statistics.fmean(rs) for h, rs in sorted(by_hour.items()) if len(rs) >= 5}
