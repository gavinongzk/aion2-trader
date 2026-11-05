import tempfile
import unittest
from pathlib import Path

from aion2 import analysis, collect, db, report
from aion2.config import Config
from tests import fake_api


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, base_url = fake_api.start()
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        cls.cfg = Config(base_url=base_url, db=str(tmp / "t.db"), reports=str(tmp / "reports"), delay_seconds=0)
        collect.run(cls.cfg, log=lambda *a: None)
        cls.conn = db.connect(cls.cfg.db)
        cls.server_id, cls.ideas = analysis.analyze(cls.conn, cls.cfg)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def names(self, strategy):
        return [i.name for i in self.ideas[strategy]]

    def test_uses_default_server(self):
        self.assertEqual(self.server_id, 7)

    def test_flip_finds_underpriced_item_and_buys_up_the_ladder(self):
        self.assertEqual(self.names("flip"), ["Cheap Ore"])
        idea = self.ideas["flip"][0]
        # 20 wanted, but only the 3 @ 7000 clear a 10% return; the 9600 ones don't
        self.assertEqual(idea.metrics["qty"], 3)
        self.assertAlmostEqual(idea.metrics["unit_cost"], 7000)
        self.assertTrue(any("underpriced" in r for r in idea.reasons))

    def test_craft_skips_missing_prices_and_applies_fee(self):
        self.assertEqual(self.names("craft"), ["Splendent Blade"])
        idea = self.ideas["craft"][0]
        self.assertAlmostEqual(idea.metrics["net"], 520000 * 0.95 - 392000)
        self.assertAlmostEqual(idea.metrics["consistency"], 44 / 56)
        self.assertTrue(any("Star Dragon Scale" in r and "craft" in r for r in idea.reasons))

    def test_speculation_patterns(self):
        by_name = {i.name: i for i in self.ideas["speculate"]}
        self.assertIn("dip", by_name["Dipping Scale"].metrics["patterns"])
        rising = by_name["Rising Essence"].metrics["patterns"]
        self.assertIn("uptrend", rising)
        self.assertNotIn("Dead Relic", by_name)  # too few sales
        self.assertNotIn("Sliding Scale", by_name)  # a steady slide is not a dip
        self.assertNotIn("Cheap Ore", by_name)   # one cheap listing is a flip, not a dip

    def test_report_files(self):
        path = report.write(self.server_id, self.ideas, self.cfg)
        folder = path.parent
        for name in ("latest.md", "latest.csv", "latest.json"):
            self.assertTrue((folder / name).exists())
        self.assertIn("Cheap Ore", path.read_text())


if __name__ == "__main__":
    unittest.main()
