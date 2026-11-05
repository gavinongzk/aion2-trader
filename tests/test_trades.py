import unittest
from datetime import datetime, timedelta, timezone

from aion2.trades import infer
from aion2.value import NO_SALES_SIGMA, history_estimate

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def hourly(points):
    """(cheapest price, listings) per hour → the two series ``infer`` takes."""
    times = [T0 + timedelta(hours=h) for h in range(len(points))]
    return [(t, c) for t, (c, _) in zip(times, points)], [(t, n) for t, (_, n) in zip(times, points)]


class Infer(unittest.TestCase):
    def test_cheapest_listing_bought(self):
        # 3 listings, the 100 one goes after 5 hours: bought at 100
        t = infer(*hourly([(100, 3)] * 5 + [(120, 2)] * 5))
        self.assertEqual([p for _, p in t.sales], [100])
        self.assertEqual(t.expired, [])

    def test_cheapest_listing_that_sat_two_days_expired(self):
        t = infer(*hourly([(100, 3)] * 49 + [(120, 2)] * 5))
        self.assertEqual(t.sales, [])
        self.assertEqual([p for _, p in t.expired], [100])
        self.assertEqual(t.taken, [])  # an expiry isn't demand

    def test_drop_two_days_after_a_listing_is_its_expiry(self):
        # a dearer listing added at hour 2 lapses at hour 50; the one at hour 60 has no such match
        points = [(100, 3)] * 2 + [(100, 4)] * 48 + [(100, 3)] * 10 + [(100, 2)] * 5
        t = infer(*hourly(points))
        self.assertEqual(t.taken, [(T0 + timedelta(hours=60), 1)])
        self.assertEqual([p for _, p in t.sales], [100])


class SoldEstimate(unittest.TestCase):
    def test_unsold_asks_widen_the_range(self):
        closes, counts = hourly([(100, 3)] * 24 * 5)
        asks = history_estimate(closes, sold=None)
        unproven = history_estimate(closes, sold=infer(closes, counts))
        self.assertEqual(unproven.basis, "no sales")
        self.assertAlmostEqual(unproven.sigma ** 2, asks.sigma ** 2 + NO_SALES_SIGMA ** 2)

    def test_expired_ask_caps_the_value(self):
        # 150 for 3 days, then a lone 90 sits two days unsold and lapses; asks are back at 150
        closes, counts = hourly([(150, 5)] * 72 + [(90, 6)] * 48 + [(150, 5)] * 12)
        est = history_estimate(closes, sold=infer(closes, counts))
        self.assertEqual((est.basis, est.price), ("expired", 90))

    def test_recent_sale_prices(self):
        # asks at 100, but every few hours one sells at a dip to 80
        points = [(100, 5)] * 24 * 3
        for h in range(5, len(points) - 1, 6):
            points[h] = (80, 6)  # a cheap one listed...
            points[h + 1] = (100, 5)  # ...and bought within the hour
        closes, counts = hourly(points)
        est = history_estimate(closes, sold=infer(closes, counts))
        self.assertEqual(est.basis, "sales")
        self.assertEqual(est.price, 100)
        self.assertEqual(est.sold_at, 80)


if __name__ == "__main__":
    unittest.main()
