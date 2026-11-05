"""The bot's commands and embeds, without connecting to Discord. Skipped if discord.py is missing."""

import unittest

try:
    import discord
except ImportError:
    discord = None

from aion2.analysis import Idea, Profile
from aion2.config import Config


def total_length(embed) -> int:
    return len(embed.title or "") + len(embed.description or "") + len(embed.footer.text or "") + sum(
        len(f.name) + len(f.value) for f in embed.fields)


@unittest.skipIf(discord is None, "discord.py not installed")
class Bot(unittest.TestCase):
    def test_commands(self):
        from aion2.bot import TraderBot
        bot = TraderBot(Config())
        names = {c.qualified_name for c in bot.tree.walk_commands()}
        self.assertEqual(names, {"deals", "item", "refresh", "scorecard", "timing", "watch", "watch add", "watch remove", "watch list"})

    def test_ideas_embed_stays_within_discord_limits(self):
        from aion2 import views
        long_reason = "x" * 900
        ideas = [Idea("flip", i, f"Item {i}", 1.0, "buy 1 @ 1k, sell @ 2k: +900 (+90%)", [long_reason] * 3)
                 for i in range(10)]
        embed = views.ideas_embed("flip", ideas)
        self.assertEqual(len(embed.fields), 10)
        self.assertLessEqual(total_length(embed), 6000)
        self.assertTrue(all(len(f.value) <= 1024 for f in embed.fields))

    def test_empty_and_item_embeds(self):
        from aion2 import views
        self.assertIn("Nothing passes", views.ideas_embed("craft", []).description)
        bare = views.item_embed(Profile(1, "Odyle", None, 0, None, None), [])
        self.assertIn("Not listed", bare.description)


if __name__ == "__main__":
    unittest.main()
