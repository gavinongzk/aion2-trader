"""What sold, and what didn't, inferred from the hourly cheapest price and listing count.

The API has no sales: only asks. But a listing leaves the market one of two ways: someone buys it,
or it expires ``listing_hours`` after it was listed (2 days in Aion 2). So:

  sale      the cheapest listing went (the count fell and the cheapest price rose) before it could
            have expired: someone paid that price
  expired   the cheapest listing went at about its expiry age: nobody paid that price in 2 days
  other     the count fell with the cheapest price unchanged: one of several listings at that price
            sold, or a dearer listing expired. Listings are followed in cohorts by when they were
            listed; each sale takes a random listing, so a cohort's unsold share shrinks with every
            sale, and what's left of it a listing life later is the expected expiry. The rest are
            sales. (Matching every drop to any listing added 2 days before took most sales of a
            busy item for expiries: new listings arrive every hour, but few of them last 2 days.)

On Hadala the cheapest listing goes within 12 hours 94% of the time, so most of its departures are
sales. Expiry is mostly the fate of the dearer listings: the asks nobody pays.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

SLACK_H = 8  # the cheapest price is hourly, so "listed at" is only known roughly: this close to expiry counts


@dataclass
class Trades:
    sales: list = field(default_factory=list)    # (time, price): the cheapest listing bought at that price
    expired: list = field(default_factory=list)  # (time, price): the cheapest listing expired unsold
    taken: list = field(default_factory=list)    # (time, listings): listings that went other than by expiry

    def since(self, start: datetime, end: datetime | None = None) -> "Trades":
        def cut(xs):
            return [(t, v) for t, v in xs if t >= start and (end is None or t <= end)]

        return Trades(cut(self.sales), cut(self.expired), cut(self.taken))


def infer(closes: list, listing_counts: list, listing_hours: float = 48) -> Trades:
    """Sales, expiries and listings taken from (time, cheapest price) and (time, listings) series."""
    counts = dict(listing_counts)
    pts = [(t, c, counts[t]) for t, c in closes if c and counts.get(t) is not None]
    out = Trades()
    life = timedelta(hours=listing_hours)
    # listings by when they were listed: [time, how many, the share still unsold]. A sale takes a
    # random listing from the stock, so each sale shrinks every cohort's unsold share by sold/stock;
    # what's left of a cohort one listing life later expires. (The stock at the start counts as one
    # cohort listed then: its age is unknown.)
    cohorts = [[pts[0][0], pts[0][2], 1.0]] if pts else []
    listed_at = pts[0][0] if pts else None  # when the cheapest price took its current value
    for (t0, c0, l0), (t1, c1, l1) in zip(pts, pts[1:]):
        drop = l0 - l1
        if drop > 0:
            if c1 > c0:  # the cheapest listing went
                drop -= 1
                if t1 - listed_at >= life - timedelta(hours=SLACK_H):
                    out.expired.append((t1, c0))
                else:
                    out.sales.append((t1, c0))
                    out.taken.append((t1, 1))
            # the rest: what's due to expire of the cohorts one listing life old, then sales
            due = [c for c in cohorts if c[0] <= t1 - life]
            expiring = min(drop, sum(n * left for _, n, left in due))
            cohorts = [c for c in cohorts if c[0] > t1 - life]
            sold = drop - expiring
            if sold > 0:
                for c in cohorts:
                    c[2] *= max(0.0, 1 - sold / l0)
                if sold >= 0.5:
                    out.taken.append((t1, sold))
                    if c1 <= c0:  # buyers take the cheapest first: these sold at the cheapest price too
                        out.sales.append((t1, c0))
        elif drop < 0:
            cohorts.append([t1, -drop, 1.0])
        if c1 != c0:
            listed_at = t1
    return out
