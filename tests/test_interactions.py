"""The slash-command function (vercel/api/discord.py), without Discord or Vercel."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("interactions", Path(__file__).parent.parent / "vercel/api/discord.py")
fn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fn)

DATA = {
    "server_id": 1, "max_watches": 2,
    "deals": {"flip": {"title": "Flip", "fields": [{"name": f"{i}. x", "value": "v"} for i in range(1, 11)]}},
    "scorecard": {"title": "Scorecard", "fields": []}, "timing": {"title": "Timing", "fields": []},
    "items": [[7, "Orichalcum Ore", 2500, 40], [8, "Orichalcum Ingot", 4000, 12], [9, "Odyle", None, 0]],
    "cards": {"7": {"title": "Orichalcum Ore", "fields": []}},
}


class FakeSupabase:
    def __init__(self):
        self.rows = []

    def select(self, table, **eq):
        return [r for r in self.rows if all(r[k] == v for k, v in eq.items())]

    def upsert(self, table, row, on_conflict):
        self.rows = [r for r in self.rows if (r["user_id"], r["item_key"]) != (row["user_id"], row["item_key"])] + [row]

    def delete(self, table, **eq):
        before = len(self.rows)
        self.rows = [r for r in self.rows if not all(r[k] == v for k, v in eq.items())]
        return len(self.rows) < before


def command(name, options=(), sub=None):
    opts = [{"name": k, "value": v} for k, v in options]
    if sub:
        opts = [{"type": 1, "name": sub, "options": opts}]
    return {"type": 2, "data": {"name": name, "options": opts}, "member": {"user": {"id": "42"}}, "channel_id": "5"}


class Interactions(unittest.TestCase):
    def test_ping(self):
        self.assertEqual(fn.handle({"type": 1}, DATA), {"type": 1})

    def test_autocomplete_matches_every_word_most_listed_first(self):
        r = fn.handle({"type": 4, "data": {"name": "item", "options": [{"name": "name", "value": "ori", "focused": True}]}}, DATA)
        self.assertEqual([c["value"] for c in r["data"]["choices"]], ["7", "8"])

    def test_deals_count(self):
        r = fn.handle(command("deals", [("strategy", "flip"), ("count", 3)]), DATA)
        self.assertEqual(len(r["data"]["embeds"][0]["fields"]), 3)

    def test_item_card_or_a_basic_one(self):
        self.assertEqual(fn.handle(command("item", [("name", "7")]), DATA)["data"]["embeds"][0]["title"], "Orichalcum Ore")
        basic = fn.handle(command("item", [("name", "odyle")]), DATA)["data"]["embeds"][0]
        self.assertEqual(basic["description"], "No price history yet.")

    def test_watch_add_list_remove(self):
        s = FakeSupabase()
        r = fn.handle(command("watch", [("item", "8"), ("below", "3.5k")], sub="add"), DATA, s)
        self.assertIn("at or below **3.5k**", r["data"]["content"])
        self.assertEqual(r["data"]["flags"], 64)
        self.assertEqual((s.rows[0]["below"], s.rows[0]["channel_id"]), (3500, "5"))
        listed = fn.handle(command("watch", sub="list"), DATA, s)["data"]["embeds"][0]["description"]
        self.assertIn("**Orichalcum Ingot**: below 3.5k (now 4k)", listed)
        self.assertIn("Removed", fn.handle(command("watch", [("item", "8")], sub="remove"), DATA, s)["data"]["content"])
        self.assertEqual(s.rows, [])

    def test_watch_limit_and_bad_price(self):
        s = FakeSupabase()
        for key in ("7", "8"):
            fn.handle(command("watch", [("item", key), ("below", "1k")], sub="add"), DATA, s)
        self.assertIn("most allowed", fn.handle(command("watch", [("item", "9"), ("below", "1k")], sub="add"), DATA, s)["data"]["content"])
        self.assertIn("isn't a price", fn.handle(command("watch", [("item", "7"), ("below", "lots")], sub="add"), DATA, s)["data"]["content"])

    def test_refresh_dispatches(self):
        calls = []
        r = fn.handle(command("refresh"), DATA, dispatch=lambda: calls.append(1))
        self.assertEqual(calls, [1])
        self.assertIn("Started", r["data"]["content"])

    def test_signature(self):
        from nacl.signing import SigningKey
        key = SigningKey.generate()
        body, ts = b'{"type":1}', "1700000000"
        sig = key.sign(ts.encode() + body).signature.hex()
        public = key.verify_key.encode().hex()
        self.assertTrue(fn.verified(public, sig, ts, body))
        self.assertFalse(fn.verified(public, sig, ts, b'{"type":2}'))
        self.assertFalse(fn.verified(public, "zz", ts, body))


if __name__ == "__main__":
    unittest.main()
