"""The server's economy as a whole: its price level, its sections' price levels, and the Kina
spent on the market each day.

The API has no Kina balances, so the money supply can't be measured directly. What can be measured
is the other side of MV = PQ: the Kina that changes hands (P × Q, from the sales ``trades.py``
infers) and the price level (P, an index). Spending growing faster than prices means more money is
circulating, or circulating faster: on a young server, mostly players farming Kina. The market
fee is a money sink: ``fee`` × spending is Kina the market destroys each day.

All of it is measured on a fixed basket: items priced on at least ``BASKET_SHARE`` of the last
``WINDOW_DAYS`` days, so the measures don't grow just because more items are tracked. The index
is the trimmed mean of each item's log price relative to its first day: a chained "what does the
same basket cost now".

None of it changes the ratings yet. Buys made while their section's index fell over the week did
worse in the backtest (-3% median after the fee, against +7% for all buys, in both halves of the
items), but there were only 29 of them: too few to act on. The market index and spending are the
same for every item on a day, and two weeks of days can't tell whether they predict anything. So
they are context; the section trend is logged with each live call and the backtest keeps the split,
to see whether it holds up.
"""

import math
import statistics
from collections import defaultdict
from datetime import date, timedelta

from .analysis import Profile

WINDOW_DAYS = 21     # the basket and the measures cover this many days
BASKET_SHARE = 0.9   # an item is in the basket when priced on this share of those days
TRIM = 0.1           # the index drops this share of the item moves at each end
SECTION_MIN = 8      # a section index needs this many basket items
TREND_DAYS = 7       # a section's trend: its index change over this many days


def _tmean(xs: list[float], trim: float = TRIM) -> float:
    xs = sorted(xs)
    n = int(len(xs) * trim)
    xs = xs[n:len(xs) - n] or xs
    return sum(xs) / len(xs)


def _index(daily: dict[date, dict[int, float]], days: list[date], keys: list[int]) -> dict[date, float]:
    """Log index by day: the trimmed mean of each item's log price relative to its first price."""
    base = {k: next(daily[d][k] for d in days if k in daily[d]) for k in keys}
    out = {}
    for d in days:
        moves = [math.log(daily[d][k] / base[k]) for k in keys if k in daily[d]]
        if moves:
            out[d] = _tmean(moves)
    return out


def build(profiles: dict[int, Profile], sections: dict[int, str], fee: float, window_days: int = WINDOW_DAYS,
          tz=None) -> dict:
    """The economy of the server ``profiles`` come from. Only complete days count: today is still
    filling in. Each list in the result has one value per day in ``days``."""
    last = max((p.closes[-1][0].date() for p in profiles.values() if p.closes), default=None)
    if last is None:
        return {"days": []}
    start = last - timedelta(days=window_days)
    daily: dict[date, dict[int, float]] = defaultdict(dict)
    for k, p in profiles.items():
        by_day = defaultdict(list)
        for t, v in p.closes:
            if start <= t.date() < last and v:
                by_day[t.date()].append(v)
        for d, vs in by_day.items():
            daily[d][k] = statistics.median(vs)
    days = sorted(daily)
    if len(days) < 2:
        return {"days": []}
    basket = [k for k in profiles if sum(k in daily[d] for d in days) >= BASKET_SHARE * len(days)]
    if not basket:
        return {"days": []}
    index = _index(daily, days, basket)
    by_section = defaultdict(list)
    for k in basket:
        by_section[sections.get(k) or "other"].append(k)
    section_index = {s: _index(daily, days, keys) for s, keys in by_section.items() if len(keys) >= SECTION_MIN}

    sales, spent, by_hour = defaultdict(int), defaultdict(float), [0] * 24
    for k in basket:
        for t, v in profiles[k].trades.sales:
            if start <= t.date() < last:
                sales[t.date()] += 1
                spent[t.date()] += v
                by_hour[(t.astimezone(tz) if tz else t).hour] += 1

    def series(values: dict[date, float], log: bool = False) -> list[float | None]:
        return [round(math.exp(values[d]) if log else values[d], 4) if d in values else None for d in days]

    def change(values: dict[date, float], n: int) -> float | None:
        if len(days) <= n or days[-1] not in values or days[-1 - n] not in values:
            return None
        return math.exp(values[days[-1]] - values[days[-1 - n]]) - 1

    week = days[-TREND_DAYS:]
    before = days[-2 * TREND_DAYS:-TREND_DAYS]

    def per_day(values, span):
        return sum(values[d] for d in span) / len(span) if span else None

    spent_week, spent_before = per_day(spent, week), per_day(spent, before)
    sales_week, sales_before = per_day(sales, week), per_day(sales, before)
    return {
        "days": [d.isoformat() for d in days],
        "basket": len(basket),
        "index": series(index, log=True),
        "sections": {s: series(v, log=True) for s, v in section_index.items()},
        "sales": [sales[d] for d in days],
        "spent": [round(spent[d]) for d in days],
        "fee_sink": [round(spent[d] * fee) for d in days],
        # sales by local hour: when buyers are about (evenings sell ~1.8× as fast as early mornings)
        "sales_by_hour": by_hour,
        "summary": {
            "inflation_week": change(index, TREND_DAYS),
            "inflation_window": change(index, len(days) - 1),
            "spent_per_day": spent_week,
            "spent_growth": spent_week / spent_before - 1 if spent_week and spent_before else None,
            "sales_per_day": sales_week,
            "sales_growth": sales_week / sales_before - 1 if sales_week and sales_before else None,
            "fee_sink_per_day": spent_week * fee if spent_week else None,
            "section_trend": {s: change(v, TREND_DAYS) for s, v in section_index.items()},
        },
        # for the valuation and its backtest: {section: {day: log index}}
        "_section_log": section_index,
    }


def section_trend(econ: dict, section: str | None, day: date | None = None, days: int = TREND_DAYS) -> float | None:
    """How much the section's index changed over the ``days`` up to ``day`` (default: the latest)."""
    log = econ.get("_section_log", {}).get(section or "other")
    if not log:
        return None
    end = day if day is not None else max(log)
    if end not in log:
        end = max((d for d in log if d <= end), default=None)
        if end is None:
            return None
    then = end - timedelta(days=days)
    if then not in log:
        return None
    return math.exp(log[end] - log[then]) - 1
