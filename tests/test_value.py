import math
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from aion2 import db, scorecard
from aion2.analysis import Profile
from aion2.collect import price_request
from aion2.config import Config
from aion2.value import (Estimate, add_context, assess, backtest, blend, craft_costs, fill_rates, history_estimate,
                         ideas, load, peer_estimate)

NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)
CFG = Config()


def series(path, days=10):
    """Hourly (time, value) points, ``path(hours_ago)``."""
    return [(NOW - timedelta(hours=h), path(h)) for h in range(int(days * 24), -1, -1)]


def profile(now, path, days=10):
    """An item priced now at ``now``; its listings dip and refill each hour, so it trades often."""
    return Profile(1, "Ore", now, 20, None, None, closes=series(path, days),
                   listing_counts=series(lambda h: 20 - h % 2 * 3, days))


def hist(price, sigma=0.2):
    return Estimate("history", price, sigma, 1.0)


def peer(level):
    return {"key": 2, "name": "Blade", "ratio": 1.0, "home_level": level, "implied": level, "servers": 6,
            "spread": 0.05, "weight": 1.0}


class HistoryEstimate(unittest.TestCase):
    def test_follows_the_recent_level(self):
        # 100 for a week and a half, 50 for the last day: the level is today's, not the old one
        est = history_estimate(series(lambda h: 50 if h <= 24 else 100))
        self.assertEqual(est.price, 50)

    def test_one_cheap_hour_does_not_move_it(self):
        est = history_estimate(series(lambda h: 40 if h == 0 else 100))
        self.assertEqual(est.price, 100)

    def test_sigma_is_the_daily_spread(self):
        steady = history_estimate(series(lambda h: 100))
        jumpy = history_estimate(series(lambda h: 100 * (1 + 0.3 * math.sin(h // 24))))
        self.assertLess(steady.sigma, jumpy.sigma)

    def test_short_history_is_uncertain(self):
        self.assertEqual(history_estimate(series(lambda h: 100, days=1)).sigma, 0.25)


class PeerEstimate(unittest.TestCase):
    META = {1: {"name": "Sword", "category": "Swords"}, 2: {"name": "Blade", "category": "Swords"},
            3: {"name": "Relic", "category": "Swords"}}

    def prices(self, ratio=2.0, servers=6):
        """Home is server 0; on the others item 1 costs ``ratio`` × item 2, at different price levels."""
        return {0: {}} | {s: {1: {"price": 100 * ratio * (1 + s / 10)}, 2: {"price": 100 * (1 + s / 10)}}
                          for s in range(1, servers + 1)}

    def test_ratio_times_home_level(self):
        est, peers = peer_estimate(1, self.META, self.prices(), 0, {2: 150}, CFG)
        self.assertAlmostEqual(est.price, 300)
        self.assertAlmostEqual(peers[0]["ratio"], 2.0)

    def test_another_tier_is_not_a_peer(self):
        est, _ = peer_estimate(1, self.META, self.prices(ratio=10), 0, {2: 150}, CFG)
        self.assertIsNone(est)

    def test_needs_enough_servers(self):
        est, _ = peer_estimate(1, self.META, self.prices(servers=3), 0, {2: 150}, CFG)
        self.assertIsNone(est)


class Blend(unittest.TestCase):
    def test_home_history_counts_more_at_equal_precision(self):
        fair, _, shares = blend([hist(100, 0.1), Estimate("peers", 200, 0.1, 1.0)], home_weight=2)
        self.assertAlmostEqual(shares[0], 2 / 3)
        self.assertLess(fair, math.sqrt(100 * 200))

    def test_peer_share_is_capped(self):
        # noisy history, tight peers: the peers would take nearly all the weight
        _, _, shares = blend([hist(100, 0.8), Estimate("peers", 200, 0.05, 1.0)], 2, max_peer_share=0.5)
        self.assertEqual(shares, [0.5, 0.5])

    def test_disagreement_widens_sigma(self):
        _, close, _ = blend([hist(100), Estimate("peers", 105, 0.1, 1.0)], 2)
        _, far, _ = blend([hist(100), Estimate("peers", 300, 0.1, 1.0)], 2)
        self.assertGreater(far, close)


class Assess(unittest.TestCase):
    def test_below_fair_value_is_a_buy_with_a_buy_price(self):
        v = assess(profile(85, lambda h: 100), hist(100), None, [], CFG)
        self.assertEqual(v["label"], "Buy")
        self.assertAlmostEqual(v["buy_below"], 90)
        self.assertGreater(v["resale_roi"], 0)

    def test_far_below_is_a_strong_buy(self):
        self.assertEqual(assess(profile(70, lambda h: 100), hist(100), None, [], CFG)["label"], "Strong buy")

    def test_strong_buy_needs_the_peers_to_agree(self):
        # the peers barely move the fair value, but they say 70 isn't cheap: a buy, not a strong one
        v = assess(profile(70, lambda h: 100), hist(100), Estimate("peers", 75, 0.3, 1.0), [peer(75)], CFG)
        self.assertEqual(v["label"], "Buy")

    def test_disagreeing_estimates_are_flagged(self):
        v = assess(profile(70, lambda h: 100), hist(100), Estimate("peers", 30, 0.1, 1.0), [peer(30)], CFG)
        self.assertTrue(any("disagree" in r for r in v["reasons"]))

    def test_overpriced_on_an_item_that_trades_is_a_sell(self):
        v = assess(profile(120, lambda h: 100), hist(100), None, [], CFG)
        self.assertEqual(v["label"], "Sell")
        self.assertAlmostEqual(v["list_at"], 120 * 0.97)  # just under the cheapest
        self.assertIn("sell", v["reasons"][0])

    def test_overpriced_on_a_slow_item_is_not_a_sell(self):
        slow = Profile(1, "Ore", 120, 2, None, None, closes=series(lambda h: 100), listing_counts=series(lambda h: 2))
        self.assertEqual(assess(slow, hist(100), None, [], CFG)["label"], "Overpriced")

    def test_far_over_fair_value_is_only_overpriced(self):
        # a troll ask: listing next to it isn't selling
        self.assertEqual(assess(profile(300, lambda h: 100), hist(100), None, [], CFG)["label"], "Overpriced")

    def test_close_to_fair_value_is_fair(self):
        self.assertEqual(assess(profile(98, lambda h: 100), hist(100), None, [], CFG)["label"], "Fair")

    def test_falling_price_says_wait(self):
        v = assess(profile(60, lambda h: 100 * 0.95 ** ((240 - h) / 24)), hist(100), None, [], CFG)
        self.assertEqual(v["label"], "Wait")

    def test_uncertain_value_needs_a_wider_margin(self):
        v = assess(profile(85, lambda h: 100), hist(100, sigma=0.5), None, [], CFG)
        self.assertEqual(v["label"], "Fair")
        self.assertAlmostEqual(v["margin"], 0.25)

    def test_margin_covers_a_high_fee(self):
        v = assess(profile(85, lambda h: 100), hist(100), None, [], replace(CFG, sales_fee=0.12))
        self.assertAlmostEqual(v["margin"], 1 - 0.88 / 1.03)
        self.assertGreater(v["resale_roi"], 0)  # 85 → 100, after 12%: still a profit
        self.assertEqual(v["label"], "Buy")

    def test_the_going_rate_is_not_a_bargain(self):
        # asks say 100, but recent sales went for 85: at 85 it's the going rate, not a buy
        v = assess(profile(85, lambda h: 100), Estimate("history", 100, 0.2, 1.0, "sales", 5, 0, 85), None, [], CFG)
        self.assertEqual(v["label"], "Fair")
        self.assertEqual(v["list_at"], 85)
        self.assertTrue(any("going rate" in r for r in v["reasons"]))

    def test_cheap_against_sales_too_is_a_buy(self):
        v = assess(profile(70, lambda h: 100), Estimate("history", 100, 0.2, 1.0, "sales", 5, 0, 90), None, [], CFG)
        self.assertIn(v["label"], ("Strong buy", "Buy"))

    def test_dear_asks_without_sales_are_only_overpriced(self):
        v = assess(profile(130, lambda h: 100), Estimate("history", 100, 0.2, 1.0, "no sales"), None, [], CFG)
        self.assertEqual(v["label"], "Overpriced")

    def test_not_listed_still_gets_a_buy_price(self):
        v = assess(profile(None, lambda h: 100), hist(100), None, [], CFG)
        self.assertEqual(v["label"], "Not listed")
        self.assertAlmostEqual(v["buy_below"], 90)


class Backtest(unittest.TestCase):
    def test_dips_that_come_back_pay(self):
        # 100, with a dip to 70 for a few hours every 3 days that comes straight back
        p = profile(100, lambda h: 70 if h % 72 in (0, 1, 2) else 100, days=20)
        result = backtest({1: p}, CFG)
        self.assertGreater(result["evaluations"], 0)
        self.assertLess(result["error_fair"], 0.05)


def valuation(key, label, now=80, fair=100):
    return {"key": key, "name": f"Item {key}", "label": label, "now": now, "fair": fair, "upside": fair / now - 1,
            "buy_below": 90, "sigma": 0.1, "z": -2.2, "reasons": ["The two disagree: ..."],
            "per_day": 3.0, "estimates": [{"source": "history", "weight": 0.7}, {"source": "peers", "weight": 0.3}]}


class Calls(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_only_buys_become_calls_most_upside_first(self):
        calls = ideas([valuation(1, "Fair"), valuation(2, "Buy", now=90), valuation(3, "Strong buy", now=60)])
        self.assertEqual([c.item_key for c in calls], [3, 2])
        self.assertEqual(calls[0].metrics["patterns"], ["strong buy"])
        self.assertEqual(calls[0].metrics["peer_share"], 0.3)
        self.assertTrue(calls[0].metrics["disagree"])

    def test_slow_sellers_are_scored_apart(self):
        v = valuation(1, "Buy") | {"per_day": 0.1}
        self.assertEqual(ideas([v])[0].metrics["patterns"], ["buy", "slow"])

    def test_logged_once_a_day_and_scored_against_fair_value(self):
        called = NOW - timedelta(hours=30)
        calls = {"value": ideas([valuation(1, "Buy")])}
        self.assertEqual(scorecard.record(self.conn, 1, calls, now=called), 1)
        self.assertEqual(scorecard.record(self.conn, 1, calls, now=called + timedelta(hours=1)), 0)
        for h, price in ((1, 85), (12, 101), (24, 95)):
            self.conn.execute("INSERT INTO item_snapshots VALUES (1, 1, ?, ?, 5, NULL, NULL)",
                              ((called + timedelta(hours=h)).isoformat(), price))
        self.assertEqual(scorecard.evaluate(self.conn, 1, 0.05, now=NOW), 1)
        lines, pending = scorecard.summary(self.conn, 1, now=NOW, strategy="value")
        self.assertEqual((lines[0].kind, lines[0].horizon_h, lines[0].n), ("buy", 24, 1))
        self.assertEqual(lines[0].hit_rate, 0)  # the 80th percentile of 85, 101, 95 is 99.4: short of 100
        self.assertEqual(pending, 1)
        self.assertIn("value (buy): 1d: 0% hit", scorecard.render(lines, pending)[0])


class Load(unittest.TestCase):
    def test_stale_series_is_extended_with_snapshots(self):
        conn = db.connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute("INSERT INTO items (server_id, item_key, name, price, listings) VALUES (1, 7, 'Ore', 90, 5)")
        db.save_response(conn, 1, *price_request(7), {"points": [
            {"ts": "2026-10-30T00:00:00Z", "close": 100, "listings": 5},
            {"ts": "2026-10-30T01:00:00Z", "close": 100, "listings": 5}]})
        for ts, price in (("2026-10-30T00:30:00Z", 1), ("2026-11-02T00:00:00Z", 90)):
            conn.execute("INSERT INTO item_snapshots VALUES (1, 7, ?, ?, 5, NULL, NULL)", (ts, price))
        p = load(conn, 1, CFG)[7]
        # the snapshot inside the series is skipped, the one after it is added
        self.assertEqual([c for _, c in p.closes], [100, 100, 90])


if __name__ == "__main__":
    unittest.main()


class Context(unittest.TestCase):
    def test_below_craft_cost_is_flagged_and_scored_apart(self):
        v = {"key": 1, "name": "Blade", "label": "Fair", "now": 80, "reasons": ["Fair value 100."]}
        add_context(v, profile(80, lambda h: 80), CFG, craft_cost=100)
        self.assertEqual(v["craft_cost"], 100)
        self.assertIn("Below its craft cost", v["reasons"][1])
        self.assertEqual([i.metrics["patterns"] for i in ideas([v | {"upside": 0.25}])], [["below cost"]])

    def test_crafting_that_pays(self):
        v = {"now": 150, "reasons": []}
        add_context(v, profile(150, lambda h: 150), CFG, craft_cost=100)
        self.assertTrue(any("Crafting it pays" in r for r in v["reasons"]))

    def test_fill_rates(self):
        # a listing sells every other hour at the asking price: buyers always came within a day
        f = fill_rates(profile(100, lambda h: 100), CFG)
        self.assertEqual((f["fill_1d"], f["fill_3d"]), (1.0, 1.0))


class CraftCosts(unittest.TestCase):
    def test_materials_at_their_market_level_or_listed_price(self):
        conn = db.connect(":memory:")
        self.addCleanup(conn.close)
        db.save_response(conn, 1, "/crafts/9", {}, {"target_key": 9, "steps": [{"materials": [
            {"material_key": 1, "expected": 3, "unit_price": 50, "method": "buy"},
            {"material_key": 2, "expected": 2, "unit_price": 10, "method": "npc"}]}]})
        self.assertAlmostEqual(craft_costs(conn, 1, {1: profile(100, lambda h: 100)})[9], 3 * 100 + 2 * 10)
