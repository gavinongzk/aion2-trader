import unittest
from datetime import datetime, timedelta, timezone

from aion2.analysis import Profile

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def profile(listings: list[int]) -> Profile:
    """An item without sales statistics, with one listing count per hour."""
    p = Profile(1, "x", price=100, listings=listings[-1], units_sold=None, sold_avg=None)
    p.listing_counts = [(T0 + timedelta(hours=h), n) for h, n in enumerate(listings)]
    p.closes = [(t, 100) for t, _ in p.listing_counts]
    return p


class EstimatedDemand(unittest.TestCase):
    def test_counts_listings_that_disappear(self):
        # 10 → 7 → 9 → 4 over 24 hours: 3 + 5 = 8 listings gone in one day
        counts = [10, 7, 9, 4] + [4] * 21
        p = profile(counts)
        self.assertTrue(p.estimated)
        self.assertAlmostEqual(p.per_day, 8.0)
        self.assertIn("(est.)", p.demand())

    def test_trend_compares_this_week_with_last(self):
        # last week: one listing taken every hour; this week: every other hour
        last_week = [100 - h for h in range(24 * 7)]
        this_week = [last_week[-1] - (h + 1) // 2 for h in range(24 * 7)]
        p = profile(last_week + this_week)
        self.assertAlmostEqual(p.demand_trend, -0.5, delta=0.02)

    def test_sales_statistics_win_when_present(self):
        p = profile([10, 5, 10, 5] + [5] * 21)
        p.units_sold = 280
        self.assertFalse(p.estimated)
        self.assertAlmostEqual(p.per_day, 10.0)


if __name__ == "__main__":
    unittest.main()
