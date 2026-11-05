import unittest
from datetime import datetime, timedelta, timezone

from aion2 import economy
from aion2.analysis import Profile

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
DAYS = 15


def item(key, price, sold_every=None):
    """Hourly prices ``price(day)``; with ``sold_every`` hours, a listing is bought that often."""
    p = Profile(key, f"item {key}", None, None, None, None)
    for h in range(DAYS * 24):
        t = T0 + timedelta(hours=h)
        listings = 5 - (sold_every is not None and h % sold_every == sold_every - 1)
        p.closes.append((t, price(h // 24)))
        p.listing_counts.append((t, listings))
    return p


class Build(unittest.TestCase):
    def setUp(self):
        # 10 weapons doubling over the window, 10 armor pieces flat; the weapons trade
        self.profiles = {k: item(k, lambda d: 100 * 2 ** (d / (DAYS - 2)), sold_every=6) for k in range(10)}
        self.profiles |= {k: item(k, lambda d: 50) for k in range(10, 20)}
        self.sections = {k: "weapons" if k < 10 else "armor" for k in self.profiles}
        self.econ = economy.build(self.profiles, self.sections, fee=0.12)

    def test_today_is_left_out(self):
        self.assertEqual(len(self.econ["days"]), DAYS - 1)

    def test_section_indexes(self):
        self.assertAlmostEqual(self.econ["sections"]["weapons"][-1], 2.0, places=2)
        self.assertAlmostEqual(self.econ["sections"]["armor"][-1], 1.0)
        self.assertGreater(economy.section_trend(self.econ, "weapons"), 0.3)
        self.assertAlmostEqual(economy.section_trend(self.econ, "armor"), 0.0)

    def test_the_trimmed_index_is_between_the_sections(self):
        self.assertTrue(1.0 < self.econ["index"][-1] < 2.0)

    def test_spending_and_the_fee_sink(self):
        last = self.econ["sales"][-1]
        self.assertGreater(last, 0)
        self.assertEqual(self.econ["fee_sink"][-1], round(self.econ["spent"][-1] * 0.12))
        self.assertIsNotNone(self.econ["summary"]["spent_per_day"])

    def test_an_item_seen_on_few_days_stays_out_of_the_basket(self):
        self.profiles[99] = item(99, lambda d: 1000)
        self.profiles[99].closes = self.profiles[99].closes[-48:]
        self.assertEqual(economy.build(self.profiles, self.sections, 0.12)["basket"], 20)

    def test_sales_by_hour(self):
        hours = self.econ["sales_by_hour"]
        self.assertEqual(len(hours), 24)
        self.assertEqual(sum(hours), sum(self.econ["sales"]))

    def test_trend_at_a_past_day(self):
        early = datetime(2026, 10, 3).date()
        self.assertIsNone(economy.section_trend(self.econ, "weapons", early))  # no week before it


if __name__ == "__main__":
    unittest.main()
