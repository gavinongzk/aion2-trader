import tempfile
import unittest
from pathlib import Path

from aion2 import analysis, db, watch
from aion2.stats import parse_kina


class Watches(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(str(Path(self.tmp.name) / "w.db"))
        self.set_price(1000)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def set_price(self, price):
        self.conn.execute("INSERT OR REPLACE INTO items (server_id, item_key, name, price, listings) "
                          "VALUES (1, 42, 'Sealed Blue Wave Wings', ?, 5)", (price,))

    def test_alerts_once_then_again_only_when_cheaper(self):
        watch.add(self.conn, 7, 1, 42, 900, channel_id=99)
        self.assertEqual(watch.due(self.conn, 1), [])          # 1000 > 900
        self.set_price(850)
        [alert] = watch.due(self.conn, 1)
        self.assertEqual((alert.user_id, alert.channel_id, alert.price), (7, 99, 850))
        self.assertEqual(watch.due(self.conn, 1), [])          # same listing: no repeat
        self.set_price(800)
        self.assertEqual(len(watch.due(self.conn, 1)), 1)      # cheaper again
        self.set_price(1200)
        self.assertEqual(watch.due(self.conn, 1), [])          # back above: re-armed
        self.set_price(890)
        self.assertEqual(len(watch.due(self.conn, 1)), 1)

    def test_add_updates_and_remove(self):
        watch.add(self.conn, 7, 1, 42, 900, channel_id=99)
        watch.add(self.conn, 7, 1, 42, 1100, channel_id=98)
        [row] = watch.of_user(self.conn, 7, 1)
        self.assertEqual((row["below"], row["name"]), (1100, "Sealed Blue Wave Wings"))
        self.assertTrue(watch.remove(self.conn, 7, 1, 42))
        self.assertFalse(watch.remove(self.conn, 7, 1, 42))

    def test_search_matches_every_word(self):
        self.conn.execute("INSERT INTO items (server_id, item_key, name, listings) VALUES (1, 43, 'Blue Ore', 9)")
        self.assertEqual([r["item_key"] for r in analysis.search_items(self.conn, 1, "blue wings")], [42])
        self.assertEqual([r["item_key"] for r in analysis.search_items(self.conn, 1, "blue")], [43, 42])


class ParseKina(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(parse_kina("250k"), 250_000)
        self.assertEqual(parse_kina("1.5M"), 1_500_000)
        self.assertEqual(parse_kina("12,000"), 12_000)
        for bad in ("abc", "-5", "0"):
            with self.assertRaises(ValueError):
                parse_kina(bad)


if __name__ == "__main__":
    unittest.main()
