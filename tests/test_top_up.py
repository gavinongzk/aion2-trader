import unittest
from datetime import datetime, timedelta, timezone

from aion2 import collect, db

NOW = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)  # fetch_cached checks against the clock


def points(hours_ago, price=100):
    return [{"ts": (NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:00:00Z"), "close": price} for h in hours_ago]


class FakeClient:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def get(self, path, **params):
        self.calls.append(params)
        return self.reply


class TopUp(unittest.TestCase):
    def test_recent_enough(self):
        self.assertTrue(collect.recent_enough({"points": points([3])}, NOW))
        self.assertFalse(collect.recent_enough({"points": points([30])}, NOW))
        self.assertFalse(collect.recent_enough(None, NOW))

    def test_merge_keeps_30_days_and_newer_wins(self):
        old = {"points": points([24 * 31, 24 * 10, 2], price=100), "range_start": "x"}
        new = {"points": points([2, 1], price=120)}
        merged = collect.merge_points(old, new, now=NOW)
        self.assertEqual([p["close"] for p in merged["points"]], [100, 120, 120])  # the 31-day-old point went
        self.assertEqual(merged["range_start"], merged["points"][0]["ts"])

    def test_a_fresh_series_is_topped_up_a_stale_one_refetched(self):
        conn = db.connect(":memory:")
        self.addCleanup(conn.close)
        request = collect.price_request(7)
        fresh = points(range(30 * 24, 2, -1))
        db.save_response(conn, 1, *request, {"points": fresh})
        conn.execute("UPDATE responses SET fetched_at='2026-01-01T00:00:00+00:00'")  # older than the cache
        client = FakeClient({"points": points([1, 0], price=130)})
        self.assertTrue(collect.fetch_cached(client, conn, 1, request, 50, log=lambda *_: None))
        self.assertEqual(client.calls[0]["range"], collect.RECENT)
        stored = db.load_response(conn, 1, *request)
        self.assertEqual(stored["points"][-1]["close"], 130)
        self.assertGreater(len(stored["points"]), 600)  # the rest of the 30 days kept

        db.save_response(conn, 1, *request, {"points": points([48])})  # ends 2 days ago: refetch it all
        conn.execute("UPDATE responses SET fetched_at='2026-01-01T00:00:00+00:00'")
        client = FakeClient({"points": points([0])})
        collect.fetch_cached(client, conn, 1, request, 50, log=lambda *_: None)
        self.assertEqual(client.calls[0]["range"], "30d")


if __name__ == "__main__":
    unittest.main()
