"""Shift detection, timing patterns, material leads and the scorecard, on made-up series."""

import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from aion2 import db, scorecard, timing
from aion2.analysis import Idea, Profile, material_lead
from aion2.stats import level_shift

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
UTC = ZoneInfo("UTC")


def daily(prices):
    return [(T0 + timedelta(days=i, hours=23), p) for i, p in enumerate(prices)]


def hourly(price_at, days=14):
    return [(T0 + timedelta(hours=h), price_at(h)) for h in range(24 * days)]


class Shifts(unittest.TestCase):
    def test_finds_a_step(self):
        prices = [100, 102, 99, 101, 100, 98, 101, 60, 61, 59, 60]
        when, ratio = level_shift(daily(prices))
        self.assertEqual(when.date(), (T0 + timedelta(days=7)).date())
        self.assertAlmostEqual(ratio, 0.6, delta=0.03)

    def test_ignores_a_steady_slide_and_noise(self):
        self.assertIsNone(level_shift(daily([100 * 0.96 ** i for i in range(14)])))
        self.assertIsNone(level_shift(daily([100, 110, 92, 105, 97, 108, 95, 103, 99, 106])))

    def test_ignores_a_supply_gap(self):  # only absurd listings left: ×50, not a new level
        self.assertIsNone(level_shift(daily([100] * 7 + [5000] * 4)))

    def test_profile_uses_only_days_since_the_shift(self):
        p = Profile(1, "x", price=60, listings=10, units_sold=None, sold_avg=None)
        p.closes = [(t + timedelta(hours=h), v) for t, v in daily([100] * 10 + [60] * 4) for h in (-12, 0)]
        p.listing_counts = [(t, 10) for t, _ in p.closes]
        self.assertIsNotNone(p.shift)
        self.assertEqual(p.usual, 60)
        self.assertIn("dropped 40%", p.shift_note())


class Timing(unittest.TestCase):
    def test_hour_of_day_pattern(self):
        # cheapest at 20:00, dearest at 08:00, on a falling trend that must not get in the way
        series = hourly(lambda h: 1000 * 0.99 ** (h / 24) * (1 + 0.06 * math.cos((h % 24 - 8) / 24 * 2 * math.pi)))
        p = timing.hourly(series, UTC)
        self.assertEqual((p.cheap, p.dear), (20, 8))
        self.assertTrue(timing.is_edge(p))
        self.assertIn("20:00", p.describe())

    def test_flat_series_has_no_edge(self):
        self.assertFalse(timing.is_edge(timing.hourly(hourly(lambda h: 500), UTC)))

    def test_weekday_needs_three_weeks(self):
        self.assertIsNone(timing.weekly(hourly(lambda h: 500, days=14), UTC))
        cheap_sunday = timing.weekly(hourly(lambda h: 400 if (T0 + timedelta(hours=h)).weekday() == 6 else 500,
                                            days=28), UTC)
        self.assertEqual(cheap_sunday.label(cheap_sunday.cheap), "Sun")


class MaterialLead(unittest.TestCase):
    def test_widening_names_the_material(self):
        ore = Profile(7, "Ore", 80, 10, None, None)
        ore.closes = [(T0 + timedelta(hours=h), 100 if h < 24 * 2 else 80) for h in range(24 * 5)]
        spend = {"Ore": [10, 800, {"buy"}, 7], "Stone": [5, 200, {"buy"}, 8]}
        text = material_lead(spend, {7: ore}, 1000, cost_change=-0.16, price_change=0.01)
        self.assertIn("margin widening", text)
        self.assertIn("Ore -20%", text)
        self.assertIsNone(material_lead(spend, {7: ore}, 1000, cost_change=-0.02, price_change=0.0))


class Scorecard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(str(Path(self.tmp.name) / "s.db"))
        self.conn.execute("INSERT INTO items (server_id, item_key, name, price, captured_at) "
                          "VALUES (1, 5, 'Ore', 100, ?)", (T0.isoformat().replace("+00:00", "Z"),))
        # hourly snapshots after the call: the price climbs from 100 to 130 over a week
        for h in range(0, 24 * 8):
            t = (T0 + timedelta(hours=h)).isoformat().replace("+00:00", "Z")  # the API's format
            self.conn.execute("INSERT INTO item_snapshots VALUES (1, 5, ?, ?, 10, NULL, NULL)",
                              (t, 100 + 30 * min(h, 168) / 168))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def ideas(self):
        return {"speculate": [Idea("speculate", 5, "Ore", 1.0, "dip", [],
                                   {"patterns": ["dip"], "entry": 100, "target": 120})]}

    def test_record_dedupes_within_a_day(self):
        self.assertEqual(scorecard.record(self.conn, 1, self.ideas(), now=T0), 1)
        self.assertEqual(scorecard.record(self.conn, 1, self.ideas(), now=T0), 0)

    def test_evaluate_and_summary(self):
        scorecard.record(self.conn, 1, self.ideas(), now=T0)
        self.assertEqual(scorecard.evaluate(self.conn, 1, fee=0.05, now=T0 + timedelta(days=8)), 3)
        lines, pending = scorecard.summary(self.conn, 1, now=T0 + timedelta(days=8))
        by_h = {l.horizon_h: l for l in lines}
        self.assertEqual(pending, 0)
        self.assertEqual(by_h[24].hit_rate, 0)       # 80th pct of the first day ~ 104 < 120
        self.assertEqual(by_h[168].hit_rate, 1)      # reached 120+ within the week
        self.assertAlmostEqual(by_h[168].median_ret, 130 * 0.95 / 100 - 1, places=2)
        text = scorecard.render(lines, pending)
        self.assertTrue(text[0].startswith("dip: 1d: 0% hit"))

    def test_horizon_without_data_is_given_up(self):
        scorecard.record(self.conn, 1, self.ideas(), now=T0)
        self.conn.execute("DELETE FROM item_snapshots WHERE captured_at > ?",
                          ((T0 + timedelta(hours=20)).isoformat(),))
        self.conn.execute("INSERT INTO item_snapshots VALUES (1, 6, ?, 1, 1, NULL, NULL)",
                          ((T0 + timedelta(days=9)).isoformat(),))  # the collector ran later, other items
        scorecard.evaluate(self.conn, 1, fee=0.05, now=T0 + timedelta(days=10))
        lines, pending = scorecard.summary(self.conn, 1, now=T0 + timedelta(days=10))
        self.assertEqual((lines, pending), ([], 0))

    def test_weekly_post_timer(self):
        self.assertTrue(scorecard.due_for_post(self.conn, 7, now=T0))
        scorecard.mark_posted(self.conn, now=T0)
        self.assertFalse(scorecard.due_for_post(self.conn, 7, now=T0 + timedelta(days=6)))
        self.assertTrue(scorecard.due_for_post(self.conn, 7, now=T0 + timedelta(days=7)))


if __name__ == "__main__":
    unittest.main()
