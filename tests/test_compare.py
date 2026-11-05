import unittest

from aion2 import db
from aion2.analysis import latest_server
from aion2.compare import build, comparable, typical_ratio

SERVERS = [
    {"server_id": 1, "name": "Home", "region": "AS", "faction": "Asmodian"},
    {"server_id": 2, "name": "Cheap", "region": "AS", "faction": "Elyos"},
    {"server_id": 3, "name": "Plain", "region": "AS", "faction": "Asmodian"},
    {"server_id": 4, "name": "Away", "region": "EU", "faction": "Asmodian"},
]


def add(conn, server_id, key, price, listings=5):
    conn.execute("INSERT OR REPLACE INTO items (server_id, item_key, name, category, section_id, price, listings, updated_at) "
                 "VALUES (?, ?, ?, 'Ore', 'materials', ?, ?, ?)", (server_id, key, f"Item {key}", price, listings, db.now()))


class HomeServer(unittest.TestCase):
    def test_home_survives_other_servers_updating_later(self):
        conn = db.connect(":memory:")
        self.addCleanup(conn.close)
        db.set_home_server(conn, 1)
        add(conn, 1, 10, 100)
        add(conn, 2, 10, 100)  # compare stores another server after yours
        self.assertEqual(latest_server(conn), 1)


class Comparable(unittest.TestCase):
    def test_region_takes_both_factions(self):
        self.assertEqual([s["server_id"] for s in comparable(SERVERS, SERVERS[0])], [1, 2, 3])

    def test_faction_scope(self):
        self.assertEqual([s["server_id"] for s in comparable(SERVERS, SERVERS[0], "faction")], [1, 3])


class TypicalRatio(unittest.TestCase):
    def test_not_stuck_at_one_when_most_items_match(self):
        # a plain median would say 1.0; the server is dearer on 4 items of 10
        self.assertGreater(typical_ratio([1.0] * 6 + [1.3] * 4), 1.05)

    def test_one_absurd_ratio_is_trimmed(self):
        self.assertAlmostEqual(typical_ratio([1.0] * 9 + [500.0]), 1.0)


class Build(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        for key, base in ((10, 100), (11, 1000), (12, 50)):
            add(self.conn, 1, key, base * 1.2)   # home: 20% dearer
            add(self.conn, 2, key, base * 0.8)   # cheap: 20% cheaper
            add(self.conn, 3, key, base)
        add(self.conn, 3, 13, 999)               # on one server only: not compared
        add(self.conn, 2, 12, 1, listings=1)     # a lone listing doesn't count
        self.data = build(self.conn, 1, SERVERS[:3], min_servers=2)
        self.addCleanup(self.conn.close)

    def test_index_and_ratio_to_home(self):
        servers = {s["id"]: s for s in self.data["servers"]}
        # item 12 is on home and plain only, so its median is 55 and home's ratio 60 / 55
        self.assertAlmostEqual(servers[1]["index"], (1.2 * 1.2 * 60 / 55) ** (1 / 3), places=4)
        self.assertAlmostEqual(servers[2]["index"], 0.8, places=2)
        self.assertAlmostEqual(servers[2]["vs_home"], 0.8 / 1.2, places=2)
        self.assertEqual(servers[2]["cheapest_count"], 2)

    def test_items(self):
        items = {it["key"]: it for it in self.data["items"]}
        self.assertEqual(sorted(items), [10, 11, 12])
        self.assertEqual(items[10]["cheapest"]["server_id"], 2)
        self.assertAlmostEqual(items[10]["spread"], 116 / 84)  # 90th / 10th percentile of 80, 100, 120
        self.assertEqual(items[12]["servers"], 2)
        self.assertAlmostEqual(items[11]["home_ratio"], 1.2)


if __name__ == "__main__":
    unittest.main()
