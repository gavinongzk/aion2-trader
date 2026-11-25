import unittest
from datetime import date

from aion2 import archive, db


class FakeSupabase:
    def __init__(self):
        self.rows, self.deleted_before = {}, None

    def upsert(self, table, rows, on_conflict):
        for r in rows:
            self.rows[(r["server_id"], r["item_key"], r["day"])] = r

    def delete_before(self, table, column, value):
        self.deleted_before = value
        self.rows = {k: v for k, v in self.rows.items() if v["day"] >= value}


class Upload(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        rows = [(s, 7, f"2026-11-{d:02d}T{h:02d}:00:00Z", p * s, 5, None, None)
                for d in range(20, 26) for h, p in ((0, 90), (8, 100), (16, 110)) for s in (1, 2)]
        self.conn.executemany("INSERT INTO item_snapshots VALUES (?,?,?,?,?,?,?)", rows)
        self.conn.execute("INSERT INTO daily_prices VALUES (2, 7, '2026-11-01', 150, 4)")  # rolled up earlier

    def test_first_upload_then_only_new_days(self):
        s = FakeSupabase()
        sent = archive.upload(self.conn, s, log=lambda *_: None, today=date(2026, 11, 25))
        self.assertEqual(sent, 2 * 5 + 1)  # 20th-24th from snapshots, 2 servers, plus the rolled-up day
        self.assertEqual(s.rows[(1, 7, "2026-11-24")]["price"], 100)  # the day's median
        self.assertNotIn((1, 7, "2026-11-25"), s.rows)  # today isn't complete
        self.assertEqual(archive.upload(self.conn, s, log=lambda *_: None, today=date(2026, 11, 25)), 0)
        self.assertEqual(archive.upload(self.conn, s, log=lambda *_: None, today=date(2026, 11, 26)), 2)  # the 25th

    def test_old_days_are_deleted(self):
        s = FakeSupabase()
        archive.upload(self.conn, s, log=lambda *_: None, today=date(2026, 12, 5))
        self.assertEqual(s.deleted_before, "2026-11-05")
        self.assertNotIn((2, 7, "2026-11-01"), s.rows)


if __name__ == "__main__":
    unittest.main()
