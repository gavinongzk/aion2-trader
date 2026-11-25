import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from aion2 import db, publish
from aion2.analysis import Idea
from aion2.config import Config


def idea(key, name):
    return Idea("flip", key, name, 1.0, f"Buy {name}", ["cheap"])


class FakeSupabase:
    def __init__(self, watches):
        self.watches, self.updates = watches, []

    def select(self, table, **filters):
        return self.watches

    def update(self, table, values, **filters):
        self.updates.append((values, filters))


class Notify(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.cfg = replace(Config(), db=str(Path(self.dir.name) / "t.db"))
        conn = db.connect(self.cfg.db)
        conn.execute("INSERT INTO items (server_id, item_key, name, price, listings) VALUES (1, 7, 'Ore', 80, 3)")
        conn.commit()
        conn.close()
        self.sent = []
        self.ideas = {"flip": [idea(7, "Ore")]}
        patches = [mock.patch.object(publish.analysis, "analyze_all", lambda conn, cfg: (1, {}, self.ideas)),
                   mock.patch.object(publish.discord_rest, "send", lambda token, ch, content=None, embed=None,
                                     mention_users=False: self.sent.append((ch, content, embed)))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_first_run_posts_nothing_old_then_only_new_ideas(self):
        publish.notify(self.cfg, "t", 99, None, log=lambda *_: None)
        self.assertEqual(self.sent, [])  # what was already top before the first run isn't news
        self.ideas = {"flip": [idea(7, "Ore"), idea(8, "Blade")]}
        publish.notify(self.cfg, "t", 99, None, log=lambda *_: None)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual([f["name"] for f in self.sent[0][2]["fields"]], ["1. Blade"])

    def test_alerts_from_supabase(self):
        supa = FakeSupabase([{"user_id": "42", "item_key": 7, "below": 100, "channel_id": "5", "last_alert_price": None}])
        publish.notify(self.cfg, "t", None, supa, log=lambda *_: None)
        self.assertEqual(self.sent[0][0], "5")
        self.assertIn("<@42> **Ore** is listed at **80**", self.sent[0][1])
        self.assertEqual(supa.updates, [({"last_alert_price": 80}, {"user_id": "42", "server_id": 1, "item_key": 7})])


class Commands(unittest.TestCase):
    def test_definitions_are_valid(self):
        names = [c["name"] for c in publish.COMMANDS]
        self.assertEqual(names, ["deals", "item", "scorecard", "timing", "watch", "refresh"])
        self.assertTrue(all(len(c["description"]) <= 100 for c in publish.COMMANDS))
        for c in publish.COMMANDS:
            for o in c.get("options", []):
                self.assertLessEqual(len(o["description"]), 100, o["name"])


if __name__ == "__main__":
    unittest.main()
