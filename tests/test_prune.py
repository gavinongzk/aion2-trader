import unittest
from datetime import date

from aion2 import db
from aion2.value import snapshot_history, world_history


class Prune(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        rows = []
        for day in range(1, 25):  # 24 days of 3 snapshots a day, on the home server (1) and two others
            for hour, price in ((0, 90), (8, 100), (16, 110)):
                for server in (1, 2, 3):
                    rows.append((server, 7, f"2026-11-{day:02d}T{hour:02d}:00:00Z", price * server, 5, None, None))
        self.conn.executemany("INSERT INTO item_snapshots VALUES (?,?,?,?,?,?,?)", rows)

    def test_old_snapshots_become_one_row_a_day(self):
        rolled, deleted = db.prune(self.conn, 1, hourly_days=8, daily_days=30, today=date(2026, 11, 25))
        left = self.conn.execute("SELECT min(captured_at) FROM item_snapshots WHERE server_id=2").fetchone()[0]
        self.assertEqual(left[:10], "2026-11-17")
        self.assertEqual(rolled, 16 * 2)  # 16 days before the 17th, the 2 other servers
        price = self.conn.execute("SELECT price FROM daily_prices WHERE server_id=2 AND day='2026-11-05'").fetchone()[0]
        self.assertEqual(price, 200)  # the day's median

    def test_home_stays_hourly(self):
        db.prune(self.conn, 1, hourly_days=8, daily_days=30, today=date(2026, 11, 25))
        left = self.conn.execute("SELECT min(captured_at) FROM item_snapshots WHERE server_id=1").fetchone()[0]
        self.assertEqual(left[:10], "2026-11-01")

    def test_daily_rows_go_after_30_days(self):
        db.prune(self.conn, 1, hourly_days=8, daily_days=10, today=date(2026, 11, 25))
        first = self.conn.execute("SELECT min(day) FROM daily_prices").fetchone()[0]
        self.assertEqual(first, "2026-11-15")

    def test_readers_see_the_daily_rows(self):
        db.prune(self.conn, 1, hourly_days=8, daily_days=30, today=date(2026, 11, 25))
        closes, counts = snapshot_history(self.conn, 2, 7)
        self.assertEqual(closes[0][1], 200)                    # a daily row first...
        self.assertEqual(closes[-1][1], 220)                   # ...then the hourly ones
        self.assertEqual(counts[0][0].date(), date(2026, 11, 17))  # listing counts only hourly
        self.assertEqual(len(world_history(self.conn, 1)), 24)  # every day is still there for the world price


if __name__ == "__main__":
    unittest.main()
